"""A public tunnel must reach only bounded GitHub notifications, never Sentinel's UI/API."""

import httpx
import pytest
from fastapi.testclient import TestClient
from scripts.github_webhook_gateway import MAX_BODY_BYTES, create_gateway


def test_gateway_forwards_exact_payload_and_signature_without_authorization() -> None:
    calls: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(202, json={"review_id": "R-test"})

    client = TestClient(
        create_gateway("http://127.0.0.1:8000", transport=httpx.MockTransport(upstream))
    )
    response = client.post(
        "/api/github/webhook",
        content=b'{"action":"opened"}',
        headers={
            "x-hub-signature-256": "test-signature",
            "x-github-event": "pull_request",
            "x-github-delivery": "test-delivery",
            "authorization": "Bearer private-local-token",
        },
    )
    assert response.status_code == 202 and response.json() == {"review_id": "R-test"}
    assert len(calls) == 1
    assert calls[0].content == b'{"action":"opened"}'
    assert calls[0].headers["x-hub-signature-256"] == "test-signature"
    assert calls[0].headers["x-github-delivery"] == "test-delivery"
    assert "authorization" not in calls[0].headers
    for path in ("/", "/api/health", "/api/reviews", "/docs", "/openapi.json"):
        assert client.get(path).status_code == 404
        assert client.post(path, json={}).status_code == 404
    assert len(calls) == 1


def test_gateway_rejects_oversized_and_chunked_requests_before_forwarding() -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid notification reached the private API")

    client = TestClient(
        create_gateway("http://127.0.0.1:8000", transport=httpx.MockTransport(unexpected))
    )
    assert (
        client.post("/api/github/webhook", content=b"x" * (MAX_BODY_BYTES + 1)).status_code == 413
    )
    assert (
        client.post(
            "/api/github/webhook", content=b"{}", headers={"transfer-encoding": "chunked"}
        ).status_code
        == 400
    )


@pytest.mark.parametrize(
    "target", ["https://example.com", "http://127.0.0.1/private", "http://user@127.0.0.1"]
)
def test_gateway_refuses_non_loopback_or_credentialed_targets(target: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        create_gateway(target)
