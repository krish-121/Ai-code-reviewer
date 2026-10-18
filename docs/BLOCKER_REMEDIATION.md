# High-priority audit blockers: remediation and verification

Verified 2026-10-16. Scope: audit findings S01–S09. All nine fixes are implemented,
with 53 new regression cases (45 unit, 7 HTTP/pipeline, 1 live Docker integration).
Changes are local and uncommitted. This does not close the audit's remaining S10–S33 findings.

## What changed

| Blocker | Repair | Regression evidence |
|---|---|---|
| S01: file access outside the repository | Canonical relative paths are required. File access opens each component through pinned directory descriptors without following symlinks; hard links are rejected. Apply checks hashes and writes through the same open descriptors. Invalid and rejected findings cannot queue fixes through the API. | `test_s01_*` in [unit regressions](../tests/unit/test_blocker_regressions.py), plus persisted-finding HTTP tests in [boundary regressions](../tests/integration/test_blocker_boundaries.py). Implementation: [paths.py](../src/sentinel/core/paths.py), [engine.py](../src/sentinel/core/fixes/engine.py), [finding routes](../src/sentinel/apps/api/routes/findings.py). |
| S02: generated code executing through host tools | Fix analysis now runs in Docker using a trusted installed entry point and `python -I`. Repository tools/plugins are not loaded. Process runners cannot validate generated code. Scratch copies omit dependency links, symlinks and sensitive files. | `test_s02_*`; `test_process_sandbox_cannot_execute_generated_code`; live `test_fix_analysis_and_tests_use_trusted_container_tools`. Implementation: [container analysis](../src/sentinel/sandbox/analysis.py), [entry point](../src/sentinel/sandbox/analyze.py), [Dockerfile](../Dockerfile.sandbox). |
| S03: credential leakage | Multiline private keys are redacted before diff lines are rendered, preserving line positions. Redaction no longer uses entropy or placeholder-substring exemptions. Static hints, tool messages and raw fix requests are sanitized. Sensitive files are rejected before fix reads and excluded from scratch copies. | `test_s03_*`, persisted `.env` HTTP rejection, and the existing GitHub end-to-end assertion that raw provider requests contain no planted Stripe key. Implementation: [secrets.py](../src/sentinel/analysis/diff/secrets.py), [filtering.py](../src/sentinel/analysis/diff/filtering.py), [fix safety](../src/sentinel/core/fixes/safety.py). |
| S04: ignored files re-entering context | Graph/source collection now honors ignore patterns, language settings and previously skipped paths. Context and saved snapshots are built from that filtered source set. | `test_s04_context_and_snapshot_honor_ignore_and_language`; `test_s04_ignored_caller_never_enters_provider_or_saved_sources`. Implementation: [workspace collection](../src/sentinel/core/review/workspace.py), [orchestrator](../src/sentinel/core/review/orchestrator.py). |
| S05: allowed child expanding to an unauthorized Git root | The API authorizes the effective repository root, and queued requests recheck their allowed roots. Source reads reject external symlinks. | `test_s05_*`, including HTTP rejection of an allowed child inside a disallowed parent Git repository. Implementation: [review routes](../src/sentinel/apps/api/routes/reviews.py), [workspaces](../src/sentinel/services/workspaces.py), [Git source reads](../src/sentinel/analysis/diff/git.py). |
| S06: tool failures reported as clean success | Tool-specific exit/output contracts distinguish diagnostics from execution failures. Malformed output, ESLint fatal errors, Bandit errors and non-file TypeScript errors cannot become successful empty runs. Failures propagate to partial reviews. | `test_s06_*`, including valid nonzero diagnostic exits and a pipeline partial-status check. Implementation: [diagnostics.py](../src/sentinel/analysis/static/diagnostics.py), [base.py](../src/sentinel/analysis/static/base.py). |
| S07: false validated verdicts | Both versions need matching successful analyzer runs. The target must reproduce at its cited location, and its reproducing rules must disappear from that file. All required analysis and sandbox test checks must pass. No-op edits are rejected; edit whitespace is preserved. | `test_s07_*`, updated fix/API/CLI tests and successful live Docker validation. Implementation: [validation.py](../src/sentinel/core/fixes/validation.py), [patch.py](../src/sentinel/core/fixes/patch.py), [engine.py](../src/sentinel/core/fixes/engine.py). |
| S08: unknown SQL declared safe | Only proven literal/parameterized SQL can receive a decisive safe verdict. Unknown arguments, builder results and attributes remain neutral. | `test_s08_unknown_sql_is_not_decisively_safe` (three cases), existing literal/parameterized/dynamic SQL tests. Implementation: [SQL probe](../src/sentinel/analysis/static/probes/sql.py). |
| S09: demo setup deleting existing work | Demo creation refuses any existing destination, including symlinks. The recursive deletion branch is removed. | `test_s09_existing_demo_directory_is_never_deleted`, plus existing demo-based integration tests. Implementation: [demo builder](../demo/build_demo_repo.py). |

