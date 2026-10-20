# Sentinel compared with SPEC.md

Assessment: **20 October 2026**. Scope: the V1 in [SPEC §§45 and 54](SPEC.md),
including its learning material and a repeatable public demonstration.

**Verdict: V1 is complete within its documented supported limits.** It is a working
portfolio/learning project with CLI, browser and GitHub integration, rather than
only generated scaffolding. An always-on public service still needs deployment and
operational acceptance. Completion does not promise perfect AI accuracy or no unknown bugs.

This assessment reconciles the specification, current source, regression tests and
dated acceptance reports. It is not a new line-by-line audit of every dependency.
Earlier failed experiments remain in their reports; a later success does not erase them.

## What was checked against the specification

“Complete” below means the implemented V1 behaviour has tests/evidence. Bounded static
analysis cannot establish every runtime relationship or prove an application safe.

| SPEC sections | Result | Implementation and evidence |
| --- | --- | --- |
| §§1–4, 57–58: review, evidence, human decision | Complete | [Orchestrator](../src/sentinel/core/review/orchestrator.py) separates model proposals, verification and output; [Apply](../src/sentinel/core/fixes/apply.py) is explicit. |
| §5: Python, JavaScript, TypeScript | Complete | [Language registry](../src/sentinel/analysis/ast/registry.py), compiler/Python parsers; [multilingual](QUALITY_EVALUATION.md) and [cross-file](MULTIFILE_QUALITY_EVALUATION.md) experiments. |
| §§6, 26: CLI, local/staged/range/path and GitHub input | Complete | [CLI](../src/sentinel/apps/cli/review_commands.py), [workspaces](../src/sentinel/services/workspaces.py), [GitHub end-to-end tests](../tests/e2e/test_github_flow.py). |
| §§7–8: staged pipeline, diff and safe filtering | Complete | [Diff/filtering](../src/sentinel/analysis/diff), [review state](../src/sentinel/core/review/state.py); binary/generated/ignored/sensitive paths are filtered, incomplete analysis is reported. |
| §9: lightweight graph and bounded context | Complete within structural limits | [Graph explanation](GRAPH_ANALYSIS.md); functions, imports, modules/variables, callers, tests and data operations. Dynamic dispatch and full taint analysis are not complete; the SPEC explicitly avoids a compiler-grade graph. |
| §10: static analyzers and normalized findings | Complete | [Static adapters](../src/sentinel/analysis/static), locked Python/JS tools and actual Docker/CI runs. Missing tools are reported, not counted as clean analysis. |
| §§11, 24–25, 36, 43: structured AI, BYOK, multiple providers and errors | Complete for V1; live evidence differs by provider | [Provider factory](../src/sentinel/ai/providers/factory.py), [offline provider tests](../tests/unit/test_ai_providers.py), [live Gemini/DeepSeek browser evidence](BROWSER_LIVE_WORKFLOW.md). Claude/Ollama adapters have offline tests; neither is required to run the configured Gemini route. |
| §§12–18: categories, evidence, confidence, verification, deduplication and summary | Complete | [Finding processing](../src/sentinel/core/findings), [verification](../src/sentinel/core/verification), [summary](../src/sentinel/core/review/summary.py), golden/adversarial tests. Unsupported claims remain rejected/uncertain. |
| §§19–21, 31: review UI, details, actions and clickable architecture | Complete for demonstrated V1 flows | [React UI](../web/src), [real browser acceptance](BROWSER_LIVE_WORKFLOW.md), [fresh visitor acceptance](PUBLIC_DEMO_VERIFICATION.md). Full accessibility/device/outage acceptance remains separate. Next.js and the other frontend libraries are recommendations, not mandatory replacements. |
| §§22–23: propose, sandbox, validate, explicit Apply | Complete within conservative fix policy | [Fix engine](../src/sentinel/core/fixes/engine.py), [Docker runners](../src/sentinel/sandbox/runners.py), [multi-file boundary](MULTI_FILE_FIXES.md), actual model and replay-Docker acceptance. Only validated, unchanged local proposals can Apply. |
| §§27–28: repository settings and cache | Complete | [Configuration](../src/sentinel/core/configuration/config.py), [cache](../src/sentinel/infrastructure/storage/cache.py), content/analyzer-version keys and cache tests. |
| §§29–30: PostgreSQL, persistence, jobs and progress | Complete | [Database](../src/sentinel/infrastructure/database), [leased/fenced queue](../src/sentinel/infrastructure/queue), [worker](../src/sentinel/apps/worker/main.py), migrations, SSE and actual PostgreSQL/Compose acceptance. SQLite is the documented local option. |
| §§32–34: backend stack, separation and understandable code | Complete with documented choices | [Architecture](ARCHITECTURE.md) and [decisions](DESIGN_DECISIONS.md); domain ports, application services, adapters and composition root. Strict types, docstrings and complexity gates help maintain readability. Some older cohesive modules exceed suggested file lengths; that is maintenance work, not an excuse to add another layer. |
| §§35, 37–39: unit/golden/integration/end-to-end tests | Complete | [Tests](../tests), actual PostgreSQL and Docker in CI, [real GitHub test](GITHUB_LIVE_TEST.md) and [reconnection test](GITHUB_CONNECTION_RECOVERY.md). Controlled examples do not establish general precision/recall. |
| §40: privacy and security boundaries | Complete within stated threat model | [Security model](../README.md#security-model), path/secret/prompt/tenant/sandbox regressions and minimum App permissions. Trusted validation workers control their Docker engine; generated test containers do not. |
| §§41–42: logs, metrics and benchmarks | Required baseline complete | [Observability](../src/sentinel/infrastructure/observability), [measured size benchmarks](BENCHMARKS.md). OpenTelemetry export is optional and not implemented. Benchmarks exclude real-model latency and do not establish production throughput. |
| §§44–47: restricted V1 scope and development phases | Complete | V1 loop and polish are present. IDE plugins, extra languages, compiler-grade flow, autonomous coding, billing and other V2 work remain intentionally outside scope. |
| §§48–52: learning documents | Complete and updated | [README](../README.md), [architecture](ARCHITECTURE.md), [decisions](DESIGN_DECISIONS.md), [walkthrough](WALKTHROUGH.md), [14-day study guide](STUDY_GUIDE.md). |
| §53: quality gates in CI | Complete; keep green for each release | [Workflow](../.github/workflows/ci.yml): Ruff, strict mypy, Python tests/coverage, frontend checks and isolated Compose acceptance. See verification below. |
| §§54–55: definition of done and public planted-bug demo | Complete for V1 | [Public guide](PUBLIC_DEMO.md), [public templates](../demo/sentinel-demo-repo), [fresh-download proof](PUBLIC_DEMO_VERIFICATION.md). One public checkout creates the separate sample Git repository locally; no second hosted repository or private data publication is necessary. |
| §56: honest resume claims | Available with measured limits | Describe the pipeline and measured experiments. Do not claim perfect detection, compiler-level understanding or production capacity. |
| §59: MUST/SHOULD/DO NOT checklist | MUST items complete | History, cache, repository configuration, progress, visualization and benchmarks also exist. OpenTelemetry is the unimplemented optional SHOULD item; the DO NOT features remain excluded. |

## Issues repaired in this comparison

1. **Conflicting CLI choices silently selected the wrong input.** For example,
   `sentinel review app --staged` reviewed every file under `app`, ignoring the staged
   choice. `--staged --worktree` silently chose staged. The CLI now asks for exactly one
   source before loading private settings, opening a database or contacting AI.
   `--repo` requires `--pr`, and PR numbers must be positive.
2. **A nonexistent review path looked empty.** A misspelled directory could yield an
   empty change set. CLI paths must now exist; shared path analysis also raises an
   explicit error for missing roots/subpaths, including paths that disappear before
   queued work executes. Existing empty directories remain valid.
3. **Valid GitHub repository names containing dots were not recognised.** Automatic
   PR-target inference now preserves names such as `reviewer.demo` for HTTPS and SSH
   remotes, while still stripping the final `.git` transport suffix.
4. **Completion reports contradicted current evidence.** Older status rows still called
   the public demo unverified and listed superseded model/setup assumptions. The current
   verdict now links the accepted fresh download and separates optional/operational work.

[The input regression tests](../tests/unit/test_review_selection.py) cover refusal
before side effects, Git/non-Git missing targets, legitimate empty directories and
GitHub origin inference with dotted names.
Existing CLI tests continue to exercise all valid modes. There is no new framework,
provider, paid service or bypass of validation.

## Verification after these repairs

| Check | Executed result |
| --- | --- |
| Full local Python 3.14.4 suite, including real Docker validation | **665 passed, 27 PostgreSQL variants skipped**; no local PostgreSQL test URL was configured. This full run includes the first 13 new input cases. |
| Final focused suite after the additional dotted-origin repair | **20 passed**; includes all input cases and seven origin cases. Existing valid CLI/diff tests also passed. |
| Coverage from the full run | **93.64% overall / 97% core**; above the SPEC's 80% / 90% gates. |
| Final source Ruff lint/format and strict application typing | Passed; 235 Python files formatted, 155 application modules typed. Bridge and demo-tool strict typing passed in the full check. |
| Independent installable-wheel smoke | Passed: imports came from the temporary wheel install, bundled JS was present, packaged migrations initialized a new database, browser assets served and CLI version worked. No AI calls. |
| Documentation links and saved-credential comparison | 437 document/source links resolve; edited public files/exports contain none of the checked saved credentials. Private key/config/token permissions remain 0600. |

The full local run completed while the final origin-only repair was added. Its 665
tests and the final focused 20 are **not added together** as a distinct-test total.
The published revision's CI runs the complete final tree, including PostgreSQL and
frontend/Compose checks; use the linked workflow to identify its exact revision.


The preceding uploaded revision `48a83fe` also passed all three hosted jobs in
[39383034428](https://github.com/krish-121/Ai-code-reviewer/actions/runs/39383034428):
678 Python tests, one skip, 27 frontend tests and Compose acceptance. Those historical
counts are kept distinct from this repair's results. The [CI page](https://github.com/krish-121/Ai-code-reviewer/actions/workflows/ci.yml)
identifies the exact commit and newest hosted outcome.

No new billable/live model requests or GitHub notification relays were needed to
verify these input repairs. Earlier real-model and signed-PR evidence retains its
original scope; it was not rerun or relabelled as a fresh experiment here.

## What is actually left

There is **no identified mandatory V1 feature left unimplemented** in this comparison.
The remaining list depends on what you want to offer next:

| Work | When it is needed | Why |
| --- | --- | --- |
| Start the local server, Docker and configured bridge | Whenever using the live local workflow | Saved configuration is not a running process. Free-provider outages/quotas can still prevent an AI response. |
| Reconnect an approved GitHub webhook endpoint | Before another live automatic PR review | Smee was disconnected and its temporary local access removed at your request. The App remains installed only on the private test repository. No continuous notification connection is currently promised. |
| Durable HTTPS hosting, authentication/reverse-proxy acceptance | Before offering a service that works while your computer is off | A working supervised local test does not provide permanent hosting. |
| Full interruption/race, backup-restore/upgrade and load/retention rehearsals | Before other people depend on a deployed service | Leases, retries, migrations and existing tests are implemented; full operator recovery and production capacity have not been accepted. |
| Full keyboard/accessibility, screen-size and reconnect matrix | Before a broad public-service rollout | Current component/browser acceptance covers important flows, not every device or failure combination. |
| Broader independent model-quality/business-contract evaluations | Ongoing, especially before relying on fixes | The pricing case demonstrated why passing generated tests can still miss an intended contract. Conservative refusal and human review remain necessary. |
| OpenTelemetry; live Claude/Ollama or distributed OpenCode-profile acceptance | Only if chosen | These are optional capabilities/deployment choices. Ollama is not installed and is not required; GLM is unavailable/disabled, so it is not a working fallback. |
| V2 features and targeted readability improvements | Later maintenance or a new project phase | Keep changes focused. Do not turn completion into an endless framework rewrite or a list of unrelated features. |

Your saved Gemini 3.8 default and quota-only free DeepSeek fallback remain unchanged.
The key-free public demo uses clearly labelled scripted AI replies while running real
analysis, verification, queueing, Docker tests and explicit Apply. See the walkthrough
for the code path and the release page for operational acceptance details.
