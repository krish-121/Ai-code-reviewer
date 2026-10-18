# S16: baseline comparison and deletion-impact analysis

**Subsequent SPEC work:** migrations and multi-file fixes are now implemented; see [current release readiness](RELEASE_READINESS.md). The counts and remaining-work notes below are the earlier audit checkpoint.

Verified **2026-10-18**. **S16 is resolved within Sentinel's supported static-analysis scope. All 24 audit findings S10–S33 are now resolved.** The earlier S01–S09 regressions also passed again. Changes remain local and uncommitted. This closes the audited defects; live-service acceptance and the broader SPEC limits listed below remain separate work.

## What changed

When a change removes lines, deletes a file, or renames a file, static analysis runs over **every eligible source file in both base and head**, including unchanged importers, callers, transitive callers and tests. It no longer discards diagnostics merely because their files or cited lines were unchanged. This full scan avoids relying on incomplete graph reachability to decide which files deserve analysis.

Staged reviews export their pinned index tree and base commit. Range reviews export the target commit and use the actual Git merge-base that produced the three-dot diff. Working-tree reviews copy the source and reject a diff that changes during copying, so later edits do not change the analyzed tree. PR reviews retain base/head revision guards, resolve the diff's common ancestor through GitHub's comparison API, download that exact baseline, and persist its SHA as `ChangeSet.baseline_ref`. The current base-branch tip remains `base_ref` for publication guards. GitHub's [comparison response schema](https://docs.github.com/en/enterprise-cloud%40latest/rest/commits/commits#compare-two-commits) supplies `merge_base_commit`.

Head diagnostics are classified as `introduced`, `pre-existing`, or `unknown`. Matching requires the same producer, rule, message, and unchanged source span mapped across line shifts and renames. Multiplicity is preserved. Confirmed baseline diagnostics remain in suppressed results with an explicit reason; new diagnostics can surface anywhere in the surviving source tree. Merging findings preserves new/unknown eligibility and cannot accidentally hide them behind a pre-existing finding.

An additional structural check detects imports whose previously local target was explicitly deleted or renamed away. It covers Python and JS/TS local module resolution, including newly added imports and callers. It never treats a file omitted by the inventory as proof of deletion or guesses the availability of third-party packages. Python type checks now inspect untyped function bodies. Compiler/type diagnostics handle supported removed-export cases.

The AI receives redacted deleted-code hunks and bounded source context around affected surviving diagnostic sites. Already-confirmed pre-existing diagnostics are omitted from AI hints. Deleted files count as reviewed. Saved static-stage metrics include base/head file counts and introduced/pre-existing diagnostic counts, and baseline tool runs are recorded as `base:<tool>`.

Missing snapshots, unavailable/disabled/failed/timed-out analyzers, missing analyzer records, incomplete parsing, truncated/unreadable source inventories and omitted impact context leave the review **partial** with visible limitations. Incomplete comparison never establishes that a head diagnostic is pre-existing. Source exclusions, language policy, secret filtering and prompt budgets still apply.

## Source and regression evidence

- Baseline comparison and completeness: [src/sentinel/core/review/baseline.py:92](D:/sentinel-final-v2/sentinel/src/sentinel/core/review/baseline.py:92).
- Lost local imports: [src/sentinel/analysis/graph/deletion.py:17](D:/sentinel-final-v2/sentinel/src/sentinel/analysis/graph/deletion.py:17).
- Affected source context: [src/sentinel/core/review/impact_context.py:12](D:/sentinel-final-v2/sentinel/src/sentinel/core/review/impact_context.py:12).
- Local snapshots: [src/sentinel/services/workspaces.py:61](D:/sentinel-final-v2/sentinel/src/sentinel/services/workspaces.py:61).
- PR baseline acquisition: [src/sentinel/services/baselines.py:14](D:/sentinel-final-v2/sentinel/src/sentinel/services/baselines.py:14).
- GitHub merge-base lookup: [src/sentinel/integrations/github/client.py:212](D:/sentinel-final-v2/sentinel/src/sentinel/integrations/github/client.py:212).
- Pipeline integration: [src/sentinel/core/review/orchestrator.py:242](D:/sentinel-final-v2/sentinel/src/sentinel/core/review/orchestrator.py:242).
- Regression scenarios: [tests/unit/test_deletion_impact.py:80](D:/sentinel-final-v2/sentinel/tests/unit/test_deletion_impact.py:80).
- Real tools and snapshot integration: [tests/integration/test_deletion_impact.py:36](D:/sentinel-final-v2/sentinel/tests/integration/test_deletion_impact.py:36).

