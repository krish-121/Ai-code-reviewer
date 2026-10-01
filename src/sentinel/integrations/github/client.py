"""Minimal GitHub REST client (plain httpx) and credentials.

Tokens: a GitHub App installation token is requested with only the permissions Sentinel
needs (``contents: read``, ``pull_requests: write``, ``issues: write``), scoped to the
single repository being reviewed. A personal access token also works for the CLI.
"""

from __future__ import annotations

import io
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
import jwt

from sentinel.core.domain.errors import SentinelError

API_VERSION = "2022-11-28"
MIN_PERMISSIONS = {"contents": "read", "pull_requests": "write", "issues": "write"}


class GitHubError(SentinelError):
    """A GitHub API call failed (``status`` is the HTTP status, if any)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class TokenProvider(Protocol):
    """Supplies a GitHub token for a repository."""

    def token(self, repo: str | None = None) -> str:
        """A token valid for ``repo``."""


@dataclass
class StaticToken:
    """A personal access token (used by ``sentinel review --pr``)."""

    value: str

    def token(self, repo: str | None = None) -> str:
        """The same token for every repository."""
        return self.value


class GitHubAppAuth:
    """Exchange an App JWT for short-lived, least-privilege installation tokens."""

    def __init__(
        self,
        app_id: str,
        private_key_pem: str,
        installation_id: int,
        *,
        api_url: str = "https://api.github.com",
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.app_id = app_id
        self.private_key = private_key_pem
        self.installation_id = installation_id
        self.clock = clock
        self._http = httpx.Client(base_url=api_url, transport=transport, timeout=20)
        self._cache: dict[str | None, tuple[str, float]] = {}

    def app_jwt(self) -> str:
        """A short-lived JWT signed with the App's private key (RS256)."""
        now = int(self.clock())
        payload = {"iat": now - 60, "exp": now + 540, "iss": self.app_id}
        token: str = jwt.encode(payload, self.private_key, algorithm="RS256")
        return token

    def token(self, repo: str | None = None) -> str:
        """An installation token with ``MIN_PERMISSIONS``, cached until near expiry."""
        cached = self._cache.get(repo)
        if cached and cached[1] - 60 > self.clock():
            return cached[0]
        body: dict[str, Any] = {"permissions": MIN_PERMISSIONS}
        if repo:
            body["repositories"] = [repo.split("/")[-1]]
        resp = self._http.post(
            f"/app/installations/{self.installation_id}/access_tokens",
            json=body,
            headers={
                "Authorization": f"Bearer {self.app_jwt()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        if resp.status_code >= 400:
            raise GitHubError(f"cannot get installation token: {resp.text[:200]}", resp.status_code)
        data = resp.json()
        token = str(data["token"])
        expires = self.clock() + 3000  # tokens live 1h; refresh well before
        self._cache[repo] = (token, expires)
        return token


class GitHubClient:
    """The few GitHub REST calls Sentinel needs, over ``httpx``."""

    def __init__(
        self,
        auth: TokenProvider,
        *,
        api_url: str = "https://api.github.com",
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 3,
    ) -> None:
        self.auth = auth
        self.sleep = sleep
        self.max_retries = max_retries
        self._http = httpx.Client(
            base_url=api_url, transport=transport, timeout=30, follow_redirects=True
        )

    # ------------------------------------------------------------------ transport
    def _request(
        self,
        method: str,
        path: str,
        repo: str | None = None,
        *,
        accept: str | None = None,
        **kw: Any,
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self.auth.token(repo)}",
            "Accept": accept or "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "sentinel-review",
        }
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._http.request(method, path, headers=headers, **kw)
            except httpx.HTTPError as exc:
                if attempt > self.max_retries:
                    raise GitHubError(f"GitHub unreachable: {exc}") from exc
                self.sleep(min(30, 2**attempt))
                continue
            limited = resp.status_code == 429 or (
                resp.status_code == 403 and "rate limit" in resp.text.lower()
            )
            if (resp.status_code >= 500 or limited) and attempt <= self.max_retries:
                wait = resp.headers.get("retry-after")
                self.sleep(float(wait) if wait and wait.isdigit() else min(30, 2**attempt))
                continue
            if resp.status_code >= 400:
                raise GitHubError(
                    f"GitHub {method} {path} failed: HTTP {resp.status_code} {resp.text[:200]}",
                    resp.status_code,
                )
            return resp

    def _paginate(self, path: str, repo: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            resp = self._request("GET", path, repo, params={"per_page": 100, "page": page})
            items = resp.json()
            out.extend(items)
            if len(items) < 100 or page >= 30:
                return out
            page += 1

    # ------------------------------------------------------------------ reads
    def pull(self, repo: str, number: int) -> dict[str, Any]:
        """Pull-request metadata."""
        data: dict[str, Any] = self._request("GET", f"/repos/{repo}/pulls/{number}", repo).json()
        return data

    def pull_diff(self, repo: str, number: int) -> str:
        """The pull request as a unified diff."""
        return self._request(
            "GET", f"/repos/{repo}/pulls/{number}", repo, accept="application/vnd.github.v3.diff"
        ).text

    def download_tree(self, repo: str, ref: str, dest: Path) -> None:
        """Download the repository at ``ref`` and extract it safely into ``dest``."""
        resp = self._request("GET", f"/repos/{repo}/tarball/{ref}", repo)
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:*") as tar:
            members = []
            for m in tar.getmembers():
                parts = m.name.split("/", 1)
                if len(parts) < 2 or not parts[1]:
                    continue  # the top-level "<owner>-<repo>-<sha>/" directory
                m.name = parts[1]
                members.append(m)
            tar.extractall(dest, members=members, filter="data")

    def review_comments(self, repo: str, number: int) -> list[dict[str, Any]]:
        """All inline review comments on the pull request."""
        return self._paginate(f"/repos/{repo}/pulls/{number}/comments", repo)

    def issue_comments(self, repo: str, number: int) -> list[dict[str, Any]]:
        """All conversation comments on the pull request."""
        return self._paginate(f"/repos/{repo}/issues/{number}/comments", repo)

    # ------------------------------------------------------------------ writes
    def create_issue_comment(self, repo: str, number: int, body: str) -> dict[str, Any]:
        """Post a conversation comment."""
        data: dict[str, Any] = self._request(
            "POST", f"/repos/{repo}/issues/{number}/comments", repo, json={"body": body}
        ).json()
        return data

    def update_issue_comment(self, repo: str, comment_id: int, body: str) -> dict[str, Any]:
        """Edit a conversation comment."""
        data: dict[str, Any] = self._request(
            "PATCH", f"/repos/{repo}/issues/comments/{comment_id}", repo, json={"body": body}
        ).json()
        return data

    def create_review(
        self,
        repo: str,
        number: int,
        *,
        commit_id: str,
        body: str,
        comments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Post a review with inline comments (event ``COMMENT``, never approve/block)."""
        payload = {"commit_id": commit_id, "body": body, "event": "COMMENT", "comments": comments}
        data: dict[str, Any] = self._request(
            "POST", f"/repos/{repo}/pulls/{number}/reviews", repo, json=payload
        ).json()
        return data
