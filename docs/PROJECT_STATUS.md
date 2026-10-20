# Current project status and remaining work

## Current V1 completion assessment — 20 October 2026

The [SPEC comparison](SPEC_COMPLETION.md) checks all requirement groups and the
definition of done. V1 is complete within its supported limits. This comparison repaired
ambiguous CLI review choices, missing paths that could look empty, and dotted GitHub origin inference;
regressions protect both. It also removes stale claims that the public demo is still
unverified. See that report for current test results and the exact remaining list.

Continuous GitHub notifications remain disconnected by request. Permanent hosting,
full production recovery/load/accessibility acceptance and broader model evaluation
remain separate follow-up work. Ollama, GLM, OpenTelemetry and V2 expansion are not
required to use the completed configured workflow. Earlier dated entries below are history.

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
- See [PUBLIC_DEMO_VERIFICATION.md](PUBLIC_DEMO_VERIFICATION.md). The replies are
  explicitly scripted; this closes public-demo acceptance, not general model accuracy
  or the separate production/recovery/accessibility/load acceptance work.

## Public runnable demo — 19 October 2026

The [public demo guide](PUBLIC_DEMO.md) now gives a single-checkout quickstart,
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

**Local browser acceptance — 19 October 2026:** real Gemini 3.5 Flash-Lite and real
free DeepSeek each completed browser review → fix generation → all seven Docker
validation checks → explicit Apply. Final saved attempts are applied/fixed; independent
injection/quoting tests passed. DeepSeek used a controlled local Gemini 429, not a
scripted model response. Gemini 3.8 was busy; its saved default is unchanged by the
owner's choice. Fixed misleading uncertainty/model labels, stale UI assets and an
overconfirmed test-code claim. Normal CLI restored; Smee remains disconnected.
**648 Python tests passed, 27 PostgreSQL variants skipped**; all **36 Docker tests** ran. Overall/core coverage: **93.59% / 97%**. Ruff lint/format and strict application/bridge/helper typing passed. Frontend: **27 tests passed**, type/format checks and production build passed.
See [BROWSER_LIVE_WORKFLOW.md](BROWSER_LIVE_WORKFLOW.md).

The public demo task from this earlier checkpoint is now implemented above. Live distributed
Compose-profile acceptance, outage/recovery, accessibility and capacity work remain
under deployment operations; this local run does not silently close those checks.

