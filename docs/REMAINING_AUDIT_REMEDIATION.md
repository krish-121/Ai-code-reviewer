# Remaining audit issues S10–S33: remediation and verification

**Subsequent SPEC work:** migrations and multi-file fixes are now implemented; see [current release readiness](RELEASE_READINESS.md). The counts and remaining-work notes below are the earlier audit checkpoint.

Verified **2026-10-18** against the local source at `D:\sentinel-final-v2\sentinel`. **All 24 issues S10–S33 are resolved.** Final S16 implementation and the latest complete check results are in [S16_REMEDIATION.md](S16_REMEDIATION.md). S01–S09 are documented separately in [BLOCKER_REMEDIATION.md](BLOCKER_REMEDIATION.md), and their regressions passed again. Changes remain local and uncommitted. “Resolved” means the audited defect is repaired and checked at the stated boundary; it does not imply complete SPEC coverage or live-service certification.

## Issue disposition

| Issue | Status | Implemented behavior and limits | Implementation and regression evidence |
|---|---|---|---|
| S10 | **Resolved** | Canonical local roots identify repositories. Fix generation and apply use the review request’s saved path, not the mutable repository row. | [src/sentinel/services/reviews.py:116](D:/sentinel-final-v2/sentinel/src/sentinel/services/reviews.py:116); [tests/unit/test_remaining_backend.py:37](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_backend.py:37) |
| S11 | **Resolved** | Check queued base/head before and after diff retrieval, download the saved head, publish the saved diff, and reject superseded revisions. Summaries label the reviewed commit; the final GitHub request race is an external API limitation. | [src/sentinel/services/reviews.py:255](D:/sentinel-final-v2/sentinel/src/sentinel/services/reviews.py:255); [tests/unit/test_remaining_backend.py:199](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_backend.py:199) |
| S12 | **Resolved** | Fence service transactions, heartbeat and completion by owner, attempt and unexpired lease. Bound crash retries and reject stale writes; hold the claim lock through publication. Already-running computation may finish, but cannot commit stale results. | [src/sentinel/infrastructure/queue/fencing.py:43](D:/sentinel-final-v2/sentinel/src/sentinel/infrastructure/queue/fencing.py:43); [tests/unit/test_remaining_backend.py:94](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_backend.py:94) |
| S13 | **Resolved** | Unique delivery/revision reservations coalesce concurrent webhook duplicates atomically. S11 prevents superseded publication. | [src/sentinel/services/reviews.py:152](D:/sentinel-final-v2/sentinel/src/sentinel/services/reviews.py:152); [tests/unit/test_remaining_backend.py:128](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_backend.py:128) |
| S14 | **Resolved** | Only markers authored by the authenticated account/App bot participate in deduplication or update selection. | [src/sentinel/integrations/github/client.py:136](D:/sentinel-final-v2/sentinel/src/sentinel/integrations/github/client.py:136); [tests/unit/test_remaining_backend.py:179](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_backend.py:179) |
| S15 | **Resolved** | Export the exact staged index or resolved target commit for all context; index diff and tree come from one write-tree snapshot. | [src/sentinel/services/workspaces.py:57](D:/sentinel-final-v2/sentinel/src/sentinel/services/workspaces.py:57); [tests/unit/test_remaining_backend.py:223](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_backend.py:223) |
| S16 | **Resolved** | Compare the complete eligible base/head source trees; retain new diagnostics in unchanged dependents, suppress confirmed baseline diagnostics, detect lost local imports and expose incomplete analysis. | [src/sentinel/core/review/baseline.py:92](D:/sentinel-final-v2/sentinel/src/sentinel/core/review/baseline.py:92); [S16 regression and verification report](S16_REMEDIATION.md) |
| S17 | **Resolved** | A synchronous helper or a changed test call path is neutral evidence, not decisive proof against blocking-call or missing-test claims. | [src/sentinel/core/verification/checks.py:274](D:/sentinel-final-v2/sentinel/src/sentinel/core/verification/checks.py:274); [tests/unit/test_verification.py:1](D:/sentinel-final-v2/sentinel/tests/unit/test_verification.py:1) |
| S18 | **Resolved** | A hashed source site and occurrence distinguish defects inside one symbol while tolerating inserted lines. The anchor retains no raw source text. | [src/sentinel/core/review/orchestrator.py:370](D:/sentinel-final-v2/sentinel/src/sentinel/core/review/orchestrator.py:370); [tests/unit/test_remaining_analysis_ai.py:60](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_analysis_ai.py:60) |
| S19 | **Resolved** | TLS detection requires recognized imported HTTP APIs and avoids shadowed receivers. Heuristic runtime patterns receive a qualified likely verdict. | [src/sentinel/analysis/static/python_rules.py:302](D:/sentinel-final-v2/sentinel/src/sentinel/analysis/static/python_rules.py:302); [tests/unit/test_remaining_analysis_ai.py:84](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_analysis_ai.py:84) |
| S20 | **Resolved** | Search/replace strings preserve indentation, multiline content and final newlines exactly (original repair in S07, additional regression here). | [src/sentinel/core/domain/ai.py:46](D:/sentinel-final-v2/sentinel/src/sentinel/core/domain/ai.py:46); [tests/unit/test_remaining_analysis_ai.py:98](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_analysis_ai.py:98) |
| S21 | **Resolved** | Require the findings field; malformed envelopes/schema responses get one corrective retry. Explicit provider safety refusals do not retry. | [src/sentinel/ai/providers/base.py:229](D:/sentinel-final-v2/sentinel/src/sentinel/ai/providers/base.py:229); [tests/unit/test_remaining_analysis_ai.py:120](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_analysis_ai.py:120) |
| S22 | **Resolved** | Scratch copies omit host dependency directories and links; trusted container dependencies supply Python and Node packages. Live tests exercised PyYAML, TypeScript, and full fix validation. | [src/sentinel/core/fixes/scratch.py:30](D:/sentinel-final-v2/sentinel/src/sentinel/core/fixes/scratch.py:30); [tests/integration/test_sandbox.py:140](D:/sentinel-final-v2/sentinel/tests/integration/test_sandbox.py:140) |
| S23 | **Resolved** | Fence metadata, paths, static hints, prior explanations, response echoes and validation feedback as untrusted data, including retry paths. | [src/sentinel/ai/prompts/__init__.py:124](D:/sentinel-final-v2/sentinel/src/sentinel/ai/prompts/__init__.py:124); [tests/unit/test_remaining_analysis_ai.py:127](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_analysis_ai.py:127) |
| S24 | **Resolved** | Poll active reviews independently of SSE, back off failed requests, and restart fix polling when the attempt ID changes. | [web/src/lib/api.ts:121](D:/sentinel-final-v2/sentinel/web/src/lib/api.ts:121); [web/tests/audit-regressions.test.ts:1](D:/sentinel-final-v2/sentinel/web/tests/audit-regressions.test.ts:1) |
| S25 | **Resolved** | Render retrieval/action errors with retries; show bounded call/test reachability and label missing graph evidence without asserting absent tests. | [web/src/lib/testReachability.ts:4](D:/sentinel-final-v2/sentinel/web/src/lib/testReachability.ts:4); [web/tests/audit-regressions.test.ts:1](D:/sentinel-final-v2/sentinel/web/tests/audit-regressions.test.ts:1) |
| S26 | **Resolved** | API metrics aggregate persisted worker results; histogram memory uses bounded buckets/count/sum. Retention-dependent totals and scrape cost are documented. | [src/sentinel/infrastructure/observability/durable.py:10](D:/sentinel-final-v2/sentinel/src/sentinel/infrastructure/observability/durable.py:10); [tests/unit/test_remaining_operations.py:28](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_operations.py:28) |
| S27 | **Resolved** | Drain both child pipes with one 40 KB capture limit and terminate the process group/container on overflow or timeout. | [src/sentinel/sandbox/output.py:16](D:/sentinel-final-v2/sentinel/src/sentinel/sandbox/output.py:16); [tests/unit/test_remaining_operations.py:60](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_operations.py:60) |
| S28 | **Resolved** | Qualify release, verification, redaction and worker guarantees. Public tunnels require token auth or a webhook-only proxy. Historical completion claims are labelled historical. | [docs/GITHUB_APP.md:43](D:/sentinel-final-v2/sentinel/docs/GITHUB_APP.md:43); [README.md:12](D:/sentinel-final-v2/sentinel/README.md:12) |
| S29 | **Resolved** | CLI apply uses FixService.apply, sharing the transaction that marks the finding fixed and the fix attempt applied. | [src/sentinel/apps/cli/fix_command.py:146](D:/sentinel-final-v2/sentinel/src/sentinel/apps/cli/fix_command.py:146); [tests/integration/test_cli.py:129](D:/sentinel-final-v2/sentinel/tests/integration/test_cli.py:129) |
| S30 | **Resolved** | Reject unsupported setup_command explicitly; propagate configured analyzer timeout into the container command and outer timeout. | [src/sentinel/core/configuration/config.py:81](D:/sentinel-final-v2/sentinel/src/sentinel/core/configuration/config.py:81); [tests/unit/test_remaining_operations.py:96](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_operations.py:96) |
| S31 | **Resolved** | Cache by semantic prompt content and model options, close owned AI providers at service boundaries, and validate/atomically replace escaped TOML configuration. | [src/sentinel/ai/providers/base.py:270](D:/sentinel-final-v2/sentinel/src/sentinel/ai/providers/base.py:270); [tests/unit/test_remaining_analysis_ai.py:168](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_analysis_ai.py:168) |
| S32 | **Resolved** | Pin verified Python constraints and npm lock; use them in CI/builds. Fix lint/format/test failures, add supported test-client transport and explicit test database cleanup. Add LICENSE and .dockerignore; all required local gates now pass. | [.github/workflows/ci.yml:42](D:/sentinel-final-v2/sentinel/.github/workflows/ci.yml:42); [tests/conftest.py:13](D:/sentinel-final-v2/sentinel/tests/conftest.py:13) |
| S33 | **Resolved** | Validate output/fail-on choices before work; suppress interactive PR progress for JSON/Markdown. | [src/sentinel/apps/cli/review_commands.py:46](D:/sentinel-final-v2/sentinel/src/sentinel/apps/cli/review_commands.py:46); [tests/unit/test_remaining_operations.py:131](D:/sentinel-final-v2/sentinel/tests/unit/test_remaining_operations.py:131) |

