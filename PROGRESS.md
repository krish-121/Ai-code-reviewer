# Sentinel — build progress

Living log of what is built, what was decided, and what still needs a human eye.
Spec: [`docs/SPEC.md`](docs/SPEC.md) (originally `project (1).md`) (sections referenced as §N). Last updated: 2026-10-19.

## Fresh public download accepted — 20 October 2026

- Rechecked implementation `a435e0c`: all three GitHub jobs passed in
  [39299740562](https://github.com/krish-121/Ai-code-reviewer/actions/runs/39299740562).
  Logs confirm 678 Python tests passed, one skipped; 27 frontend tests and full
  Docker/Compose acceptance passed. No code failure or weakened gate.
- The actual public clone/new Python environment prepared a completed replay review
  and seven-check validated proposal while preserving source before Apply. Restarting
  the demo retained them. The browser exposed the rejected safe-SQL warning, generated
  a distinct fix via the worker, validated and applied it; six final-tree tests passed
  in Docker. Reload kept applied/fixed state; outside-sample review was refused.
- Docker Desktop had stopped after interruption. Restarted the existing engine;
  no new application-code defect was found. Added the restart instruction and exact
  fresh-download evidence to the walkthrough. Saved provider/key setup stays separate.
- See [PUBLIC_DEMO_VERIFICATION.md](docs/PUBLIC_DEMO_VERIFICATION.md). The replies are
  explicitly scripted; this closes public-demo acceptance, not general model accuracy
  or the separate production/recovery/accessibility/load acceptance work.

## Public runnable demo — 19 October 2026

The [public demo guide](docs/PUBLIC_DEMO.md) now gives a single-checkout quickstart,
plain-language explanations, browser tour, screenshots, stop/reopen/fresh-path
instructions and an optional live-provider path. Sample templates stay in the public
main repository; the private integration repository is unchanged.

- Full sample review completed with real analysis/graph/verification and explicitly
  scripted model replies. It surfaced bug/security/performance/test findings and
  rejected three false claims. Scripted tokens are not reported as real API usage.
- The SQL proposal adds four regression cases. All seven normal Docker gates passed,
  sources stayed unchanged until explicit browser Apply, and the actual applied
  sample passes six tests. No generated/sample code is executed on the host.
- Shared demo wiring uses fresh Settings without saved/environment AI keys, its own
  database/cache, one allowed sample root, copy transport and a loopback-only server.
  Existing data and unrelated databases are refused. The ordinary queue and Apply
  services remain in use; no fake production vendor or weakened validation is added.
- Four regression tests exercise isolation, non-overwrite, the actual seed entrypoint
  plus normal API Apply and final Docker tests, and the unmarked-database guard.
  The Docker acceptance runs in hosted CI; demo scripts also get strict typing.
- Gemini 3.8 remains the owner's default; no Ollama, paid service, GitHub App change,
  Smee relay, private data publication or additional public repository is required.
- Public-demo presentation and repeatability are covered by the runnable guide and
  regression checks. Retain distributed live-profile, recovery, accessibility, load
  and broader model-quality work as separate operational acceptance. Decision 35.

Final local checks: **652 Python tests passed, 27 PostgreSQL variants skipped**; the real Docker tests include the new public entrypoint/Apply acceptance. Overall coverage **93.65%**, core **97%**. Ruff lint/format, strict application/bridge/evaluation-helper typing and strict typing of the three demo scripts passed. The separate browser-applied sample passed all six tests in Docker. Hosted results and fresh public-clone rehearsal are checked separately for the published revision.

## Complete local browser acceptance — 19 October 2026

- Actual browser form → persisted queue → real AI review → generation → all seven
  Docker validation checks → explicit Apply passed in two disposable SQL examples.
- Gemini 3.5 Flash-Lite produced the successful Gemini review/fix, three final tests
  and independent quoting/injection checks. Saved Gemini 3.8 returned two real busy
  503s; a listed legacy 2.5 model returned account-specific 404. Retain those attempts.
- Controlled local Gemini 429 triggered production quota fallback to real free
  DeepSeek. Its fix used shared cooldown, added two tests and applied normally; four
  final tests plus independent checks passed. No DeepSeek answer was replayed.
- Source/new-test files stayed unchanged until browser Apply. Reload retained the
  saved validated proposal. Both attempts are applied/fixed with actual model metadata.
- Repaired failed-stage uncertainty, pending/unavailable/provider UI labels, missing
  fix-model display, stale rebuilt assets and overconfirmation of test-code coverage
  claims. Captured warning replay changed supported → uncertain without AI/history writes.
- Owner chose to keep saved Gemini 3.8. Normal CLI restored; no quota injection,
  widened saved roots, credential upload, public relay or Smee reconnection. Decisions 33–34.
- **648 Python tests passed, 27 PostgreSQL variants skipped**; all **36 Docker tests** ran. Overall/core coverage: **93.59% / 97%**. Ruff lint/format and strict application/bridge/helper typing passed. Frontend: **27 tests passed**, type/format checks and production build passed.
- See [BROWSER_LIVE_WORKFLOW.md](docs/BROWSER_LIVE_WORKFLOW.md). Current browser
  acceptance is local with the real bridge; distributed live Compose-profile and
  complete outage/accessibility/load acceptance remain separate operational checks.

## Hosted checks and completion assessment — 19 October 2026

- All three code-check jobs in `39286099864` for `d2cd45c` report success. Retrieved
  completed logs: **673 Python tests passed, one optional skip**, **21 frontend tests**,
  full Docker/Compose acceptance, Ruff/format/strict types/coverage/build gates passed.
  PostgreSQL variants ran. No failing code check or required code repair was found.
- GitHub's active Actions/Pages/Webhooks incident delayed status visibility. Initial
  polls showed queued jobs without assigned runners. Keep this chronology separate
  from the final successful job results and from subsequent documentation-only runs.
- Replaced outdated release estimates and already-closed integration gaps with current
  evidence and observable completion criteria. This continuation changes documentation
  only. Checked 191 source-document links and exported working GitHub source links.
- Remaining V1 demonstration acceptance: current bridge-enabled browser workflow and
  a repeatable recruiter-facing demo. Public hosting/recovery/load and optional models
  are separate. Smee remains disconnected; no temporary permissions were restored.
- See [RELEASE_READINESS.md](docs/RELEASE_READINESS.md) and the walkthrough.

## GitHub notification recovery — 19 October 2026

- Cloudflare generated names failed public and authoritative DNS despite a connected
  tunnel process. Added credential-free public gateway readiness checks before the
  computer-specific connector updates the App URL. Signed GitHub ping remains required.
- With explicit temporary data-sharing consent, tested official Smee client 5.0.0 in
  a restricted container without project mounts or saved credentials. A real signed
  ping reached Sentinel. Real PR #2 produced one completed Gemini review, a supported
  SQL-injection finding, one summary and one inline comment on the exact head revision.
- PR remains open/unmerged; no fix generation or Apply was performed in this test.
- Cleanup verified: GitHub no longer points to Smee, prior inactive webhook setting
  restored, temporary container/image/gateway removed, channel/restoration records
  deleted. Existing test-only App installation and AI keys preserved. New automatic
  reviews are disconnected by request. External data erasure is not claimed.
- Required local checks: **647 passed, 27 PostgreSQL skips**, all **36 Docker tests**;
  **93.55% overall / 97% core** coverage, Ruff lint/format and application (155 files),
  bridge and helper typing passed. Added 14 offline readiness tests. No frontend change.
- See [GITHUB_CONNECTION_RECOVERY.md](docs/GITHUB_CONNECTION_RECOVERY.md) for the
  beginner explanation, evidence boundaries, cleanup and remaining work. Decision 32.

## Pricing contract investigation — 19 October 2026

- Traced both original failed fixes to downstream compensation encouraged by the
  review's suggestion and tests checking only callers; the retry already had history.
- Improved root-cause localization and producer/consumer contract instructions.
  Label suggestions as unverified; no new edit permissions or relaxed Apply checks.
- Fresh free DeepSeek review found the pricing division; correct Decimal companion
  stayed clear. Fresh root fix + three regressions passed all seven normal gates,
  independent tests and normal Apply. Actual applied history is applied/fixed.
- Original downstream finding also generated a correct helper repair, independently
  passing, but stayed unverified and actual Apply refused it without writes. Added
  clear rerun-review guidance for this case and retained conservative attribution.
- Captured old/new patch pair has two offline Docker regressions: with the same
  stronger tests, old compensation fails and root repair validates. Original corpus
  truth/hidden tests and earlier experiment results are unchanged. Decision 31.
- Actual applied tree also passed 63 supported integer amount/quantity/shipping
  scenarios plus mixed/empty carts; these extra checks were authored after generation.
- Required local checks: **633 passed, 27 PostgreSQL skips**; all **36 Docker tests** executed. Overall/core coverage: **93.55% / 97%**. Ruff lint/format, application typing (154 source files), strict bridge typing (3 files) and the strict case-preparation helper check passed. The normal sandbox image was rebuilt. No frontend source changed.
- Full explanation: [PRICING_FIX_INVESTIGATION.md](docs/PRICING_FIX_INVESTIGATION.md).

## Cross-file quality evaluation — 19 October 2026

- Added nine invented six-module applications with three staged source changes each:
  six bugs and three correct changes across Python/JavaScript/TypeScript. Every safe
  base passes separate checks; buggy heads pass old tests and fail withheld checks.
- Initial live round: all six planted bugs detected, one false alarm among three
  clean changes. Gemini's initial HTTP 503 was excluded from quality counts; evaluation
  explicitly selected already-configured free DeepSeek, without changing saved settings.
- Added bounded named imported class/data context and a generic concrete-counterexample
  prompt rule. Preserved the original false alarm and repeated live reviews.
- Reproduced and repaired omitted-target promotion: a helper-only patch must not count
  an absent target entry as changed source. Missing/no-op targets remain unverified.
- Repeat reviews: all six bug cases found, three clean controls clear; seven findings
  include two related organization-boundary warnings. Added neutral opaque-property
  verification and replayed captured findings against original source with no AI calls.
- First fixes: four validated/two unverified; five met the held-out contract. Added
  filtered, bounded original-review context and explicit regression guidance. Two
  missing-test follow-ups then validated and applied; Python still missed a pricing
  helper contract despite passing normal gates. Both failed proposals were independently
  rejected, not applied, and retained. Final actual-tree checks: five applied/fixed
  cases pass ordinary/held-out Docker tests; one contract miss remains. No oracle
  test text or output was generation feedback. See design decisions 26–29.
- Final privacy inspection repaired protected/ignored old paths on renames and
  propagation of excluded review paths into fix context. Public renames still work;
  saved config is unchanged. No example source contained actual credentials. Decision 30.
- Required local checks: **631 passed, 27 PostgreSQL skips**, all 34 Docker tests;
  **93.51% overall / 97% core** coverage, lint/format/application/bridge/helper typing passed.
- See [MULTIFILE_QUALITY_EVALUATION.md](docs/MULTIFILE_QUALITY_EVALUATION.md) for final
  model, independent Apply and automated verification results and their exact scope.

## Controlled multilingual quality evaluation - 19 October 2026

- Added 15 invented Python/JS/TS cases, a safe preparation helper and offline Docker
  contract tests. Answer files stay outside model context; existing destinations are
  refused, shell newlines normalized, and Git content is explicitly staged/checked.
- Final neutral-name round: 9/9 known bugs detected, 6/6 clean changes without warnings;
  all actual free DeepSeek responses. Initial diagnostic round used 13 Gemini / 2 DeepSeek
  with natural quota fallback. One empty snapshot was excluded, restaged and rerun.
- Original fix outcomes: 3 validated / 5 unverified / 1 failed. Nine final proposals
  passed independent checks. Repaired Node TAP handling, including test-callback errors
  versus failed file loading, and test-backed resolution for changed targets with a new
  reproducing regression and all other complete gates. Revalidated six captured proposals
  without new AI calls; all nine normal Apply paths and final suites/held-out checks passed,
  with applied/fixed history. Failed static resolution and incomplete checks remain blocked.
- Added the existing mutable-default concept to AI normalization so duplicate Ruff/AI
  reports merge without broader thresholds. Empty reviews explicitly identify unassessed code.
- No generated/example code executed on the host; no paid service/model download or
  credential upload. Normal tests/CI use controlled providers and Docker, never live AI.
- Required local checks: **590 passed, 27 PostgreSQL skips**, all 25 Docker tests;
  overall coverage **93.42%**, core **96%**; lint, formatting and typing passed.
- See [QUALITY_EVALUATION.md](docs/QUALITY_EVALUATION.md), the walkthrough and design
  decision 25. This is small-corpus evidence; representative quality and production work remain.

## Real GitHub App acceptance - 18–19 October 2026

- Registered the personal App `Sentinel Review krish-121` and installed it on only the
  private invented test repository. Contents read, issues/PR write and required metadata
  read; repository-scoped short-lived tokens. Saved App secrets outside Git with 0600
  permissions; linked installation ownership to a non-admin Sentinel user.
- [Real PR #1](https://github.com/krish-121/sentinel-integration-demo/pull/1): GitHub's
  signed opened event returned 202; actual Gemini completed all eight review stages,
  supported the unsafe SQL finding with three analyzers, and published one bot summary
  and one valid inline comment. The owner opened the saved review in the served UI.
- Actual GitHub redelivery returned the same review ID without extra reviews/comments.
  A Docker-tested correction/new regression triggered a second real review and updated
  the same summary to no problems. Historical inline warning remains outdated; PR stays
  open/unmerged and the base branch is unchanged. Another user received 404 for protected
  review/detail/findings/files/graph/source data.
- Added a bounded webhook-only local gateway and focused HTTP tests. Private App settings
  can be saved through normal configuration; the webhook secret uses hidden input and
  masked output. Added preservation/permissions and secret-display regressions.
- Required checks: **525 passed, 27 PostgreSQL skips**, all seven real Docker cases;
  coverage **93.38% overall / 96% core**. Ruff lint/format and strict typing passed.
  No frontend code changed. Hosted PostgreSQL variants remain part of the CI workflow.
- Initial automatic setup ping/installation events arrived before API startup (502);
  their actual redeliveries succeeded (200). Actual PR deliveries returned 202. Quick
  tunnels require running local processes and a fresh URL after restart; this is not
  permanent hosting. Quota fallback remains enabled but was not triggered by these PRs.
- See [GITHUB_LIVE_TEST.md](docs/GITHUB_LIVE_TEST.md) for the beginner explanation,
  evidence, source trace and remaining production/quality/race acceptance boundaries.

## GitHub source publication checkpoint - 18 October 2026

- Final code run: [all three hosted CI jobs passed](https://github.com/krish-121/Ai-code-reviewer/actions/runs/39141482827) on `8eb6c44`.
  Python/PostgreSQL: 544 passed, 1 skipped; frontend: 21 tests plus type/format/build;
  Docker/Compose acceptance passed. These hosted tests use controlled AI/GitHub fixtures,
  not a live reviewing App. The real pull-request bot workflow is the next GitHub milestone.


- Source destination: [krish-121/Ai-code-reviewer](https://github.com/krish-121/Ai-code-reviewer).
  The existing CI workflow runs on main pushes. Actual GitHub App installation,
  signed live deliveries and automatic comments remain separate acceptance work.
- GitHub push protection caught an invented Stripe-shaped demo value in old commits.
  Replaced that fixture throughout a separate publication copy; kept all 27 original
  snapshots and their original signatures in a verified local backup. Cleaned commits
  preserve authors, dates, messages and graph structure; changed IDs cannot retain their
  original signatures. No push-protection bypass or force-push is used.
- Current demo and end-to-end assertion use the same shorter synthetic value. Sentinel
  must still identify and redact it. Private keys, actual provider settings, local
  databases, dependency installations and caches remain outside the upload.
- The first real hosted CI run passed Python/PostgreSQL and Docker/Compose checks.
  Its web formatting check exposed one unformatted test expression; corrected it
  without changing behavior. Frontend type/format checks, all 21 tests and the
  production build passed locally. Final hosted results are available in Actions.
- See [GITHUB_UPLOAD.md](docs/GITHUB_UPLOAD.md) for the distinction between source
  hosting and bot installation, history handling and the next acceptance steps.

## Normal sandbox and complete live fix workflow - 18 October 2026

- Built the current trusted `sentinel-sandbox:latest` image (about 706 MB) and saved
  Docker/copy transport for the existing WSL runtime. Added the missing writable
  `sandbox_transport` setting and a validation/preservation regression test.
- Used the installed main checkout and actual Gemini `gemini-3.8-flash` to review a
  fresh disposable SQL example. All eight review stages completed. The model generated
  a parameterized query and a new security test on its first generation attempt.
- All seven normal fix checks passed, including baseline tests and a new regression
  test that fails before and passes after. Normal `FixService.apply` wrote only the
  example's two proposed files. Three tests and an independent SQL-input probe passed
  afterward inside Docker; stored statuses became applied/fixed. No bypass or host
  execution of generated code was used. Gemini quota was not simulated in this run.
- Normal local API/UI and in-process worker startup passed using the saved setup and
  disposable database. The test server was stopped. A full deployed browser run with
  the new bridge remains separate.
- Beginner explanation and source trace: [LIVE_FIX_WORKFLOW.md](docs/LIVE_FIX_WORKFLOW.md).
  The walkthrough, setup guide and ordered remaining work now link this completed step.
- Required checks passed: 518 Python tests, 27 PostgreSQL skips, all seven real Docker
  cases; coverage 93.36% overall and 96% core. Ruff lint/format and strict typing passed.
  Initial incomplete-environment test runs and their resolution are documented in the
  live workflow report. No frontend code changed.

## Gemini quota fallback connected - 18 October 2026

- Implemented Gemini -> official OpenCode bridge -> free DeepSeek for explicit HTTP 429
  quota/rate-limit errors. GLM is excluded; the failed direct-HTTP candidate was replaced.
- Preserved the AIProvider boundary, existing verification, private keys, cache and Apply
  rules. Actual winner and fallback reason survive review persistence.
- The local Docker bridge receives no vendor credentials, repository mount or Docker
  socket. It has authentication, per-request cleanup, approval rejection, bounded input/
  output and a deadline. Review/API workers keep their existing no-daemon boundary.
- Real Gemini-first CLI review passed. Controlled Gemini 429 -> real hosted DeepSeek ->
  full eight-stage review/database run passed. Repeat reused cooldown and cached answer
  without further model calls. Live tool-permission diagnostic rejected its command.
- Python suite: 517 passed, 27 PostgreSQL skips; overall coverage 93%, core 96%. Strict
  typing/lint passed, including the standalone bridge. Optional Compose configuration
  validated; its full deployment is not claimed by this continuation.
- Setup and source tour: [FREE_AI_FALLBACK.md](docs/FREE_AI_FALLBACK.md) and
  [WALKTHROUGH.md section 6.1](docs/WALKTHROUGH.md#61-automatic-deepseek-fallback-when-gemini-reaches-its-limit).
  Evidence and remaining limits: [DEEPSEEK_FALLBACK_VERIFICATION.md](docs/DEEPSEEK_FALLBACK_VERIFICATION.md).

## Current continuation: graph/context, Apply and report integrity — 2026-10-18

See [PROJECT_STATUS.md](docs/PROJECT_STATUS.md) for the consolidated requirement map,
earlier fix history and ordered remaining work. [LOCAL_SETUP_AND_GITHUB.md](docs/LOCAL_SETUP_AND_GITHUB.md)
explains the offline → real model → GitHub sequence. Gemini, free DeepSeek fallback,
source hosting and the real test App are now configured. Ollama remains optional.

- Preserved modules/variables and lexical module/import reads/writes across Python/TS/JS;
  changed constants include unchanged consumers. Added file/handler endpoint identity,
  independent deterministic UI projections, a hard node budget and symbol cache version 4.
- Browser acceptance exposed unverified Apply and a 20 KB truncation of valid analyzer JSON.
  Apply now requires validation at every surface; machine-readable reports get a separate
  bounded budget. The demo includes TypeScript configuration and validates its Python fix.
- **35 additional pytest cases** and **1 additional web case**. Final Python 3.14:
  **495 passed, no skips**; Python 3.11: **494 passed, 1 optional namespace skip** (passes on
  3.14). All seven real Docker cases and PostgreSQL variants ran in both suites.
- Overall coverage **93.48% / 93.46%** (3.14/3.11); core **96.21%** on both. Ruff,
  formatting, strict mypy (149 source files), dependency checks, web **21 tests** and build pass.
- Final rebuilt Compose workflow passes review → multi-file fix → Docker validation →
  three-file Apply → service recreation/persistence. Browser smoke covers token/invalid-token
  recovery, local review creation, finding details, graph variable source and validated Apply.
  Providers in these runs are fixtures/replay, not real models.
- Refreshed small/medium/large staged-review benchmarks: medians **1.073 / 1.465 / 4.042 s**
  over three runs each, with all six analyzers and an instantaneous measuring provider.
  The large graph is capped at 2,000 source files; these are not deletion/fix/load measurements.
- Live model/GitHub acceptance, representative quality evaluation, complete browser/accessibility,
  deployment operations/load and hosted release remain. No claim of complete V1 acceptance.

## SPEC gaps: Compose validation and analyzer parity — 2026-10-18

Dedicated fix-only Docker worker, stdin/tmpfs scratch transfer and identical locked runtime
analyzers are implemented. Full Compose acceptance covers auth/UI/SSE/metrics, six analyzers,
queued multi-file fix validation/Apply and persistence after service recreation. No fallback
database password remains. See [RELEASE_READINESS.md](docs/RELEASE_READINESS.md).

- Added 21 pytest regression cases and a reusable Compose acceptance harness/CI job.
- Final Python 3.14: **460 passed, no skips**; Python 3.11: **459 passed, 1 platform skip**.
  PostgreSQL and all five actual Docker cases ran in both suites. No pytest warnings.
- Focused **29 passed**; web **20 passed**; overall/core coverage **93.36% / 96.16%**.
  Lint, format, strict types, dependency checks, three production targets and installed
  image checks pass. ESLint 10.13.0 replaces the unsupported 9.x pin.
- Rough remaining release-readiness effort: **10–20%, centred on 15%**, judgment-based.
  Live providers/GitHub, actual-browser flows, production operations, quality/load and graph
  gaps remain explicit. Only disposable test data was changed; no real external requests.

## SPEC gaps: migrations and multi-file fixes — 2026-10-18

Database migrations and bounded multi-file fixes/new regression tests are implemented.
See [RELEASE_READINESS.md](docs/RELEASE_READINESS.md) for changes, evidence, remaining
unverified workflows and the rough **15–25%** release-readiness effort estimate.

- Added 37 regression cases. Focused **261 passed**; full Python 3.14 **435 passed/4 skips**;
  Python 3.11 **434 passed/5 skips**. No warnings; PostgreSQL variants all ran.
- All four Docker test bodies passed separately, including two edited files plus a new
  regression test, which fails before and passes after the patch. Web **20 passed**.
- Overall coverage **93.41%**, core **96.10%** (Python 3.14); both environments pass
  the 80%/90% gates. Lint/types/builds and installed-package/HTTP/schema checks pass.
- Existing databases require explicit upgrade/adoption. No user data was migrated here.
- Hosted services, browser/Compose acceptance, backup/restore, load and quality evaluation,
  analyzer parity and remaining graph/demo work are still explicit release gaps.

Earlier dated checkpoints below retain their original counts and limitations.

## S16 completion — 2026-10-18

**All 24 audit defects S10–S33 are resolved**, within the supported analysis boundaries.
[S16_REMEDIATION.md](docs/S16_REMEDIATION.md) records the implementation, source evidence,
regressions, exact final counts and remaining external/SPEC limits.

- Added 38 S16 regression cases. Focused suite: **225 passed**.
- Full Python 3.11 + Node 22: **398 passed, 4 environment skips**; Python 3.14 + Node 22:
  **399 passed, 3 Docker skips**. No warnings. PostgreSQL variants all ran.
- All three Docker test bodies passed separately in real containers. The optional process
  namespace case skipped in Python 3.11 passed in WSL.
- Coverage: **93.89% overall, 96.85% core** on Python 3.14; both Python environments
  exceed the 80%/90% gates. Ruff, formatting, strict types, dependency consistency, 20 web
  tests, clean web install, production bundle, both Docker builds and app smoke checks pass.
- Base/head scans include unchanged dependents; uncertainty and resource/tool limits remain
  explicit. Dynamic behavior and external/live release workflows are not certified.
- Changes remain local and uncommitted. The following sections are historical checkpoints.

## Remaining audit remediation — 2026-10-17

**23 of S10–S33 are resolved; S16 remains partial.** The complete issue-by-issue disposition,
source/test evidence and unresolved SPEC limits are in
[REMAINING_AUDIT_REMEDIATION.md](docs/REMAINING_AUDIT_REMEDIATION.md).

- Full Python 3.11 suite: **360 passed, 4 environment skips**, no warnings; 93.54% coverage.
- Full Python 3.14 suite: **361 passed, 3 Docker skips**, no warnings; 93.61% coverage.
- All three skipped Docker test bodies passed separately in real containers; the process
  namespace test skipped in Python 3.11 passed in WSL. PostgreSQL variants all ran.
- Core coverage **96.71%**; focused regressions **187 passed**; web **20 passed**.
- Clean dependency installs, lint, formatting, strict types, UI bundle, both Docker builds,
  installed package assets and HTTP/auth smoke checks pass. Test database leaks and the
  test-client deprecation are fixed. Source changes remain uncommitted.
- S16 still needs base/head diagnostic comparison and full dependent-code deletion analysis.
  Live service publication, hosted CI and full browser/Compose workflows remain unverified.

The following dated sections are historical evidence, not current acceptance results.

## Engineering audit remediation — 2026-10-16

The nine high-priority audit blockers S01–S09 are implemented and regression-tested.
See [the remediation report](docs/BLOCKER_REMEDIATION.md) for each change, its evidence,
and the remaining limitations. The previous completion claims below describe the earlier
build and do not close the audit's remaining S10–S33 findings.

- Added 53 regression cases. Focused suite: **141 passed**. Full Linux suite: **305 passed,
  12 skipped**, 93.52% overall coverage; core coverage **96.59%** (gate 90%).
- Both Docker test bodies passed separately in real Docker Desktop containers, including
  full fix validation with an untrusted repository plugin present. The full suite's two
  Docker skips reflect disabled WSL integration; ten PostgreSQL variants remain untested.
- Ruff, formatting, strict mypy (123 source files), whitespace checks and sandbox image
  build pass. SQLite resource warnings and a test-client deprecation remain.
- Fix analysis and tests now require Docker. No process fallback executes generated code.
  Rebuild the sandbox image after upgrading; install project test dependencies in it.
- Filesystem confinement rejects symlinks/hard links and requires POSIX/WSL facilities.
  Demo creation refuses existing destinations. Incomplete checks never yield `validated`.
- Assumption: conservative same-rule/location checks are preferable to falsely confirming
  a fix; ambiguous or incomplete validation remains unverified.

## Steps

Historical implementation milestones below are not release acceptance. The current audit
disposition and final check results are tracked in
[Remaining audit remediation](docs/REMAINING_AUDIT_REMEDIATION.md). Deployment limitations
and external-service verification remain explicit there.

| # | Step | Status |
|---|------|--------|
| 1 | Scaffolding, tooling, vendored dependencies | Done |
| 2 | Core review engine (diff, filtering, AST, code graph, context, static analysis, AI providers, verification, findings) | Done |
| 3 | Persistence, job queue, services, API, worker, GitHub integration | Done |
| 4 | Fix engine, sandbox, CLI, demo repository | Done |
| 5 | Test suite (unit, integration, end-to-end, golden) | Done |
| 6 | Web UI | Done |
| 7 | Benchmarks, docs, CI, Docker files | Done |
| 8 | Final check against the Definition of Done (§54), packaging | Done (see below) |
| — | Readability audit of steps 1–6 (owner's code-quality standard) | Done (see below) |

Step 3/4 note: the API, worker and GitHub integration were half-done when an earlier
session hit its usage limit. They were finished in the following session and are covered by
`tests/integration/test_api.py`, `tests/unit/test_github.py` and
`tests/e2e/test_github_flow.py` (webhook → queue → worker → review → verification →
GitHub comments → re-run deduplication).

## Current verification state

- `pytest`: 264 tests. With `SENTINEL_TEST_DATABASE_URL` (PostgreSQL 16) and Docker running:
  all pass. Without them, the PostgreSQL variants and the Docker sandbox test skip (10).
- `mypy --strict`: clean (118 source files). `ruff check` (now including complexity,
  naming and docstring rules) and `ruff format --check`: clean.
- Coverage: 93.9% overall, 97% for `sentinel/core` (gates: 80% / 90%).
- Frontend: `tsc --noEmit`, prettier, 13 `node --test` tests, esbuild production build: all pass.
- Demo: `scripts/seed_demo.py` reviews the demo repo (scripted AI replay), rejects all three
  planted wrong AI claims, and validates the SQL-injection fix in the Docker sandbox.

## Step 8: Definition of Done check (§54)

Re-run on 2026-10-02 with PostgreSQL 16 and Docker available. ✓ = met and checked here,
◐ = implemented but only verifiable live (see *Verified only with mocks*), ✗ = not met.

| Area | Item | State | Evidence |
|---|---|---|---|
| Functional | CLI review works | ✓ | `sentinel review --range main..feature/search-and-reports --no-ai` on the demo repo; `tests/integration/test_cli.py` |
| | GitHub PR review works | ◐ | webhook → worker → comments → re-run dedup in `tests/e2e/test_github_flow.py` against a faked GitHub API |
| | Web UI works | ✓ | browser-checked in local and token mode, no console errors; screenshots in `docs/screenshots/` |
| | AI providers work | ◐ | Claude, Gemini, Ollama adapters tested with `httpx.MockTransport` (bad JSON, rate limits, timeouts); never called live |
| | Static analysis works | ✓ | ruff, mypy, bandit (when installed), built-in rules and probes; `tests/unit/test_static_analysis.py` |
| | Context analysis works | ✓ | code graph + call paths + related tests; `tests/unit/test_graph.py`, `test_context_engine.py`, golden cases |
| | Findings are verified | ✓ | every finding carries checks; demo rejects 3 planted wrong AI claims |
| | Fixes can be generated | ✓ | demo fix `X-…` for the SQL injection; `tests/unit/test_fix_engine.py` |
| | Fixes are sandbox-tested | ✓ | demo fix validated with `isolation: docker`; `tests/integration/test_sandbox.py` |
| Quality | ≥80% overall coverage | ✓ | 93.9% |
| | ≥90% core coverage | ✓ | 97% |
| | mypy strict passes | ✓ | 118 files, no issues |
| | Ruff passes | ✓ | incl. C901 ≤ 10, pep8-naming, docstrings (google), bugbear, simplify |
| | Frontend checks pass | ✓ | typecheck, prettier, 13 tests, build. ESLint for `.ts/.tsx` needs `@typescript-eslint/parser` (not available offline) |
| | CI passes | ◐ | `.github/workflows/ci.yml` runs every gate above; each command passes locally, the workflow itself has not run on GitHub |
| Security | Secrets filtered | ✓ | `.env`/keys never read; redaction in diff, context and prompt; golden case `secrets` |
| | Repo content treated as untrusted | ✓ | nonce-fenced prompt, injection finding, untrusted workspace mode for PRs; golden case `prompt_injection` |
| | Generated code sandboxed | ✓ | Docker sandbox: no network, read-only root, limits, no capabilities; process sandbox opt-in only |
| | GitHub permissions minimized | ◐ | tokens requested with `MIN_PERMISSIONS` (contents read, PRs write, issues write); not tried against a real App |
| | Tenant/repository isolation tested | ✓ | `test_tenant_isolation` (store), `test_token_mode_isolates_tenants` (API), both on SQLite and PostgreSQL |
| Docs | README, ARCHITECTURE, DESIGN_DECISIONS, WALKTHROUGH, STUDY_GUIDE | ✓ | plus GITHUB_APP, DEPLOYMENT, BENCHMARKS |
| Demo | bug · security · performance · test gap · false positive rejected · fix generated · fix validated | ✓ | `python scripts/seed_demo.py`: 15 findings (SQL injection, auth order, N+1, O(n²), blocking async, missing await, swallowed exception, untested `search_products`, secrets…), 3 rejected claims, fix validated in Docker |

### Still missing or partial

1. **Live verification** of the AI providers, the GitHub App and the CI workflow — everything
   on the *Verified only with mocks* list. Nothing is known to be wrong; it has simply never
   met the real services.
2. **Docker images** (`Dockerfile`, `docker-compose.yml`) were written but not built here
   (no registry access). `Dockerfile.sandbox` was built and is used by the tests.
3. **Frontend stack** differs from the recommended Next.js/Tailwind/shadcn/Monaco (NEEDS
   REVIEW 1).
4. **OpenTelemetry tracing** (a SHOULD HAVE) is not implemented; observability is structured
   JSON logs plus Prometheus metrics at `/metrics`.
5. **Fix-validation report shape**: §22 shows type-check, lint and security as separate rows;
   Sentinel runs them as one *no new issues* check across mypy/ruff/bandit/built-in rules,
   whose detail names each tool. Splitting it is a display change in `core/fixes/validation.py`.
6. **Migrations**: tables are created with `create_all()` (NEEDS REVIEW 2).
7. **Quality-standard leftovers** (judgement calls): 13 Python files of 300–520 lines, 11
   functions of 41–46 lines (long docstrings or one flat sequence of steps), inline
   verification-check weights in `checks.py`. Details under *Readability audit*.

## Readability audit (owner's code-quality standard)

Behaviour-preserving cleanup of steps 1–6. Gates were green before and after every change
(250 tests, mypy strict, Ruff); nothing that passed before fails now.

- **Stricter Ruff.** Added `C90` (max complexity 10), `N` (naming) and `D` (Google-style
  docstrings for public code) on top of the existing `B`, `SIM`, `S`, `RUF`… rules. All
  violations were fixed, none disabled; the only configuration is `visit_*` names (required
  by `ast.NodeVisitor`) and no member docstrings in test files (test names describe behaviour).
- **Every module, public class and public function has a docstring** saying what it does,
  why, and where it sits in the flow.
- **Oversized functions split** (no function above ~45 lines, none above complexity 10). The
  biggest: `create_app` (302 lines) → `apps/api/` routers + `dependencies.py` +
  `serializers.py`; `ReviewOrchestrator.review` (240) → one method per stage plus
  `core/review/state.py` and `core/review/ai_request.py`; `parse_unified_diff` → a small
  state machine; the CLI (606 lines) → one module per command group, `main.py` lists them.
- **Oversized modules split along their natural seams**: graph builder vs. name resolution
  (`analysis/graph/resolution.py`); context engine vs. architecture subgraph; built-in rules
  → `python_patterns.py` / `python_rules.py` / `js_rules.py`; probes → `analysis/static/probes/`
  package; SQL recognition → `analysis/ast/python_sql.py`; TS regex fallback →
  `typescript_fallback.py`; fix engine → `outcome.py` / `validation.py` / `engine.py`.
- **One error pattern.** `core/domain/errors.py::SentinelError` is the base of every expected
  error (`GitError`, `ConfigError`, `ApplyError`, `AIError`, `GitHubError`…). The CLI
  prints them and exits; the API maps them to HTTP errors; the pipeline marks the stage
  failed. Broad `except Exception` remains only where a crash must be contained (pipeline
  stages, analyzer runs, worker loop) and is logged.
- **Magic values named**: job kinds (`jobs.REVIEW_JOB`…), tool statuses (`ToolStatus`),
  provider/HTTP limits, sandbox limits, probe weights, the `FROM_SETTINGS` sentinel.
- **Clearer names**: `Store.s` → `Store.session`, cryptic locals renamed; vague test names
  replaced by behaviour descriptions (e.g. `test_symbol_evidence` →
  `test_symbol_evidence_rejects_hallucinated_symbols`).
- **Frontend**: feature folders (`app/`, `pages/`, `review/`, `findings/`, `lib/`,
  `components/`, `styles/`); the 386-line findings view split into list, filters, detail and
  section components; the 2,358-line stylesheet split into 16 files by area.

Known gaps against the standard (judgement calls, not blockers):
- 13 Python files are still between 300 and 520 lines. Each is cohesive (e.g.
  `core/domain/models.py` is only data classes; `orchestrator.py` is one method per stage)
  and their functions are short (11 functions in the codebase are 41–46 lines, e.g.
  `scan_for_injection`, `Store.save_result`). Natural next splits if wanted: `models.py` →
  `changes.py` / `findings.py` / `review.py`; `store.py` → per-entity stores.
- Verification-check weights in `core/verification/checks.py` are inline keyword arguments
  (`weight=0.75`) rather than named constants; probes use named weights.

## Step 7 summary (benchmarks, docs, CI, Docker)

- **Docs**: README, `docs/ARCHITECTURE.md` (Mermaid: system, layers, pipeline, code graph,
  verification, fix validation, GitHub sequence, ER model, job states, security table),
  `DESIGN_DECISIONS.md` (19 decisions), `WALKTHROUGH.md` (one review traced with links to
  real files/functions + *How to change common things*: 14 recipes), `STUDY_GUIDE.md`
  (14 days, each with read/run/try/check-yourself), `GITHUB_APP.md`, `DEPLOYMENT.md`,
  `BENCHMARKS.md`.
- **Benchmarks**: `scripts/benchmark.py` generates small/medium/large repositories
  (1k / 10k / 58k LOC) and measures every stage, peak memory and prompt size; results in
  `docs/BENCHMARKS.md` (2.8 s / 3.2 s / 6.8 s without model latency).
- **Deployment**: `Dockerfile` (multi-stage: builds the UI, non-root user, token auth),
  `Dockerfile.sandbox`, `docker-compose.yml` (PostgreSQL + API + worker), `.env.example`.
- **CI**: `.github/workflows/ci.yml` — Ruff, Ruff format, mypy strict, pytest with coverage
  gates (80% overall, 90% core) against a PostgreSQL service with the sandbox image built,
  frontend typecheck/Prettier/tests/build, and both Docker image builds.
- **Observability**: one structured log line per stage and per review (`review_id`,
  `stage`, `duration_ms`, files, tokens …); new metric `sentinel_fix_checks_total` (test
  failure rate, fix success rate).
- **Fixes found while documenting** (behaviour changes, all tested):
  - The web UI could not be used in token mode: there was no way to enter a token, live
    progress used `EventSource` (which cannot send an `Authorization` header) and the patch
    download was a plain link. Added a sign-in form, a fetch-based SSE reader
    (`web/src/lib/sse.ts`, unit-tested) and a client-side patch download. Verified in a
    browser against a token-mode server.
  - `sentinel review --pr` queued a review job and a publish job, so a worker started later
    against the same database could have posted comments. CLI PR reviews are now created
    with `enqueue=False, publish=False`.
  - The summary said "Not run (not installed)" for tools that are installed but skipped
    (e.g. `tsc` without a `tsconfig.json`); it now gives each tool's reason.
  - Verification thresholds and confidence blending are named constants.

## Key design decisions

Full write-ups go in `docs/DESIGN_DECISIONS.md` (step 7). Short version:

- **Layering (§33–34).** `core/domain` is pure Pydantic and knows nothing about FastAPI,
  GitHub, SQL or vendors. Application code (`core/review`, `core/verification`,
  `core/fixes`, `services/`) depends on ports in `core/domain/ports.py`
  (`AIProvider`, `StaticAnalyzer`, `Cache`, `Sandbox`, `ProgressReporter`). Concrete adapters
  live in `ai/`, `analysis/`, `infrastructure/`, `integrations/`, `sandbox/`.
  `sentinel/bootstrap.py` is the single composition root. `tests/unit/test_infrastructure.py`
  enforces the import rules.
- **AI calls via httpx only (§32).** One provider class per vendor in
  `ai/providers/http_providers.py`; responses must validate against strict Pydantic
  schemas in `ai/schemas/`; one repair retry on invalid JSON.
- **Verification is deterministic (§14).** Each AI claim is checked against the diff, the
  code graph, static-analysis output and small probes (e.g. "is this SQL actually
  parameterised?"). Decisive contradictions reject a claim; rejected claims are stored but
  never merged with real findings.
- **Background jobs without Redis (§30, §32 "Redis only if actually required").** Jobs live in
  the database with leases, heartbeats and `SELECT … FOR UPDATE SKIP LOCKED` on PostgreSQL.
  Progress is streamed to the UI with Server-Sent Events that read stage rows.
- **Untrusted repository content (§40).** Sensitive files (`.env`, keys, credentials) are
  never sent to the model; secrets are redacted from everything else; prompt-injection
  patterns are flagged and the prompt frames repository text as data. Pull-request
  workspaces run in "untrusted" mode: no project-local tool binaries, mypy plugins or
  workspace TypeScript are executed.
- **Fixes never touch the host directly (§22–23).** The model proposes search/replace edits;
  they are applied to a scratch copy, parsed, re-analysed, and tested in a Docker container
  without network. Applying to the working tree requires a validated fix and a hash check
  that the file has not drifted.

## Assumptions (small decisions where the spec is silent)

- Default models: `claude-sonnet-5-5`, `gemini-2.5-flash`, `qwen2.5-coder:7b` (Ollama);
  all overridable in `.sentinel.yml` or environment variables.
- Local mode (`SENTINEL_AUTH_MODE=local`) is single-user and binds to loopback; it rejects
  foreign `Host` headers and requires an `X-Sentinel-Client` header (CSRF/DNS-rebinding guard).
  Token mode issues per-user bearer tokens; every query is scoped by user.
- Local repositories can only be reviewed from directories listed in `SENTINEL_LOCAL_ROOTS`
  (defaults to the home directory).
- At most 10 findings per review are shown by default (`review.max_findings` in `.sentinel.yml`;
  the demo repository raises it to 15);
  lower-priority ones are kept as "suppressed", not deleted.
- The demo seeding script writes to `.demo/` in the repo (git-ignored). The weaker process
  sandbox is opt-in only (`--allow-process-sandbox`).

## Original-build verification snapshot (superseded by the 2026-10-17 report)

| Path | How it is tested here | What to try live |
|------|----------------------|------------------|
| Claude provider (`ai/providers/http_providers.py`) | `httpx.MockTransport` with recorded-shape responses | `SENTINEL_PROVIDER=claude ANTHROPIC_API_KEY=… sentinel review --staged` |
| Gemini provider | `httpx.MockTransport` | `SENTINEL_PROVIDER=gemini GEMINI_API_KEY=…` |
| Ollama provider | `httpx.MockTransport` | `ollama serve` + `SENTINEL_PROVIDER=ollama` |
| GitHub App auth (JWT → installation token) | Real RS256 signing; GitHub responses faked (`tests/unit/test_github.py::FakeGitHub`) | Install the App on a test repo |
| GitHub REST calls (PR metadata, tarball, comments, update/dedupe) | Fake GitHub transport | Open a PR on the demo repo |
| Webhook delivery | Locally signed payloads; HMAC check is real | Point the App webhook at `/api/github/webhook` (e.g. via a tunnel) |
| Bandit adapter | Parser tested on recorded JSON (Bandit not installed here) | `pip install bandit` then review the demo repo |
| Docker sandbox image | Sandbox behaviour verified with a locally assembled image (no registry access); `Dockerfile.sandbox` itself not built here | `docker build -f Dockerfile.sandbox -t sentinel-sandbox .` |
| `Dockerfile`, `docker-compose.yml` | Not built or started here (no registry access); YAML validated | `docker compose up --build` |
| CI workflow (`.github/workflows/ci.yml`) | Every command in it was run locally; the workflow itself has not run on GitHub | Push to a GitHub repository |
| ESLint on TypeScript | ESLint runs for JS; for TS it needs `@typescript-eslint/parser`, which is not installed here (reported as unavailable) | `npm i -g @typescript-eslint/parser` |

PostgreSQL is **no longer mock-only**: the store, job queue (including a race between four
worker threads), API lifecycle, tenancy and the end-to-end GitHub flow were run against a
real PostgreSQL 16 (`SENTINEL_TEST_DATABASE_URL`, marker `postgres`).

## NEEDS REVIEW

1. **Frontend stack (§31).** The spec *recommends* Next.js, Tailwind, shadcn/ui, Monaco and
   TanStack Query. The original build used React 19 +
   TypeScript bundled with esbuild, hand-written CSS, a small built-in syntax highlighter and
   a tiny `useQuery` hook. It is served by FastAPI as static files. Components are plain
   React, so moving to Next.js later is mostly a routing/bundling change.
2. **Database migrations — implemented.** Packaged Alembic history and explicit legacy
   adoption are regression-tested on SQLite and PostgreSQL. Deployment backup/restore and
   production-data rehearsals remain. See [DATABASE_MIGRATIONS.md](docs/DATABASE_MIGRATIONS.md).
3. **Fix validation in Docker Compose — implemented.** A dedicated fix-only worker has
   Docker access; the API and review/publication worker do not. Scratch stdin transfer into
   tmpfs avoids daemon/worker path mismatch. Use a dedicated engine/host: the trusted
   validation worker controls that daemon. Rootless engines and stronger VM isolation
   remain deployment options requiring their own acceptance runs (docs/DEPLOYMENT.md).
4. **GitHub App permissions.** Installation tokens are requested with only
   `contents: read`, `pull_requests: write`, `issues: write` (`MIN_PERMISSIONS` in
   `integrations/github/client.py`); `issues: write` is needed because PR conversation
   comments use the Issues API. Check runs are not used. Confirm this matches how you want
   results to appear on PRs.

## Live Gemini verification - 18 October 2026

Gemini 3.8 Flash is now configured and verified with invented examples. A complete
CLI review finished all eight stages, and the model's SQL-injection finding was
independently supported by local analysis. Its proposed parameterized query passed
a separate before/after Docker test: one existing test failed before, both passed
after. The saved fix remains unverified because the current policy requires an
already-passing baseline suite; Apply was not bypassed. No project patch was applied.

See [GEMINI_LIVE_TEST.md](docs/GEMINI_LIVE_TEST.md) for evidence, usage and limits.
At that earlier Gemini-only test stage, OpenCode fallback was off. The current connected fallback is described above.

## OpenCode Docker experiment - 18 October 2026

Docker runs an application in a separate environment. Its image is a saved setup;
a container is a running copy. The official OpenCode 1.19.3 application was installed
inside an image of about 825 MB. The online DeepSeek/GLM models were not downloaded.
No project directory, Gemini key, user login or Docker socket was shared with it.
The temporary containers are gone; the reusable image remains cached.

DeepSeek V4.1 Flash Free answered without a key or payment and reported zero cost.
It identified an empty-list crash, passed Sentinel's actual review JSON schema for
an invented SQL-injection change, and returned no findings for the safe parameterized
version. No tool calls occurred in those successful responses. This is limited
compatibility evidence, not a project-wide accuracy benchmark or an unlimited quota.

GLM-5.3-Flash Free returned HTTP 503 (upstream unavailable) on two standard-mode
attempts. Its review quality is not verified. Denying every OpenCode tool had first
caused misleading HTTP 403 errors for both models; standard Build mode with global
tool permissions set to ask allowed DeepSeek to respond, without any approvals.

At the earlier experiment stage, automatic fallback was off. That earlier direct-HTTP adapter was not the tested
OpenCode route. The new integration above supersedes that candidate, with timeout/output
bounds, verified rejection of tool requests, and a real quota-switching test. Preserve
the existing deployment boundary: review/API workers do not control Docker. No source
patch was installed into the main repository by this experiment.

See [FREE_AI_VERIFICATION.md](docs/FREE_AI_VERIFICATION.md) for the test matrix, explanation,
limitations and remaining integration work. Gemini's separate live results are in
[GEMINI_LIVE_TEST.md](docs/GEMINI_LIVE_TEST.md).
