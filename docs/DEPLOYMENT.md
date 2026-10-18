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

[`docker-compose.yml`](../docker-compose.yml) runs PostgreSQL, the API (with the web UI),
a review/publication worker and a dedicated Docker-capable fix worker. A one-off migration
job must succeed before application processes start. The sandbox image is built and checked
before the fix worker starts.

```bash
cp .env.example .env            # provider + key, GitHub App settings, SENTINEL_PUBLIC_URL
export POSTGRES_PASSWORD=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
# Linux Docker Engine: grant the validation worker the socket's numeric group.
export DOCKER_GID=$(stat -c %g /var/run/docker.sock)   # Docker Desktop commonly uses 0
docker compose up --build -d
docker compose exec api sentinel users create alice          # prints alice's API token once
```

- The API listens on `127.0.0.1:8000`; put a TLS-terminating reverse proxy (Caddy, nginx)
  in front of it for other people and for GitHub webhooks.
- The image runs in **token** auth mode: every API call needs `Authorization: Bearer
  <token>`; the web UI asks for the token once and keeps it in the browser.
- Scale review throughput with `docker compose up -d --scale worker=3`. Workers coordinate
  through the database queue (leases, generation fencing and `SKIP LOCKED`). Size the pool for
  database capacity; publication holds the job lock through its external requests.
- Scale fix validation independently with `--scale validation-worker=2`; ordinary workers
  claim only `review`/`publish` jobs, and validation workers claim only `fix` jobs.
- Local repositories must be available to all three application services at the same path.
  The `repositories` volume provides `/repos`; opt in with `SENTINEL_LOCAL_ROOTS=/repos`.
  Copy only repositories intended for those users into it, preserving UID/GID 10001 ownership,
  or replace that mount with a narrowly scoped directory. Token mode permits no local roots
  by default. A local Apply writes the shared repository volume, not an unrelated checkout.
- Logs are JSON lines (`SENTINEL_LOG_FORMAT=json`) with `review_id`, `stage` and
  `duration_ms` fields; metrics are at `GET /metrics` in Prometheus format. Metrics aggregate
  retained database history across API/worker processes, with bounded histogram storage. Deleting
  review history resets the corresponding totals; scrape cost scales with retained rows.
- Back up the `pgdata` volume like any PostgreSQL database. The cache directory can be
  deleted at any time.

### Fix validation and the sandbox

Fix analysis and tests run in throwaway containers started from the `sentinel-sandbox` image
([`Dockerfile.sandbox`](../Dockerfile.sandbox)). A worker running **inside** Docker Compose
uses `SENTINEL_SANDBOX_TRANSPORT=copy`: a bounded archive of confined regular files travels
over stdin to the installed trusted launcher. It extracts into a fresh 512 MiB tmpfs;
the daemon never receives a worker path to bind-mount. No files are copied back. Analysis,
baseline tests, patched tests and generated regression tests all use the same mechanism.
Each container has no network, a read-only root, resource limits, no capabilities, a
non-root UID and no worker credentials or Docker socket. Inputs are limited to 128 MiB
and 10,000 files; links, traversal and special archive entries are rejected.

