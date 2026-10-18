# Release readiness and remaining SPEC work

**Current continuation:** [PROJECT_STATUS.md](PROJECT_STATUS.md) supersedes the snapshot
below for graph coverage, validated-only Apply, sandbox report budgets, browser smoke
acceptance and refreshed benchmarks. The latest local GitHub setup/gateway suite has **525 passing Python tests and 27 PostgreSQL skips**;
earlier frontend acceptance has **21 passing tests**. Gemini and DeepSeek fallback are now
live-tested; real GitHub App/PR acceptance also passed (see [GITHUB_LIVE_TEST.md](GITHUB_LIVE_TEST.md)). Ollama is optional. Older results below describe their dated checkpoint. See the current status for exact evidence and remaining
acceptance work. The following deployment batch is retained as a historical checkpoint.

Verified **2026-10-18**. The Docker-capable validation worker, runtime analyzer consistency,
database migrations and bounded multi-file generated fixes are implemented and regression-tested.
The original 33 audited defects (including the 24 follow-up issues S10–S33) remain closed within
their documented scope. Full production/SPEC acceptance is still incomplete. Changes are local
and uncommitted; no user database or repository was migrated or modified by the acceptance tests.

## How much work is left?

After the preceding migration/multi-file batch, the planning estimate was roughly **20%** of
release-readiness effort remaining (15–25%). This deployment batch brings the estimate to
roughly **10–20%, centred on 15%**. Most remaining effort is live integration, quality, browser,
operations and performance validation; graph representation still has implementation gaps.

These are judgment-based effort estimates, not a measured completion score or test-coverage
percentage. They exclude compiler-grade V2 analysis. Real acceptance work may uncover additional
defects and change the estimate. No automated-check failures remain in the verified snapshot.

## What is fixed

- **Docker-capable validation worker:** Compose has separate review/publication and fix-only
  workers. Only the fix worker receives the Docker client/socket. Job-kind routing is tested
  on SQLite and PostgreSQL. Its required-sandbox startup check refuses a missing Docker image
  or daemon; Compose healthchecks verify schema compatibility and daemon/image availability.
- **Scratch transfer:** bounded regular files/directories travel over stdin to an installed
  isolated-mode launcher and a private container tmpfs. Worker/daemon paths need not match.
  Empty directories and file contents survive; secrets/dependencies are omitted, and traversal,
  symlinks, hard links, special entries and byte/entry overflow are rejected. Generated changes
  never return to the worker filesystem. Network/root-filesystem/resource restrictions remain.