## Previous full verification — 2026-10-17

The latest full rerun is recorded in [S16_REMEDIATION.md](S16_REMEDIATION.md). The following counts are retained as historical evidence.

| Check | Result |
|---|---|
| Python 3.11 full suite, SQLite and PostgreSQL 16 | **360 passed, 4 skipped**, no warnings; 59.43 seconds; exit 0 |
| Python 3.14.4 full suite, SQLite and PostgreSQL 16 | **361 passed, 3 skipped**, no warnings; 136.54 seconds; exit 0 |
| Focused regression suite | **187 passed**, no warnings; exit 0 |
| Live Docker sandbox bodies | **3 passed**: isolation/network/read-only/timeout; full fix validation with an untrusted plugin; trusted Python/Node dependencies without host links |
| Branch-inclusive coverage | **93.54%** on Python 3.11; **93.61%** on Python 3.14; both exceed 80% |
| Core branch-inclusive coverage | **96.71%**, exceeds 90% on both environments |
| Ruff / formatting / strict mypy / whitespace | Pass; 169 Python files formatted; mypy checks 129 source files for the supported Linux target |
| Clean frontend install | `npm ci`: 73 packages installed from lock, exit 0 |
| Frontend tests | **20 passed**, 0 failed/skipped, including recovery, second fix attempt, graph reachability and visible request/action failures |
| Frontend types, Prettier, production bundle | All pass; generated UI copied into the Python package |
| Application and sandbox Dockerfiles | Both built successfully as `sentinel:sentinel-audit-20261017` and `sentinel-sandbox:sentinel-audit-20261017` |
| Installed application package | UI HTML/JS/CSS, TS extractor and LICENSE present; runs as UID 10001; build excludes `.git` and `.env`; dependency consistency passes |
| Application HTTP smoke check | `/api/health` 200, `/` 200, `/assets/app.js` 200, unauthenticated `/api/reviews` 401 |