**Daemon trust boundary:** only `validation-worker` has the Docker client and socket.
The API and review worker have neither. Access to a rootful Docker socket grants control
equivalent to root on that engine's host; non-root UID, a read-only socket mount or dropped
capabilities do not remove that authority. Run this stack on a dedicated Docker VM/host,
or deliberately use a rootless engine and set `SENTINEL_DOCKER_SOCKET` and `DOCKER_GID` for it.
Do not treat the validation worker itself as a sandbox for executing repository code.
See [Docker's daemon security guidance](https://docs.docker.com/engine/security/).
Rootless-daemon operation is supported by configuration but not part of the verified
Docker Desktop acceptance run.

The worker's `--require-sandbox` option refuses startup if its Docker CLI/image is
unavailable. Compose healthchecks also check schema compatibility and daemon/image access;
they are readiness checks, not a proof of worker progress. Rebuild the sandbox image after
updating Sentinel: it contains the trusted analyzers and scratch launcher.

Sandbox test logs retain their 20,000-character display limit and 40,000-byte capture
budget. The trusted structured-analysis call requests up to 1 MiB per displayed stream
with a shared 2 MiB capture budget, so an ordinary multi-file JSON report is not cut off
like a test log. Larger/truncated/invalid reports remain failed analysis, never successful
validation. An unverified patch can be inspected or downloaded; core/API/CLI/UI Apply
requires a validated outcome. Fix the missing checks before regenerating it.

Alternatively, run a fix worker directly on a host (or VM) that has Docker:

```bash
docker build -f Dockerfile.sandbox -t sentinel-sandbox .
SENTINEL_DATABASE_URL=postgresql://sentinel:<password>@<db-host>:5432/sentinel \
SENTINEL_PROVIDER=claude SENTINEL_CLAUDE_KEY=<key> \
sentinel worker --kind fix --require-sandbox
```

Because there is no network inside the sandbox, the image must already contain your
project's test dependencies; for real projects build an image `FROM sentinel-sandbox` that
installs them, and point `SENTINEL_SANDBOX_IMAGE` at it.

Repository `fix.setup_command` is rejected explicitly. Dependency installation belongs in the
trusted image build, outside generated-code execution. Python packages belong in the image's
interpreter environment; Node packages must be available on `NODE_PATH`. Host `node_modules` and
virtual environments are omitted from scratch workspaces, not linked into containers.

### Analyzer consistency and deployment checks

The API, review worker, validation worker and sandbox use Node 22 and the same locked
TypeScript/ESLint/parser tree in `tools/analyzers/package-lock.json`. Python analyzer versions
use `requirements.lock`. CI installs that same JS lock and sets both `PATH` and `NODE_PATH`.
Local CLI installs can use `npm ci --prefix tools/analyzers --omit=dev`, with those paths set
as shown in the README. Trusted installed parsers work without repository `node_modules`;
untrusted reviews never load a project parser. Missing TS parser coverage is incomplete.

Run `python scripts/verify_compose.py --output /tmp/sentinel-compose-evidence` from the
checkout for a full isolated rehearsal. It builds all production targets, uses a deterministic
HTTP provider fixture, checks auth/analyzers, queued review/fix generation, Docker regression
validation, explicit multi-file Apply and persistence after service recreation. It always
removes only its uniquely named test project's containers and volumes. It reads no operator
`.env` and sends no live provider/GitHub requests. The hosted CI deployment job runs it too.

## 3. GitHub pull-request reviews

Add the GitHub App settings to `.env` and follow [GITHUB_APP.md](GITHUB_APP.md).

## Configuration reference

All settings can be environment variables (see [`.env.example`](../.env.example)) or, for a
single user, `sentinel config set <key> <value>`. Per-repository review rules live in
`.sentinel.yml` at the repository root (`sentinel config init` writes a commented
template). The authoritative list is the `Settings` and `RepoConfig` models in
[`config.py`](../src/sentinel/core/configuration/config.py).

## Security checklist

- [ ] `SENTINEL_AUTH_MODE=token` for any externally reachable server, including loopback tunnels
      (`sentinel serve` refuses otherwise).
- [ ] TLS in front of the API; `SENTINEL_PUBLIC_URL` set to the HTTPS URL.
- [ ] Webhook secret set; App private key readable only by the Sentinel user.
- [ ] GitHub App permissions limited to those in [GITHUB_APP.md](GITHUB_APP.md).
- [ ] `SENTINEL_LOCAL_ROOTS` empty (or narrow) on a shared server, so the API cannot be asked
      to review arbitrary directories.
- [ ] Docker socket mounted only into the dedicated fix worker, on an engine whose
      host/user authority you intend that trusted worker to control.
- [ ] The process sandbox (`SENTINEL_ALLOW_PROCESS_SANDBOX`) left off on shared machines.
- [ ] Verified database backup, stopped application processes, and an explicit schema
      upgrade following [DATABASE_MIGRATIONS.md](DATABASE_MIGRATIONS.md).
