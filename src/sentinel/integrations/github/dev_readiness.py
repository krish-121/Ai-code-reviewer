"""Probe a development tunnel before advertising it as a GitHub webhook address.

A connected tunnel process does not establish working public DNS or HTTP routing.
The local connector calls this check before updating the App URL. Probes carry no
credentials; the signed GitHub ping is still required after the address is saved.
"""

import re

import httpx

QUICK_TUNNEL_URL = re.compile(r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com")
WEBHOOK_PATH = "/api/github/webhook"


def public_gateway_ready(client: httpx.Client, public_url: str) -> bool:
    """Require a reachable, confined gateway; never follow redirects or send credentials.

    Only generated HTTPS Quick Tunnel origins are accepted. A hidden API must return
    404 and an unsigned webhook must return 401. Neither success alone proves a signed
    GitHub notification can arrive; the connector verifies that separately.
    """
    if QUICK_TUNNEL_URL.fullmatch(public_url) is None:
        raise ValueError("expected an HTTPS Quick Tunnel origin without a path")
    probes = [("GET", "/api/reviews", 404), ("POST", WEBHOOK_PATH, 401)]
    try:
        for method, path, expected in probes:
            # Build independently of client defaults (including cookies/query keys).
            request = httpx.Request(
                method,
                public_url + path,
                content=b"{}" if method == "POST" else None,
                headers={"Content-Type": "application/json"},
            )
            response = client.send(request, auth=None, follow_redirects=False)
            if response.status_code != expected:
                return False
    except httpx.HTTPError:
        return False
    return True