The full suites skip the three Docker cases because nested Docker/WSL integration is unavailable. Each **actual test body** passed separately against Docker Desktop, using only a test harness to translate bind-mount paths. Python 3.11's fourth skip is the optional process network-namespace case; that case passed in WSL. No PostgreSQL tests were skipped. These are complementary runs, not a claim that one pytest invocation ran every case.

The original Python 3.11 verification image lacked Git, causing fixture errors; the corrected verification environment installs Git. A malformed SandboxResult in the new S30 test was corrected. An intermediate fingerprint implementation retained source text; it was replaced by a hash, and the existing secret-leak end-to-end regression now passes. Pool cleanup removes SQLite ResourceWarnings; pinned `httpx2` supplies Starlette's supported test transport and removes its deprecation warning. No assertion was disabled and no coverage threshold was reduced.

Docker BuildKit emits `SecretsUsedInArgOrEnv` for the variable **name** `SENTINEL_AUTH_MODE`. Its value is the non-secret mode `token`, not a credential. The warning is recorded, not hidden. Python runtime package versions and web packages are locked; OS packages, image tags, build-system bootstrap tools and global Node transitive dependencies are not content-addressed, so this is not a bit-for-bit reproducible build claim.

## Reproduce the gates

Use Linux/WSL with Python 3.11+, Node 22, Git and Docker. Set `SENTINEL_TEST_DATABASE_URL` to a **disposable** PostgreSQL database: tests drop its schema. The two verification suites used separate disposable databases, not user data.

