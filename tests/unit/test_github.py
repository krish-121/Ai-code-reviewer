"""GitHub integration: signatures, event parsing, client retries, rendering, publishing."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import tarfile
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from sentinel.analysis.diff.parser import parse_unified_diff
from sentinel.core.domain.models import (
    Category,
    ChangeSet,
    Finding,
    FindingSource,
    ReviewResult,
    ReviewSummary,
    Severity,
    VerificationResult,
    VerificationStatus,
)
from sentinel.integrations.github.client import (
    MIN_PERMISSIONS,
    GitHubAppAuth,
    GitHubClient,
    GitHubError,
    StaticToken,
)
from sentinel.integrations.github.publisher import GitHubPublisher, commentable_lines
from sentinel.integrations.github.render import SUMMARY_MARKER, finding_comment, summary_comment
from sentinel.integrations.github.webhooks import parse_pull_request_event, verify_signature

DIFF = """\
diff --git a/app/db.py b/app/db.py
--- a/app/db.py
+++ b/app/db.py
@@ -30,3 +30,6 @@ def list_users(conn):


+def search_products(conn, term):
+    query = f"SELECT * FROM products WHERE name LIKE '%{term}%'"
+    return conn.execute(query).fetchall()
"""


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def pr_payload(action: str = "opened", draft: bool = False) -> dict[str, Any]:
    return {
        "action": action,
        "installation": {"id": 99},
        "repository": {"full_name": "acme/shop"},
        "pull_request": {
            "number": 7,
            "title": "Add search",
            "draft": draft,
            "html_url": "https://gh/pr/7",
            "user": {"login": "dev"},
            "head": {"sha": "h" * 40},
            "base": {"sha": "b" * 40},
        },
    }


# ----------------------------------------------------------------- webhooks


def test_signature_verification() -> None:
    body = b'{"a": 1}'
    assert verify_signature("s3cret", body, sign("s3cret", body))
    assert not verify_signature("s3cret", body, sign("other", body))
    assert not verify_signature("s3cret", body, None)
    assert not verify_signature("s3cret", body, "sha1=abc")
    assert not verify_signature("", body, sign("", body))


def test_parse_pull_request_event() -> None:
    ev = parse_pull_request_event("pull_request", pr_payload())
    assert ev is not None
    assert (ev.repo, ev.number, ev.installation_id, ev.head_sha) == ("acme/shop", 7, 99, "h" * 40)
    assert parse_pull_request_event("pull_request", pr_payload("closed")) is None
    assert parse_pull_request_event("pull_request", pr_payload(draft=True)) is None
    assert parse_pull_request_event("pull_request", pr_payload("ready_for_review", True))
    assert parse_pull_request_event("push", pr_payload()) is None
    assert parse_pull_request_event("pull_request", {"action": "opened"}) is None


# ----------------------------------------------------------------- client


class FakeGitHub:
    """Minimal in-memory GitHub REST API behind an httpx.MockTransport."""

    def __init__(self, tarball: bytes = b"") -> None:
        self.issue_comments: list[dict[str, Any]] = []
        self.review_comments: list[dict[str, Any]] = []
        self.reviews: list[dict[str, Any]] = []
        self.requests: list[httpx.Request] = []
        self.tarball = tarball
        self.fail_next: list[int] = []
        self.next_id = 100

    def __call__(self, req: httpx.Request) -> httpx.Response:
        """Route a request to the handler for its path, like GitHub's REST API would."""
        self.requests.append(req)
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0), text="rate limit exceeded")
        path, method = req.url.path, req.method
        if path == "/user":
            return httpx.Response(200, json={"id": 42})
        if path == "/repos/acme/shop/pulls/7" and method == "GET":
            return self._pull(req)
        if path.startswith("/repos/acme/shop/tarball/"):
            return httpx.Response(200, content=self.tarball)
        if path == "/repos/acme/shop/pulls/7/comments":
            page = int(req.url.params.get("page", "1"))
            return httpx.Response(200, json=self.review_comments if page == 1 else [])
        if path == "/repos/acme/shop/issues/7/comments":
            return self._issue_comments(req)
        if path.startswith("/repos/acme/shop/issues/comments/") and method == "PATCH":
            return self._edit_issue_comment(req)
        if path == "/repos/acme/shop/pulls/7/reviews" and method == "POST":
            return self._create_review(req)
        return httpx.Response(404, text=f"no route {method} {path}")

    def _pull(self, req: httpx.Request) -> httpx.Response:
        if "diff" in req.headers.get("accept", ""):
            return httpx.Response(200, text=DIFF)
        return httpx.Response(200, json=pr_payload()["pull_request"])

    def _issue_comments(self, req: httpx.Request) -> httpx.Response:
        if req.method != "POST":
            return httpx.Response(200, json=self.issue_comments)
        self.next_id += 1
        comment = {"id": self.next_id, "body": json.loads(req.content)["body"], "user": {"id": 42}}
        self.issue_comments.append(comment)
        return httpx.Response(201, json=comment)

    def _edit_issue_comment(self, req: httpx.Request) -> httpx.Response:
        comment_id = int(req.url.path.rsplit("/", 1)[-1])
        for comment in self.issue_comments:
            if comment["id"] == comment_id:
                comment["body"] = json.loads(req.content)["body"]
        return httpx.Response(200, json={"id": comment_id})

    def _create_review(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        self.reviews.append(body)
        for comment in body["comments"]:
            self.review_comments.append(
                {"body": comment["body"], "path": comment["path"], "user": {"id": 42}}
            )
        return httpx.Response(200, json={"id": len(self.reviews)})

    def client(self, sleeps: list[float] | None = None) -> GitHubClient:
        sink = sleeps if sleeps is not None else []
        return GitHubClient(
            StaticToken("tok"), transport=httpx.MockTransport(self), sleep=sink.append
        )


def make_tarball(files: dict[str, str], top: str = "acme-shop-abc123") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        dir_info = tarfile.TarInfo(top)
        dir_info.type = tarfile.DIRTYPE
        tar.addfile(dir_info)
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_client_reads_and_retries(tmp_path: Path) -> None:
    gh = FakeGitHub(make_tarball({"app/db.py": "x = 1\n", "README.md": "hi"}))
    sleeps: list[float] = []
    client = gh.client(sleeps)
    gh.fail_next = [502, 403]  # 5xx then secondary rate limit
    assert client.pull("acme/shop", 7)["number"] == 7
    assert len(sleeps) == 2
    assert client.pull_diff("acme/shop", 7) == DIFF
    client.download_tree("acme/shop", "h" * 40, tmp_path)
    assert (tmp_path / "app" / "db.py").read_text() == "x = 1\n"
    req = gh.requests[-1]
    assert req.headers["authorization"] == "Bearer tok"
    assert req.headers["x-github-api-version"] == "2022-11-28"
    with pytest.raises(GitHubError, match="404"):
        client._request("GET", "/nope", "acme/shop")


def test_tarball_path_traversal_is_blocked(tmp_path: Path) -> None:
    evil = make_tarball({"../../escape.txt": "pwned"})
    gh = FakeGitHub(evil)
    with pytest.raises(tarfile.TarError):
        gh.client().download_tree("acme/shop", "x", tmp_path / "ws")
    assert not (tmp_path / "escape.txt").exists()


def test_client_gives_up_on_network_errors() -> None:
    def boom(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = GitHubClient(
        StaticToken("t"), transport=httpx.MockTransport(boom), sleep=lambda _s: None, max_retries=1
    )
    with pytest.raises(GitHubError, match="unreachable"):
        client.pull("acme/shop", 1)


def test_app_auth_requests_least_privilege_tokens() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/app/installations/5/access_tokens":
            return httpx.Response(201, json={"token": f"ghs_{len(seen)}"})
        return httpx.Response(500)

    clock = [1_700_000_000.0]
    auth = GitHubAppAuth(
        "123", pem, 5, transport=httpx.MockTransport(handler), clock=lambda: clock[0]
    )
    assert auth.token("acme/shop") == "ghs_1"
    assert auth.token("acme/shop") == "ghs_1"  # cached
    body = json.loads(seen[0].content)
    assert body == {"permissions": MIN_PERMISSIONS, "repositories": ["shop"]}
    bearer = seen[0].headers["authorization"].removeprefix("Bearer ")
    claims = jwt.decode(
        bearer,
        key.public_key(),
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims["iss"] == "123"
    clock[0] += 4000  # past expiry -> refresh
    assert auth.token("acme/shop") == "ghs_2"
    bad = GitHubAppAuth("123", pem, 6, transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubError, match="installation token"):
        bad.token()


# ----------------------------------------------------------------- rendering & publishing


def _finding(**kw: Any) -> Finding:
    base: dict[str, Any] = {
        "category": Category.SECURITY,
        "severity": Severity.HIGH,
        "confidence": 0.93,
        "title": "SQL injection in search_products",
        "explanation": "term is interpolated",
        "file": "app/db.py",
        "line_start": 34,
        "line_end": 34,
        "source": FindingSource.VERIFIED,
        "origins": ["ai:claude", "ruff:S608"],
        "fingerprint": "fp1",
        "suggested_fix": "use params",
        "verification": VerificationResult(
            status=VerificationStatus.SUPPORTED, score=0.9, call_path=["GET /search", "search()"]
        ),
    }
    base.update(kw)
    return Finding(**base)


def _result(*findings: Finding) -> ReviewResult:
    return ReviewResult(
        changeset=ChangeSet(),
        findings=list(findings),
        summary=ReviewSummary(
            headline="HIGH risk: 1 high finding(s)",
            attention=["[HIGH] x"],
            what_changed=["1 file"],
            verified=["v"],
            uncertain=["u"],
        ),
        provider="claude",
        model="m",
    )


def test_rendered_comments_carry_markers_paths_and_links() -> None:
    body = finding_comment(_finding(), "https://sentinel/reviews/R-1")
    assert "SQL injection" in body and "<!-- sentinel:fp=fp1 -->" in body
    assert "`GET /search`" in body and "Suggested fix" in body
    assert "/findings/F-" in body
    summary = summary_comment(_result(_finding(title="a | b")), review_url="https://s/r")
    assert summary.startswith(SUMMARY_MARKER)
    assert "a \\| b" in summary and "[full review](https://s/r)" in summary
    assert "What remains uncertain" in summary


def test_commentable_lines() -> None:
    lines = commentable_lines(parse_unified_diff(DIFF))
    assert lines["app/db.py"] == {30, 31, 32, 33, 34}


def test_publisher_is_idempotent_across_pushes() -> None:
    gh = FakeGitHub()
    publisher = GitHubPublisher(gh.client(), review_url="https://sentinel/reviews/R-1")
    outside = _finding(title="Unrelated", line_start=5, line_end=5, fingerprint="fp2")
    result = _result(_finding(), outside)
    first = publisher.publish("acme/shop", 7, "h" * 40, result, parse_unified_diff(DIFF))
    assert first.posted and first.not_inline and not first.summary_updated
    assert len(gh.reviews) == 1 and gh.reviews[0]["comments"][0]["line"] == 34
    assert gh.reviews[0]["comments"][0]["side"] == "RIGHT"
    assert len(gh.issue_comments) == 1
    second = publisher.publish("acme/shop", 7, "h" * 40, result, parse_unified_diff(DIFF))
    assert second.summary_updated and second.duplicates and not second.posted
    assert len(gh.reviews) == 1  # nothing new to post
    assert len(gh.issue_comments) == 1  # summary edited in place