Added **38 parametrized regression cases** across unit and integration tests. They cover deleted modules in Python/JS/TS; newly introduced imports of deleted modules; removed Python exports; new errors on unchanged lines; complete scanning of unchanged/transitive callers; pre-existing findings; line shifts; renames; duplicate multiplicity; finding merges; external/updated imports; filtered and unreadable sources; inventory/context budgets; syntax failures; all incomplete-tool outcomes; pure deletion; local staged/range/worktree acquisition; divergent branches; missing local revisions; valid/invalid GitHub merge bases; snapshot cleanup; and secret redaction in context and deleted hunks.

The two existing pipeline fixtures that expected complete reviews now supply their real baseline snapshot. No test assertion was disabled, no lint rule was relaxed, and no coverage threshold was lowered. An intermediate database connection failure came from stopped Docker Desktop, not a code defect; both final suites ran all PostgreSQL variants successfully. A verification wrapper's trailing Windows newline was normalized after all its recorded test commands had returned zero; the portable harness is included in the evidence.

## Final checks

| Check | Result |
|---|---|
| Focused regression suite | **225 passed**, no warnings; exit 0 |
| Python 3.11.17 + Node 22 | **398 passed, 4 environment skips**, no warnings; 42.79 seconds; exit 0 |
| Python 3.14.4 + Node 22 under WSL | **399 passed, 3 Docker skips**, no warnings; 84.00 seconds; exit 0 |
| Overall branch-inclusive coverage | **93.79%** on Python 3.11; **93.89%** on Python 3.14; gate 80% |
| Core branch-inclusive coverage | **96.85%** on Python 3.14; both environments pass the 90% gate |
| Live Docker sandbox integration | **3 test bodies passed** against `sentinel-sandbox:s16-20261018` |
| Ruff / Python formatting / strict mypy / whitespace | All pass; 175 files formatted, 133 source files type-checked for Linux |
| Clean frontend dependency install | `npm ci`, 73 packages, exit 0 |
| Frontend checks | **20 tests passed**, types/Prettier and production bundle pass |
| Docker builds | App `sentinel:s16-20261018` and sandbox `sentinel-sandbox:s16-20261018` pass |
| Installed app package | Built UI, TS extractor, S16 modules and LICENSE present; UID 10001; `.git`/`.env` excluded |
| App smoke checks | `/api/health`, `/`, `/assets/app.js`: 200; unauthenticated `/api/reviews`: 401 |
| Dependency consistency | Python 3.11 `pip check` passes; pinned clean installs pass in both Python environments |

The full-suite Docker skips were exercised as the actual test bodies in a separate Docker Desktop bridge (mount-path translation only). Python 3.11's fourth skip is optional process network namespaces; that test passed in WSL. No PostgreSQL variants were skipped. Coverage numbers exclude the separate live Docker body runs. BuildKit emits its existing `SecretsUsedInArgOrEnv` warning for the non-secret setting `SENTINEL_AUTH_MODE=token`; no credential value is involved.

## Still unverified or outside these defect closures

- Live Claude/Gemini/Ollama and GitHub App authorization/publication, hosted CI, complete rendered-browser workflows, and a full Compose deployment remain unverified. Local mocks, real PostgreSQL, real containers and HTTP smoke tests cover the stated boundaries.
- Static analysis cannot establish arbitrary runtime deletion effects, dynamic imports/reflection or assertion coverage. Eligible language/source policies and configured resource limits bound the scan. Incomplete required checks remain partial rather than proving safety.
- The audit's broader delivery/feature gaps remain: database upgrade migrations, full module/variable/data-flow graph coverage, multi-file generated fixes/new regression-test files, and public demo deployment. Compose fix validation requires a separate Docker-capable worker. The API image's optional analyzer set is narrower than CI/the sandbox.
- GitHub still provides no atomic compare-and-comment operation: a push during the final outbound request can leave an explicitly labelled older-commit comment. Lease fencing prevents stale service commits but cannot cancel a provider call already in flight.

The 2026-10-17 evidence archive is historical. The new S16 evidence archive contains final logs, exact commands, coverage, dependency versions, image IDs, current source hashes and the test harnesses. No source changes were committed or published.

Final evidence: [logs, hashes and reproducible commands](C:/Users/Krishna/Documents/Codex/2026-10-14/referenced-chatgpt-conversation-this-is-an/outputs/Sentinel-S16-Evidence-2026-10-18).