```sh
python -m pip install -c requirements.lock -e '.[dev,postgres,analyzers]'
npm install -g typescript@5.9.3 eslint@9.39.5 @typescript-eslint/parser@8.71.2
docker build -f Dockerfile.sandbox -t sentinel-sandbox:latest .
ruff check src tests scripts
ruff format --check src tests scripts
mypy
pytest -q --cov=sentinel --cov-report=term --cov-fail-under=80 -ra
coverage report --include='*/sentinel/core/*' --fail-under=90
python -m pip check
cd web
npm ci --no-audit --no-fund
npm run lint
npm test
npm run build
cd ..
docker build -t sentinel .
git diff --check
```

The evidence bundle retains exact invoked commands, result JSON, coverage JSON, dependency versions, full logs and the Windows/WSL/Docker bridge. No live provider request, GitHub publication or hosted CI workflow was executed.

## Remaining work

2. **External validation remains unverified:** live Claude/Gemini/Ollama, GitHub App authorization and publication, hosted CI, and the complete Compose deployment. HTTP mocks and real local PostgreSQL/container runs cover their documented boundaries. A push during GitHub's final outbound request can still leave a comment explicitly labelled with the older reviewed commit; the API provides no atomic compare-and-comment operation.
3. **Broader SPEC/release gaps, outside these 24 defect closures:** database upgrade migrations; full rendered-browser workflows (new component tests use jsdom); full module/variable/data-flow graph coverage; generated multi-file fixes/new regression-test files; public demo deployment. The API image has TypeScript but omits optional ESLint/parser, whereas CI and the sandbox include them. Compose workers cannot validate fixes without a separately configured Docker-capable worker. See deployment documentation. These remain limitations, not claimed completed features.

Provider calls already in flight cannot be force-cancelled after a lost lease; fencing prevents subsequent stale commits. Inferred call graphs do not prove assertion coverage. Secret redaction and static heuristics remain detection mechanisms, not completeness guarantees.

Full verification evidence: [logs, manifests and harnesses](C:/Users/Krishna/Documents/Codex/2026-10-14/referenced-chatgpt-conversation-this-is-an/outputs/Sentinel-Remaining-Audit-Evidence-2026-10-17).
