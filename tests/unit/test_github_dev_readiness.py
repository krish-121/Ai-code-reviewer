"""Public tunnel readiness must establish reachability without exposing private routes.

These offline HTTP tests reproduce the false-ready DNS failure and protect the
boundary between private GitHub authentication and unsigned public gateway probes.
"""

import httpx
import pytest

from sentinel.integrations.github.dev_readiness import public_gateway_ready

PUBLIC = "https://sentinel-example.trycloudflare.com"


def test_public_checks_do_not_share_client_credentials_or_follow_redirects() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        assert "proxy-authorization" not in request.headers
        assert not request.url.query
        if request.method == "GET":
            return httpx.Response(404)
        assert request.url.path == "/api/github/webhook" and request.content == b"{}"
        return httpx.Response(401)

    with httpx.Client(
        transport=httpx.MockTransport(handle),
        headers={"Authorization": "Bearer private-test-default", "Proxy-Authorization": "private"},
        cookies={"session": "private"},
        params={"api_key": "private"},
        auth=("private-user", "private-password"),
        follow_redirects=True,
    ) as client:
        assert public_gateway_ready(client, PUBLIC)
    assert [(request.method, request.url.path) for request in seen] == [
        ("GET", "/api/reviews"),
        ("POST", "/api/github/webhook"),
    ]


@pytest.mark.parametrize(
    ("private_status", "unsigned_status"),
    [(200, 401), (401, 401), (404, 200), (404, 502), (302, 401)],
)
def test_exposed_api_unprotected_hook_or_redirect_is_not_ready(
    private_status: int, unsigned_status: int
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        status = private_status if request.method == "GET" else unsigned_status
        return httpx.Response(status, headers={"Location": "https://unrelated.example/"})

    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        assert not public_gateway_ready(client, PUBLIC)


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
def test_unresolvable_or_timed_out_hostname_is_not_ready(error: type[httpx.RequestError]) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise error("public address unavailable", request=request)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert not public_gateway_ready(client, PUBLIC)


@pytest.mark.parametrize(
    "url",
    [
        "http://sentinel-example.trycloudflare.com",
        "https://127.0.0.1",
        "https://sentinel-example.trycloudflare.com/api",
        "https://sentinel-example.trycloudflare.com.evil.example",
        "https://key@sentinel-example.trycloudflare.com",
        "https://sentinel-example.trycloudflare.com?key=private",
    ],
)
def test_non_tunnel_origin_is_rejected_without_request(url: str) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        pytest.fail("An invalid origin must never be contacted")

    with (
        httpx.Client(transport=httpx.MockTransport(handle)) as client,
        pytest.raises(ValueError, match="Quick Tunnel origin"),
    ):
        public_gateway_ready(client, url)
