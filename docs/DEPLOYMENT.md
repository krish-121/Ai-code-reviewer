# Deployment

Three ways to run Sentinel, from simplest to most complete.

## 1. Just the CLI (one developer, no server)

```bash
pip install "sentinel-review[analyzers] @ git+<this repository>"   # or: pip install -e ".[analyzers]"
sentinel config set provider claude
sentinel config set claude_api_key <key>        # stored in ~/.config/sentinel/config.toml (0600)
cd your-repo && sentinel review --staged
```

History is kept in a local SQLite file; `sentinel serve` opens the web UI for it on
`http://127.0.0.1:8000` (loopback only, no login, one user).

## 2. Docker Compose (a team server)

[`docker-compose.yml`](../docker-compose.yml) runs PostgreSQL, the API (with the web UI)
and one worker.

```bash
cp .env.example .env            # provider + key, GitHub App settings, SENTINEL_PUBLIC_URL
export POSTGRES_PASSWORD=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
docker compose up --build -d
docker compose exec api sentinel users create alice          # prints alice's API token once
```

- The API listens on `127.0.0.1:8000`; put a TLS-terminating reverse proxy (Caddy, nginx)
  in front of it for other people and for GitHub webhooks.
- The image runs in **token** auth mode: every API call needs `Authorization: Bearer
  <token>`; the web UI asks for the token once and keeps it in the browser.
- Scale review throughput with `docker compose up -d --scale worker=3`. Workers coordinate
  through the database queue (leases + `SKIP LOCKED`), so any number is safe.
- Logs are JSON lines (`SENTINEL_LOG_FORMAT=json`) with `review_id`, `stage` and
  `duration_ms` fields; metrics are at `GET /metrics` in Prometheus format.
- Back up the `pgdata` volume like any PostgreSQL database. The cache directory can be
  deleted at any time.

### Fix validation and the sandbox

Fix *tests* run in throwaway containers started from the `sentinel-sandbox` image
([`Dockerfile.sandbox`](../Dockerfile.sandbox)). A worker running **inside** Docker Compose
cannot start those containers safely: it would need the host's Docker socket (which is
equivalent to root on the host) and a scratch directory shared with the host at the same
path. The compose file therefore does not mount the socket. In that setup, fixes are still
generated, applied to scratch copies, syntax-checked and re-analysed, but the test step is
skipped and the fix is reported as **unverified**.

To get fully validated fixes, run one worker directly on a host (or VM) that has Docker:

```bash
docker build -f Dockerfile.sandbox -t sentinel-sandbox .
SENTINEL_DATABASE_URL=postgresql://sentinel:<password>@<db-host>:5432/sentinel \
SENTINEL_PROVIDER=claude SENTINEL_CLAUDE_KEY=<key> \
sentinel worker
```

Because there is no network inside the sandbox, the image must already contain your
project's test dependencies; for real projects build an image `FROM sentinel-sandbox` that
installs them, and point `SENTINEL_SANDBOX_IMAGE` at it.

This trade-off is listed as *NEEDS REVIEW* in [PROGRESS.md](../PROGRESS.md).

## 3. GitHub pull-request reviews

Add the GitHub App settings to `.env` and follow [GITHUB_APP.md](GITHUB_APP.md).

## Configuration reference

All settings can be environment variables (see [`.env.example`](../.env.example)) or, for a
single user, `sentinel config set <key> <value>`. Per-repository review rules live in
`.sentinel.yml` at the repository root (`sentinel config init` writes a commented
template). The authoritative list is the `Settings` and `RepoConfig` models in
[`config.py`](../src/sentinel/core/configuration/config.py).

## Security checklist

- [ ] `SENTINEL_AUTH_MODE=token` for anything not bound to `127.0.0.1`
      (`sentinel serve` refuses otherwise).
- [ ] TLS in front of the API; `SENTINEL_PUBLIC_URL` set to the HTTPS URL.
- [ ] Webhook secret set; App private key readable only by the Sentinel user.
- [ ] GitHub App permissions limited to those in [GITHUB_APP.md](GITHUB_APP.md).
- [ ] `SENTINEL_LOCAL_ROOTS` empty (or narrow) on a shared server, so the API cannot be asked
      to review arbitrary directories.
- [ ] Docker socket **not** mounted into the API or worker containers.
- [ ] The process sandbox (`SENTINEL_ALLOW_PROCESS_SANDBOX`) left off on shared machines.
- [ ] A database migration plan before upgrading with real data (tables are created with
      `create_all()`; see PROGRESS.md).