- **Analyzer parity:** API, both workers, sandbox and CI use one npm lock: Node 22,
  TypeScript **5.9.3**, ESLint **10.13.0**, parser **8.71.2**. Python tools use `requirements.lock`.
  The installed trusted parser now works for local reviews without project dependencies.
  Missing TypeScript parser coverage is incomplete even when JavaScript linting succeeds.
  The old ESLint 9 pin was replaced after npm reported its unsupported status; see the
  [official support policy](https://eslint.org/version-support/).
- **Compose integration:** ordered PostgreSQL/schema/application startup, sandbox-image build,
  shared repository paths, healthchecks, independent worker scaling and restart persistence.
  An unset database password is rejected instead of falling back to `change-me`.
- **Earlier batch remains verified:** packaged Alembic history and explicit legacy adoption,
  migration rollback/data preservation, coordinated existing-file edits plus an advertised
  new regression test, before/after diagnostics and tests, guarded Apply and ordinary-error rollback.

This batch adds **21 pytest regression cases** and the reusable full-stack acceptance script
`scripts/verify_compose.py`. The previous batch added 37 cases. An old real-ESLint test assumed
the installed TypeScript parser was absent; it now controls that missing-parser case explicitly,
and a separate real TypeScript test verifies successful installed-parser analysis. No assertions
or coverage gates were disabled. The test-only verification image also needed writable ownership
for its coverage directory; the final non-root run succeeds without warnings.

## Final verification

| Check | Final result |
|---|---|
| Focused worker/transfer/parser/Docker suite | **29 passed**, no skips or warnings |
| Full Python 3.14.4 + Node 22 | **460 passed, zero skipped**, 64.39 seconds |
| Full Python 3.11.17 + Node 22 | **459 passed, 1 platform skip**, 80.91 seconds |
| PostgreSQL 16 | All backend variants ran, in separate disposable databases per suite |
| Actual Docker cases | **All five ran and passed inside each full suite** |
| Overall branch-inclusive coverage | **93.36%** on both Python versions; gate 80% |
| Core branch-inclusive coverage | **96.16%** on both versions; gate 90% |
| Ruff / formatting / strict mypy | Pass; **197** Python files formatted, **147** source files type-checked |
| Frontend | Clean locked install, **20 tests**, types/Prettier and production build pass |
| Full Compose | All services start; migration/image jobs exit 0; API and both workers become healthy |
| Real HTTP workflow | Auth rejection, UI/assets, all six analyzers, graph, SSE and metrics pass |
| Real queued fix | Two existing files plus a new regression test validate in Docker; Apply writes all three |
| Persistence | Review, applied-fix record and all three files survive full service recreation |
| Installed images | Three production targets have identical analyzer versions and matching source hashes; only fix-worker target has Docker CLI |
| Dependencies | Both Python dependency checks and locked JS installs pass |

The Python 3.11 skip is optional unprivileged process network namespaces inside its test
container; that check passed under WSL. No Docker or PostgreSQL case was skipped. The WSL test
Docker shim delegates CLI calls to Docker Desktop; it does not translate paths, replace test
bodies or mock Docker. Production source and pytest cases were unchanged after the final suites;
the final Compose harness was separately linted and exercised after its HTTP/config assertions
were completed. Documentation was finalized afterward.

The application, dedicated validation-worker and sandbox Docker targets all build. Installed
image checks verify trusted launcher/migrations/UI contents, source hashes and UID 10001.
Build logs retain normal root-pip notices and the existing BuildKit warning about the non-secret
`SENTINEL_AUTH_MODE=token` variable name; those are not failed checks. The deprecated ESLint 9
install warning is absent from the final locked install.

## Remaining gaps and unverified areas

| Area | Work still required |
|---|---|
| Live AI providers | Real Claude/Gemini/Ollama model compatibility, error envelopes, rate limits, cost and latency. Compose uses a deterministic Ollama HTTP fixture, not a real model. |
| Review/fix quality | Representative real-repository precision/recall, false-positive rates and fix-success evaluation; golden/adversarial tests do not establish these. |
| Live GitHub App | Private-repository installation permissions, real signed delivery/publication/updates and push-race acceptance. HTTP shapes are tested locally. |
| Actual browser | Login/token handling, navigation, SSE disconnect/reconnect, retries and Apply through a real browser; accessibility/responsiveness. HTTP serving and SSE completion are now verified. |
| Deployment variants | Rootless/remote Docker, TLS/reverse proxy/public webhook deployment, daemon outages and stronger VM isolation. Local Docker Desktop Compose startup/validation/recreation/persistence now pass. |
| Database operations | Backup/restore and upgrades on copies of deployment data; competing/mixed-version migration and multi-host rehearsals. Unknown custom legacy schemas need explicit conversion. Ordered multi-process Compose startup is verified. |
| Graph coverage | Module/variable representation and some data-flow relationships remain partial. Compiler-grade tracing and complete dynamic behavior remain outside V1. |
| Performance/load | Updated small/medium/large benchmarks, whole-tree/deletion/fix scans, sustained concurrency, worker disruption, database growth and metrics scrape costs. Earlier benchmark numbers are historical. |
| Hosted CI and public release | New deployment CI job is configured and its command passes locally; hosted workflow execution, public deployment and demo repository are unverified. |

## Supported boundaries

The trusted validation worker controls its Docker daemon. A rootful socket grants host-level
authority even with a non-root worker UID and dropped capabilities. The API, review worker and
generated containers receive no socket. Use a dedicated engine/VM; rootless operation requires
its own acceptance run. [Docker's security guidance](https://docs.docker.com/engine/security/)
explains this daemon boundary. Healthchecks establish readiness, not forward job progress.

Scratch transfer caps uncompressed content at 128 MiB and 10,000 entries. Local fix confinement
requires POSIX/WSL. Project test dependencies belong in the trusted image; generated code cannot
install packages over the network. Static analysis cannot prove arbitrary runtime behavior;
budgets/missing tools remain explicit incomplete results. GitHub lacks an atomic revision-check
and comment operation; an already-running provider request cannot be force-cancelled on lease loss.

Generated fixes may edit supplied existing files and create advertised regression-test slots.
Arbitrary new source modules/directories and deletion edits are unsupported. New Python tests
must fail before/pass after; other frameworks need a compatible configured regression command.
Apply has ordinary-error rollback, not crash/power-loss atomicity. A failed database commit after
filesystem writes may need reconciliation. Backups/version control remain necessary.

## Implementation evidence

| Change | Current source |
|---|---|
| Worker and sandbox Compose wiring | [docker-compose.yml:97](D:/sentinel-final-v2/sentinel/docker-compose.yml:97) |
| Docker-only worker image | [Dockerfile:58](D:/sentinel-final-v2/sentinel/Dockerfile:58) |
| Job-kind routing | [src/sentinel/apps/worker/main.py:59](D:/sentinel-final-v2/sentinel/src/sentinel/apps/worker/main.py:59) |
| Required-sandbox startup | [src/sentinel/apps/cli/server_commands.py:67](D:/sentinel-final-v2/sentinel/src/sentinel/apps/cli/server_commands.py:67) |
| Scratch packing/extraction | [src/sentinel/sandbox/workspace.py:29](D:/sentinel-final-v2/sentinel/src/sentinel/sandbox/workspace.py:29) |
| Installed scratch launcher | [src/sentinel/sandbox/launch.py:18](D:/sentinel-final-v2/sentinel/src/sentinel/sandbox/launch.py:18) |
| Trusted parser fallback | [src/sentinel/analysis/static/js_tools.py:100](D:/sentinel-final-v2/sentinel/src/sentinel/analysis/static/js_tools.py:100) |
| Full-stack acceptance | [scripts/verify_compose.py:164](D:/sentinel-final-v2/sentinel/scripts/verify_compose.py:164) |
| Routing/health regressions | [tests/unit/test_validation_worker.py:22](D:/sentinel-final-v2/sentinel/tests/unit/test_validation_worker.py:22) |
| Transfer regressions | [tests/unit/test_sandbox_transfer.py:28](D:/sentinel-final-v2/sentinel/tests/unit/test_sandbox_transfer.py:28) |
| Installed-parser regressions | [tests/unit/test_runtime_analyzers.py:18](D:/sentinel-final-v2/sentinel/tests/unit/test_runtime_analyzers.py:18) |

## Operator guides and evidence

[Deployment](DEPLOYMENT.md), [Database upgrades](DATABASE_MIGRATIONS.md),
[Multi-file fixes](MULTI_FILE_FIXES.md). The dated original audit/S16 reports are historical
checkpoints; this report supersedes their statements that migrations, multi-file edits,
Compose Docker validation and delivered analyzer parity are missing.

Final [logs, commands, dependency versions, image IDs, coverage and source hashes](C:/Users/Krishna/Documents/Codex/2026-10-14/referenced-chatgpt-conversation-this-is-an/outputs/Sentinel-Deployment-Evidence-2026-10-18).