## Verification results

Testing used a disposable Linux source copy, isolated dependencies and temporary SQLite
databases. No live AI service, GitHub publication or production database was used.

| Check | Result |
|---|---|
| Focused regression suite (new blocker tests plus fix, filtering, static-analysis and verification tests) | **141 passed** |
| Full suite: `python -m pytest -q --cov=sentinel --cov-report=term --cov-report=json:<evidence>/remediation-coverage.json --cov-fail-under=80 -ra` | **305 passed, 12 skipped, 39 warnings**; exit 0 |
| Overall line + branch coverage | **93.52%**, gate 80% |
| Core coverage: `python -m coverage report --include=*/sentinel/core/* --fail-under=90` | **96.59%**, gate 90% (rounded terminal report: 97%) |
| `python -m ruff check src tests scripts` | **Pass** |
| `python -m ruff format --check src tests scripts` | **Pass**, 159 files formatted |
| `python -m mypy --platform linux` | **Pass**, 123 source files; strict settings from `pyproject.toml` |
| `git diff --check` | **Pass** |
| `docker build -f Dockerfile.sandbox -t sentinel-sandbox:sentinel-blockers-20261015 .` | **Pass** |
| Live Docker: `test_docker_sandbox_runs_isolated` | **Pass**: tests execute, network is blocked, root filesystem writes fail, timeout kills execution |
| Live Docker: `test_fix_analysis_and_tests_use_trusted_container_tools` | **Pass**: complete SQL fix validation, configured repository plugin cannot execute on host, original source unchanged |

The full suite skipped ten PostgreSQL variants and two Docker tests because its normal
WSL Docker command could not access Docker Desktop. **Both Docker test bodies were then
executed successfully against real containers**, using a test-only adapter that calls
Docker Desktop's Windows executable and translates mount paths. These are not mocked
Docker successes. Their separate execution is not included in the coverage percentages.
All 53 newly added regression cases were exercised successfully across these runs.

The former pipeline logging failure was fixed by isolating that test's log handler from
CLI configuration and parent handlers, preserving its one-record-per-stage assertion.
CLI/API tests now require an unverified verdict when no Docker validation was provided.

## Remaining limitations and operational steps

- **No unresolved confirmed S01–S09 defect remains in the exercised cases.** This is not a
  claim that all possible secret formats, hostile repositories or runtime environments
  have been exhaustively proven safe.
- Ten PostgreSQL variants remain unverified in this run; no disposable PostgreSQL database
  was configured. SQLite tests passed.
- The full run emitted 39 warnings, primarily SQLite connection cleanup/resource warnings
  and a FastAPI/Starlette test-client deprecation. They do not fail the suite and were not
  repaired in this blocker-only change.
- Docker Desktop's WSL integration is disabled on this machine. Enable integration for
  the intended WSL distribution for ordinary CLI/worker use. The test-only mount adapter
  is verification infrastructure, not a production dependency.
- Rebuild the deployment's `sentinel-sandbox` image after updating Sentinel, or explicitly
  select the verified image tag above. Existing image tags and repository secrets/config
  were not replaced. Project test dependencies must be installed in the image; validation
  does not reuse host dependency directories.
- Validation is deliberately conservative: missing/disabled/failed checks leave a patch
  unverified. An AI-only finding without a deterministic reproducer remains unverified
  even when tests pass. Multiple same-rule findings or shifted locations may require a
  more precise future matching algorithm. Applying an unverified patch still requires
  the existing explicit user action.
- Confined file access requires Linux/macOS POSIX facilities; on Windows use WSL, as
  already documented. Native Windows file access does not use an unsafe fallback.
- Demo setup now requires a fresh destination; it will not overwrite an existing demo.
- The other 24 audit findings, S10–S33, remain outside this change. No frontend changes
  were made, so frontend checks were not rerun.