**Completion assessment — 19 October 2026:** all three code-check jobs in
[39286099864 on `d2cd45c`](https://github.com/krish-121/Ai-code-reviewer/actions/runs/39286099864)
report success. Completed logs confirm **673 Python tests passed, one optional skip**,
**21 frontend tests passed**, and successful isolated Compose acceptance. PostgreSQL
variants ran; Ruff, strict typing, builds and coverage gates passed. GitHub's incident
delayed status visibility; the initial queued results were not code failures. No code
repair or weakened gate was needed. Later documentation-only commits have separate runs.

This earlier checkpoint predates the successful local browser run above. The core
local workflow and configured bridge browser acceptance now work; the reproducible
recruiter-facing public demo was the next task; it is now provided above. Production hosting/recovery/load work is separate. The current
acceptance list is [RELEASE_READINESS.md](RELEASE_READINESS.md), replacing outdated
release percentages and already-completed integration gaps.

**GitHub recovery checkpoint — 19 October 2026:** a real signed ping and
[PR #2](https://github.com/krish-121/sentinel-integration-demo/pull/2) succeeded through
a temporary, explicitly approved Smee relay. Gemini completed all eight stages and
published one summary plus one inline SQL-injection warning. No fix was applied and
the PR is unmerged. Smee has now been disconnected: routing removed, temporary
container/image/gateway and private channel/restoration records deleted. The existing
test-only App and saved AI keys remain. **New automatic GitHub reviews are currently
disconnected by request.** This latest state supersedes earlier running-connection
descriptions. Added public readiness checks before saving a Cloudflare address;
647 local tests passed, 27 PostgreSQL variants skipped, all 36 Docker tests ran.
See [GITHUB_CONNECTION_RECOVERY.md](GITHUB_CONNECTION_RECOVERY.md).

**Pricing follow-up — 19 October 2026:** the observed Python helper-contract miss is
repaired in a fresh normal review/fix/validate/Apply workflow. Independent tests and
63 additional supported integer scenarios passed on the actual applied example.
A correct fix generated from the older downstream finding remains safely unverified;
rerunning review identifies the root cause. Stronger contract-focused instructions,
clearer unverified guidance and an offline captured-patch Docker regression are added.
See [PRICING_FIX_INVESTIGATION.md](PRICING_FIX_INVESTIGATION.md). This closes that
observed example, not general public-contract completeness or causal helper validation.
Local follow-up checks: **633 passed, 27 PostgreSQL skips**, 36 real Docker
tests; overall/core coverage **93.55% / 97%**, lint/format/types passed.
The cross-file checkpoint immediately below records the earlier result unchanged.

**Cross-file quality checkpoint — 19 October 2026:** nine additional controlled
applications, each with six application files and three changed source files. Initial
round: all six bugs detected, one false alarm among three correct changes. After context
repairs, the repeated round detected all six bugs and left all three controls clear.
Five fix cases passed independent checks and normal Apply, including a two-production-
file TypeScript fix. **One Python pricing-contract miss remains:** both model proposals
passed normal checks but failed the separate contract test and were not applied.
Added imported data context, safer target-change verification, neutral treatment of
opaque properties and filtered original-review context for fixes. See
[MULTIFILE_QUALITY_EVALUATION.md](MULTIFILE_QUALITY_EVALUATION.md) for exact evidence
and limits. These are small authored applications, not production-scale proof.

**Multilingual quality checkpoint — 19 October 2026:** 15 controlled examples
under neutral project names: nine known bugs detected, six correct changes without
warnings, and nine final real-model fixes validated/applied to disposable examples with
independent held-out Docker checks. The final round used free DeepSeek; the initial
round naturally switched from Gemini on a real quota error. This is a small-corpus
result, not a general perfect-accuracy claim. See [QUALITY_EVALUATION.md](QUALITY_EVALUATION.md).

Assessment date: **19 October 2026**. Gemini is configured and live-tested. Automatic
quota fallback to free DeepSeek through official OpenCode is connected and tested,
with a separate local Docker bridge. Local live GitHub acceptance is complete; broader
quality and production/operations evidence remain open; these provider checks do not declare the entire release complete.

See [FREE_AI_FALLBACK.md](FREE_AI_FALLBACK.md) for beginner setup and source structure,
[DEEPSEEK_FALLBACK_VERIFICATION.md](DEEPSEEK_FALLBACK_VERIFICATION.md) for current test
evidence and [WALKTHROUGH.md](WALKTHROUGH.md) section 6.1 for the complete request flow.
The earlier Docker experiment below is historical: its direct API candidate and GLM
were not enabled. The current chain contains Gemini and free DeepSeek only.

**Local live fix acceptance is now complete.** The normal sandbox image exists and
the WSL copy transport is saved. Actual Gemini generated a parameterized SQL fix and
a regression test; all seven checks passed, normal Apply succeeded, three tests passed
afterward and history records the finding as fixed. Normal local app/worker startup
also passed. See [LIVE_FIX_WORKFLOW.md](LIVE_FIX_WORKFLOW.md). This does not close the
broader quality or deployed browser acceptance work below.

GitHub setup/gateway checkpoint checks: **525 passed, 27 PostgreSQL skips**,
all seven real Docker tests ran against the normal image; overall/core coverage
**93.38% / 96%**. Ruff lint/format and strict typing passed. The verification table
below preserves the earlier PostgreSQL, browser and deployment evidence with its
original scope.

**Source hosting and hosted CI are verified.** The public source repository is
[krish-121/Ai-code-reviewer](https://github.com/krish-121/Ai-code-reviewer).
[The real hosted run](https://github.com/krish-121/Ai-code-reviewer/actions/runs/39141482827) passed all three jobs on `8eb6c44`:
Python/PostgreSQL (**544 passed, 1 skip**), frontend (**21 passed**, type/format/build),
and Docker/Compose acceptance. The local publication check passed 518 with 27 PostgreSQL
skips. Hosted CI uses controlled provider/GitHub fixtures.

**Real GitHub App acceptance also passed.** The personal App is installed only on the
private disposable test repo. [PR #1](https://github.com/krish-121/sentinel-integration-demo/pull/1)
completed actual signed delivery, Gemini review, database/UI display and bot summary/inline
comments. Actual redelivery created no duplicate work; a corrected second push updated
the same summary. Owner-isolation checks passed. The App key and notification secret are
saved outside Git; only the webhook route is exposed by a temporary tunnel. Both PR
reviews used Gemini successfully, so this run did not trigger the enabled DeepSeek fallback.
See [GITHUB_LIVE_TEST.md](GITHUB_LIVE_TEST.md).

## What was inspected

The starting checkout is `D:/sentinel-final-v2/sentinel`. Its complete non-VCS/non-dependency
inventory contained **362 files / 3,298,637 bytes**, including hidden configuration, CI,
tests, fixtures, demo, documentation and packaged assets. The specification, supplied
correction transcript, earlier **Audit Sentinel project completeness** chat, original
all-file engineering audit, requirement matrix and subsequent remediation/evidence reports
were reconciled with the current source and execution paths. Generated bundles were checked
through their authored source and a rebuild.

This session extends the earlier all-file audit. It is not a claim of a fresh independent
line-by-line security audit of every dependency or every previously reviewed line.
The untouched starting copy passed **460 tests**, with real PostgreSQL and Docker enabled.
Testing used disposable copies/databases; existing user databases and repositories were
not used as test targets. Prior uncommitted work is retained.

## What was broken, and what the earlier work repaired

| Earlier defect group | Current implementation/evidence |
|---|---|
| S01–S09: path escapes, host execution of generated changes, secret/ignore/root boundaries, false analyzer success, false validation/verdicts, destructive demo setup | Confined reads/writes, Docker validators, shared filtering/redaction, explicit incomplete results, conservative verification, exclusive demo creation. See [BLOCKER_REMEDIATION.md](BLOCKER_REMEDIATION.md). |
| S10–S33: repository identity, queue/delivery races and stale workers, GitHub revision/ownership, deletion and baseline analysis, AI parsing/prompts, finding processing, UI recovery, metrics/output/dependencies | Existing targeted regressions remain in the passing suite. See [REMAINING_AUDIT_REMEDIATION.md](REMAINING_AUDIT_REMEDIATION.md) and [S16_REMEDIATION.md](S16_REMEDIATION.md). |
| Migrations | Packaged Alembic revisions, explicit legacy adoption, compatibility checks, locking and rollback; SQLite/PostgreSQL regressions. See [DATABASE_MIGRATIONS.md](DATABASE_MIGRATIONS.md). |
| Multi-file fixes | Coordinated edits and advertised regression-test creation; before/after checks, stale-file protection and ordinary-error rollback. See [MULTI_FILE_FIXES.md](MULTI_FILE_FIXES.md). |
| Deployment and analyzer consistency | Dedicated Docker fix worker, job routing, trusted scratch transfer and locked Python/JS analyzers in application/sandbox/CI. Full disposable Compose rehearsal. See [DEPLOYMENT.md](DEPLOYMENT.md). |

The previous reports mark the original 33 findings resolved within their documented scope.
Passing regressions support those repairs; they do not establish that no other defect exists.

## What this continuation changes

| Change | Why it matters | Source/tests |
|---|---|---|
| Preserve module and variable nodes; add lexical global/imported-variable reads/writes in Python, TS and JS | A changed constant can bring its unchanged consumers into review context. Shadowed locals do not invent global dependencies. | `analysis/ast/python_access.py`, `ts_bindings.js`, `analysis/graph/variables.py`; `tests/unit/test_graph_dependencies.py` |
| Endpoint identity includes file and handler | Equal route names in different files cannot accidentally share one endpoint and fabricate paths. | `analysis/graph/builder.py`; same-route regression |
| Independent, deterministic and bounded UI graph projections | Preparing one view cannot mutate the full analysis graph; ties and node budgets behave predictably. | `core/domain/graph.py`, `analysis/graph/architecture.py`; projection/budget regressions |
| Analyzer cache version 4 and clear variable labels | Old cached extraction cannot hide the new relationships; variables are not drawn as functions. | `analysis/ast/registry.py`, `web/src/review/ArchitectureTab.tsx` |
| Validated-only Apply at core/API/CLI/UI | Browser acceptance exposed that unverified proposals could still be applied. They remain inspectable/downloadable; incomplete validation cannot reach Sentinel's working-tree writer. | `core/fixes/apply.py`, API serializers, CLI fix command, `FixPanel`; unit/API/CLI/component regressions |
| Separate bounded analysis-report output from test logs | Valid analyzer JSON exceeded the 20 KB log limit and prevented demo fix validation. Reports now have an explicit 1 MiB allowance/shared 2 MiB capture; test logs keep their original limits. | `sandbox/analysis.py`, `runners.py`, `output.py`; real Docker report/demo regressions |
| Demo TypeScript configuration and useful incomplete-check details | The compiler can run, and failed/incomplete validation identifies the tool/reason instead of only a generic verdict. | demo `tsconfig.json`, `core/fixes/validation.py` |
| Current learning material and benchmarks | The walkthrough now explains migrations, worker routing, multi-file fixes, variable context and Apply boundaries. | [GRAPH_ANALYSIS.md](GRAPH_ANALYSIS.md), [WALKTHROUGH.md](WALKTHROUGH.md), [STUDY_GUIDE.md](STUDY_GUIDE.md), [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md), [BENCHMARKS.md](BENCHMARKS.md) |

Fourteen of the 18 new graph cases fail against the original source; all pass against the
changes. Existing path/repository-identity tests now use validated fixtures so they still
exercise filesystem confinement after the new Apply precondition. API/CLI cases that
previously expected an unverified Apply now require refusal and unchanged files.

## Verification in this continuation

| Check | Result |
|---|---|
| Starting source, Python 3.14 | 460 passed, zero skipped |
| Final Python 3.14.4 + PostgreSQL + Docker | **495 passed, zero skipped**, 70.49 s |
| Final Python 3.11 + separate PostgreSQL + Docker | **494 passed, 1 optional namespace skip**, 137.30 s; skipped case passes on 3.14 |
| Actual Docker tests | All **7** cases run in both full suites, including the packaged demo and report budget |
| Branch-inclusive overall/core coverage | **93.48% / 96.21%** on 3.14; **93.46% / 96.21%** on 3.11 |
| Ruff / formatting / mypy strict | Pass; 201 Python files formatted, 149 source modules type-checked |
| Dependency consistency | Pass on both Python environments |
| Frontend | **21 passed**, no skips; type/format checks and production build pass |
| Final rebuilt Compose | Auth/UI/assets/SSE/metrics, six analyzers, queued three-file fix, Docker validation, Apply and service-recreation persistence pass |
| Actual browser smoke | Token login and invalid-token recovery; review creation/navigation; findings and variable source; generation, validation and Apply to disposable repo |
| Current size benchmarks | Three runs each; median **1.073 / 1.465 / 4.042 s**, all six analyzers; instantaneous measuring provider |

No pytest warnings were reported. The Docker/Compose provider is a deterministic HTTP
fixture and the browser provider is scripted replay. Browser smoke is not a complete
accessibility/reconnection matrix. The 3.11 verification image supplies the runtime/tools;
its source directory is replaced by the exact current staged source. Coverage is collected
in each host test process, not merged with subprocess/container internals. Builds may retain
ordinary package-manager notices and the existing warning about the non-secret
`SENTINEL_AUTH_MODE` environment-variable name; they are not failed gates.

## V1 requirement map

| SPEC area | Status and practical boundary |
|---|---|
| Local/staged/range/path inputs (§6, §8, §26) | Implemented and exercised through services/API/CLI. |
| GitHub PR input and comments (§6, §39) | Actual private App installation, signed delivery, Gemini review, database/UI display, bot comments, real redelivery, second-push summary update and owner isolation passed. Live concurrent-push races and durable hosting remain. |
| Python/TS/JS parsing (§5, §9) | Real parsers with explicit degraded TS/JS fallback. |
| Graph/context (§9, §21) | Implemented structural graph including module variables, imported bindings, callers/tests/routes/data access. Bounded/degraded/dynamic analysis limits remain explicit. |
| Static analysis (§10) | Built-in rules, Ruff, mypy, Bandit, ESLint and tsc, with normalized diagnostics and completion checks. |
| AI providers/BYOK (§11, §24–25, §36, §43) | Gemini and free DeepSeek through official OpenCode are live-tested on invented examples; quota fallback, caching and persisted model metadata verified. Gemini's complete live validated-Apply workflow passed. Broader review quality remains open. Claude/Ollama are optional and unconfigured. |
| Verification, deduplication, confidence, priority and summary (§13–18) | Implemented with deterministic checks; no claim of complete semantic or exploit proof. |
| Web UI (§19–21, §31) | Real served build, component tests and browser smoke acceptance. Full accessibility, responsive matrix and outage/reconnect acceptance remain. |
| Generated fixes and isolated validation (§22–23) | Multi-file existing edits plus advertised test slots; actual Docker tests. Apply requires validated local proposals. |
| Repository rules, cache and persistence (§27–29) | Implemented. Production PostgreSQL; SQLite for local use. Cache keys include content/analyzer version. |
| Background work and progress (§30) | Persistent leased/fenced jobs, routed workers and SSE; Compose workflow/persistence tested. |
| Architecture and readability (§33–34) | Domain ports/composition root, focused adapters and small functions; strict types, complexity/docstring/style gates. Some cohesive older modules remain over the guideline's suggested size. |
| Tests and golden cases (§35–39) | Offline provider tests, adversarial/golden/integration/end-to-end contracts and coverage gates. These are not representative precision/recall measurements. |
| Security (§40) | Filtering/redaction, untrusted inputs, confined Apply, tenant checks and sandbox regressions. Trusted fix-worker daemon authority remains an operator boundary. |
| Observability/performance (§41–42) | Structured stage logs, metrics, updated synthetic size benchmarks. Sustained load and production capacity unmeasured. |
| Documentation (§48–52) | README, architecture, decisions, walkthrough and 14-day guide updated with current paths/limits. |
| CI/demo/release (§53–55) | Source is on GitHub; actual hosted Python/PostgreSQL, frontend and Docker/Compose jobs passed. The public demo and fresh-download browser/Apply acceptance passed on 20 October. V1 is complete within documented limits; see [SPEC_COMPLETION.md](SPEC_COMPLETION.md). |

The frontend tool list in §31 is recommended. Keeping React/TypeScript served by FastAPI
is a documented design choice, not a missing Next.js folder. Compiler-grade dynamic flow,
extra languages and V2 features are not needed to close V1.

## Ordered remaining work

Use [RELEASE_READINESS.md](RELEASE_READINESS.md) as the current acceptance list.
The basic real review/fix/Apply and GitHub integration work is implemented and tested;
its results should not stay listed as missing work.

The prior code revision's three hosted jobs passed. Keep CI passing on every release.

The local browser/queued-worker workflow with real AI and the configured bridge passed.

The public presentation task now has a runnable [guide](PUBLIC_DEMO.md), public sample templates, current labelled screenshots and a recurring Docker acceptance test. Keep the documented quickstart and hosted checks passing for releases. A supervised live GitHub demo still needs an approved reachable webhook endpoint.

Before an always-on public service, test durable HTTPS/webhook deployment, outages and
simultaneous pushes, backup/restore/upgrades, accessibility and sustained load/retention.
Broaden independent business-contract and real-project model evaluations. Existing
retries/leases/migrations and small-corpus successes are foundations, not production
capacity or general accuracy measurements. Rootless/remote Docker needs testing only
if chosen. Optional providers and compiler-grade V2 analysis are not V1 blockers.

Gemini and the free OpenCode route are configured. Ollama is optional. The test-only
GitHub App remains installed; Smee and the temporary notification gateway were removed
after the real test. New automatic notifications are currently disconnected by request.
A supervised GitHub demo needs an approved reachable endpoint; paid hosting is not
required just to run that demonstration. See [LOCAL_SETUP_AND_GITHUB.md](LOCAL_SETUP_AND_GITHUB.md).
## Supported limits to retain

Variable access covers ordinary module/global and known imported bindings. Local-variable
graphs, class fields, destructuring, re-exports, dynamic imports and complete value/taint
propagation remain partial; Python lambda/comprehension inner scopes are not guessed.
Missing graph edges cannot prove safety. See [GRAPH_ANALYSIS.md](GRAPH_ANALYSIS.md).

Generated proposals cannot create arbitrary source modules/directories or delete files.
Apply rolls back ordinary write errors, not power loss or a crash across filesystem/database
commits. Dependency installation belongs in trusted sandbox images. The demo's TypeScript
imports require their project dependencies for a clean baseline; an unchanged existing
diagnostic is not evidence a proposed Python edit introduced it.

Rootful Docker daemon access is powerful even in a non-root worker. Use the dedicated worker
boundary described in deployment docs. GitHub cannot atomically compare a PR head and post a
comment; the reviewed revision is identified. Secret filtering and analysis are bounded
detection mechanisms, not completeness guarantees.

## Live Gemini verification - 18 October 2026

Gemini 3.8 Flash is now configured and verified with invented examples. A complete
CLI review finished all eight stages, and the model's SQL-injection finding was
independently supported by local analysis. Its proposed parameterized query passed
a separate before/after Docker test: one existing test failed before, both passed
after. The saved fix remains unverified because the current policy requires an
already-passing baseline suite; Apply was not bypassed. No project patch was applied.

See [GEMINI_LIVE_TEST.md](GEMINI_LIVE_TEST.md) for evidence, usage and limits.
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

See [FREE_AI_VERIFICATION.md](FREE_AI_VERIFICATION.md) for the test matrix, explanation,
limitations and remaining integration work. Gemini's separate live results are in
[GEMINI_LIVE_TEST.md](GEMINI_LIVE_TEST.md).
