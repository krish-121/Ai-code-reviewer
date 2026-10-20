# Study guide: Sentinel in 14 days

A reading plan for understanding — and being able to explain and change — the whole system.
Plan on 1–2 hours a day. Every day has the same shape:

- **Goal** — what you should be able to explain at the end of the day.
- **Read** — files and functions, in reading order (links go to the code).
- **Run** — commands that show the code working; most are single test files.
- **Try** — a small change in a disposable copy, then undo only that exercise's changes.
  Keep existing development work; do not reset the entire working tree.
- **Check yourself** — questions to answer out loud, without looking.

For Windows/WSL prerequisites, complete commands and the distinction between offline,
Ollama and GitHub testing, start with [LOCAL_SETUP_AND_GITHUB.md](LOCAL_SETUP_AND_GITHUB.md).
Use [PUBLIC_DEMO.md](PUBLIC_DEMO.md) for the required Node/Docker setup. The guide below assumes that environment is activated. Set up once:

```bash
pip install -c requirements.lock -e ".[dev,postgres,analyzers]"
python demo/build_demo_repo.py /tmp/demo          # the demo repository with planted bugs
python scripts/seed_demo.py                       # a stored demo review (scripted AI replay)
python scripts/serve_demo.py                     # http://127.0.0.1:8820; isolated scripted demo
```

Keep [ARCHITECTURE.md](ARCHITECTURE.md) and [WALKTHROUGH.md](WALKTHROUGH.md) open; the
guide refers to them. Its last section, *How to change common things*, is the reference for
the "Try" exercises.

---

## Day 1 — Project architecture

**Goal.** Describe Sentinel in two minutes: what problem it solves, the parts, and how a
review flows through them.

**Read.**
- [README.md](../README.md) — what and why.
- [ARCHITECTURE.md](ARCHITECTURE.md) sections 1–3 (system, layers, pipeline).
- The package layout: [`src/sentinel/`](../src/sentinel/) — read just the one-line docstring
  in each `__init__.py`.
- [`bootstrap.py`](../src/sentinel/bootstrap.py) — the composition root: every concrete
  piece is chosen here.

**Run.**
```bash
cd /tmp/demo && sentinel review --range main..feature/search-and-reports --no-ai --details
pytest tests/unit/test_infrastructure.py -k depend -v     # the layering rules, as tests
```

**Try.** Add `import fastapi` at the top of `core/domain/models.py` and run the
architecture test above. Read the failure message, then undo.

**Check yourself.**
1. Which layer may import which? Why must `core/domain` stay free of FastAPI and GitHub?
2. What is a *port*? Name three and the concrete classes behind them.
3. Why does `bootstrap.py` exist instead of each module creating what it needs?

## Day 2 — Domain models

**Goal.** Know the data types every other part speaks: change sets, findings,
verification results, review results, code symbols, the graph.

**Read.**
- [`core/domain/models.py`](../src/sentinel/core/domain/models.py) — `ChangeSet`,
  `FileChange` (`added_lines`, `touches`), `Finding` (`location`, `is_deterministic`),
  `VerificationResult`, `PriorityScore`, `ReviewResult`, `StageRecord`.
- [`core/domain/code.py`](../src/sentinel/core/domain/code.py) — `FileSymbols`, `Symbol`,
  `CallSite`, `EndpointRef`, `DbOperation`.
- [`core/domain/ai.py`](../src/sentinel/core/domain/ai.py) — `AIFinding` and why it is
  *strict* (`extra="forbid"`).
- [`core/domain/ports.py`](../src/sentinel/core/domain/ports.py) and
  [`errors.py`](../src/sentinel/core/domain/errors.py).

**Run.** `sentinel review --range main..feature/search-and-reports --no-ai --format json | head -80`
inside `/tmp/demo` — the JSON is a serialized `ReviewResult`.

**Try.** In a Python shell, build a `Finding` with `confidence=1.5`. Read the validation
error. Then build an `AIFinding` with an extra field `"notes": "x"`.

**Check yourself.**
1. What is the difference between a finding's *severity* and its *confidence*? (spec §15)
2. What does `FindingSource.COMBINED` mean, and when does a finding get it?
3. Why are `AIFinding` and `Finding` two different classes?

## Day 3 — CLI → application layer

**Goal.** Trace a command from the terminal to the service that runs it, and know who owns
transactions.

**Read.**
- [`apps/cli/main.py`](../src/sentinel/apps/cli/main.py) — every command and where it lives.
- [`apps/cli/review_commands.py`](../src/sentinel/apps/cli/review_commands.py) — `review`,
  `_local_request`, `_review_local`.
- [`apps/cli/common.py`](../src/sentinel/apps/cli/common.py) — `fail`, exit codes.
- [`services/reviews.py`](../src/sentinel/services/reviews.py) — `ReviewService.create_local`,
  `run`, `_run_local`, `DBProgress`.
- [`services/workspaces.py`](../src/sentinel/services/workspaces.py) — `prepare_local`.
- [WALKTHROUGH.md](WALKTHROUGH.md) steps 1–2.

**Run.** `pytest tests/integration/test_cli.py -v`

**Try.** Add a `--quiet` flag to `review` that prints only the headline. Follow
*Add a CLI command* in the walkthrough for where things go.

**Check yourself.**
1. Why does the CLI call `create_local(..., enqueue=False)` but the API passes `True`?
2. When is the review run on a temporary export instead of your working tree?
3. What happens, step by step, when you run `sentinel review` outside a git repository?

## Day 4 — The diff engine

**Goal.** Explain how `git diff` text becomes a `ChangeSet`, and how files are filtered and
secrets redacted before anything else sees them.

**Read.**
- [`analysis/diff/git.py`](../src/sentinel/analysis/diff/git.py) — `staged_changeset`,
  `range_changeset` (why refs starting with `-` are rejected).
- [`analysis/diff/parser.py`](../src/sentinel/analysis/diff/parser.py) — `parse_unified_diff`,
  `_DiffParser.feed`, `_HunkCursor.consume`, `safe_path`.
- [`analysis/diff/filtering.py`](../src/sentinel/analysis/diff/filtering.py) —
  `filter_changeset`, `sensitive_file_reason`, `_skip_reason`.
- [`analysis/diff/secrets.py`](../src/sentinel/analysis/diff/secrets.py) — `scan_line`,
  `redact_line`, `shannon_entropy`.
- [`analysis/diff/injection.py`](../src/sentinel/analysis/diff/injection.py).

**Run.** `pytest tests/unit/test_diff_parser.py tests/unit/test_filtering_and_secrets.py -v`

**Try.** Add a secret rule for a made-up token format `acme_live_<32 hex>` and a test that
it is reported and redacted.

**Check yourself.**
1. Why is a `.env` file *dropped* while a key inside `config.py` is *redacted*?
2. Which line numbers does a context line get, and why do both sides matter?
3. Name two ways a malicious diff could try to escape the repository, and where each is
   stopped.

## Day 5 — AST analysis

**Goal.** Explain what a language analyzer extracts and why everything is reduced to
`FileSymbols`.

**Read.**
- [`analysis/ast/python_analyzer.py`](../src/sentinel/analysis/ast/python_analyzer.py) —
  `_Visitor` (`visit_ClassDef`, `_visit_function`, `_visit_body`, `_visit_loop`,
  `visit_Call`), `endpoints_from_decorator`, `PythonAnalyzer.analyze`.
- [`analysis/ast/python_sql.py`](../src/sentinel/analysis/ast/python_sql.py) — `sql_literal`,
  `db_operation_kind`.
- [`analysis/ast/typescript_analyzer.py`](../src/sentinel/analysis/ast/typescript_analyzer.py)
  and [`ts_extract.js`](../src/sentinel/analysis/ast/ts_extract.js);
  [`typescript_fallback.py`](../src/sentinel/analysis/ast/typescript_fallback.py).
- [`analysis/ast/registry.py`](../src/sentinel/analysis/ast/registry.py) — routing and caching.

**Run.** `pytest tests/unit/test_python_analyzer.py tests/unit/test_typescript_analyzer.py -v`

**Try.** Teach `endpoints_from_decorator` to recognise `@router.api_route("/x", methods=["PUT"])`
— then check: is it already handled? (Read `ROUTE_DECORATORS` and `_declared_methods`.)

**Check yourself.**
1. How does the visitor know a call happens inside a loop? Why is that useful later?
2. What does the regex fallback lose compared with the compiler, and how does the review
   summary tell the user?
3. Why is `loop_depth` reset when entering a function body?

## Day 6 — The code graph

Current exercise: follow [GRAPH_ANALYSIS.md](GRAPH_ANALYSIS.md), then run
`pytest tests/unit/test_graph_dependencies.py -v`. Explain the difference between reading
a global and reading a local with the same name; why endpoints include file/handler identity;
and why marking a projected node as changed must not mutate the full graph.

**Goal.** Explain how the graph is built and which questions it answers.

**Read.**
- [`core/domain/graph.py`](../src/sentinel/core/domain/graph.py) — `CodeGraph`:
  `add_edge`, `callers`, `path_from_entrypoint`, `tests_for`, `call_path`, `enclosing`.
- [`analysis/graph/builder.py`](../src/sentinel/analysis/graph/builder.py) — the passes in
  `GraphBuilder.build`.
- [`analysis/graph/resolution.py`](../src/sentinel/analysis/graph/resolution.py) —
  `resolve_imports`, `CallResolver.resolve`, `_by_receiver_name`.
- [ARCHITECTURE.md §4](ARCHITECTURE.md#4-code-graph).

**Run.**
```bash
pytest tests/unit/test_graph.py -v
sentinel graph /tmp/demo --symbol search_products     # callers, callees, entry path
```

**Try.** In the demo repository, rename the function `search` so its call becomes
ambiguous, rerun `sentinel graph`, and see which edges disappear. Explain why
"no edge" is the safe choice.

**Check yourself.**
1. Why does `path_from_entrypoint` search *backwards* from the target?
2. Why does `builder.py` need several passes instead of one loop?
3. Give an example of a call the resolver deliberately does not resolve.

## Day 7 — Context engine and static analysis

**Goal.** Explain how the review picks what the model sees, and how static tools are run
and normalised.

**Read.**
- [`analysis/graph/context.py`](../src/sentinel/analysis/graph/context.py) —
  `ContextEngine.build`, `changed_symbols`, `_candidates_for`, `_fit`.
- [`analysis/static/runner.py`](../src/sentinel/analysis/static/runner.py) —
  `StaticAnalysisRunner.run`, `_safe_run`, `default_analyzers`.
- [`analysis/static/base.py`](../src/sentinel/analysis/static/base.py) — `find_tool`,
  `scrubbed_env`, `run_tool`, `static_finding`.
- [`python_tools.py`](../src/sentinel/analysis/static/python_tools.py) (Ruff, mypy, Bandit),
  [`js_tools.py`](../src/sentinel/analysis/static/js_tools.py) (ESLint, tsc).
- Sentinel's own rules: [`python_rules.py`](../src/sentinel/analysis/static/python_rules.py),
  [`python_patterns.py`](../src/sentinel/analysis/static/python_patterns.py),
  [`js_rules.py`](../src/sentinel/analysis/static/js_rules.py).

**Run.** `pytest tests/unit/test_context_engine.py tests/unit/test_static_analysis.py -v`
and look at [BENCHMARKS.md](BENCHMARKS.md): why is the prompt the same size for every
repository?

**Try.** Add a built-in rule that flags `assert` statements in non-test files (follow
*Add one of Sentinel's own rules*).

**Check yourself.**
1. What are the context tiers, and which is dropped first when the budget runs out?
2. What does `trust_workspace=False` change, and why does it matter for pull requests?
3. Why does a crashing analyzer not fail the review?

## Day 8 — The AI provider abstraction

**Goal.** Explain how a prompt is built safely, how providers are called without SDKs, and
how bad responses are handled.

**Read.**
- [`core/review/ai_request.py`](../src/sentinel/core/review/ai_request.py) — `build_review_request`.
- [`ai/prompts/__init__.py`](../src/sentinel/ai/prompts/__init__.py) — `SYSTEM_REVIEW`,
  `_wrap`, `_neutralize`, `build_review_prompt`.
- [`ai/providers/base.py`](../src/sentinel/ai/providers/base.py) — `review`, `_structured`,
  `_post`, `_backoff`, `_http_error`, `extract_json`.
- [`ai/providers/http_providers.py`](../src/sentinel/ai/providers/http_providers.py) — the
  three `_complete` implementations.
- [`ai/providers/factory.py`](../src/sentinel/ai/providers/factory.py) and
  [`ai/schemas`](../src/sentinel/ai/schemas/__init__.py).
- [`core/findings/normalize.py`](../src/sentinel/core/findings/normalize.py).

**Run.** `pytest tests/unit/test_ai_providers.py -v` — every failure mode from spec §36 is a
test: malformed JSON, missing fields, rate limit, timeout, provider error, retry.

**Try.** Add a fake provider class in a test that answers with Markdown around the JSON and
check that `extract_json` still copes. Then make it answer invalid JSON twice and read the
error.

**Check yourself.**
1. Why is the nonce in the fencing tags needed? What would an attacker try without it?
2. Which errors are retried, which are reported as configuration errors, and why?
3. Why is the review response cached but the fix response not?

## Day 9 — Finding verification

**Goal.** Explain "AI proposes, deterministic systems verify" with a real example from the
demo, including a rejected claim.

**Read.**
- [`core/verification/engine.py`](../src/sentinel/core/verification/engine.py) —
  `VerificationEngine.verify`, `_decide`, `deterministic`, `apply_verification`, the
  threshold constants.
- [`core/verification/checks.py`](../src/sentinel/core/verification/checks.py) — all checks.
- [`analysis/static/probes/`](../src/sentinel/analysis/static/probes/) — `SqlInjectionProbe`
  (`sql.py`), `AsyncProbe` (`runtime.py`), `AuthOrderProbe` (`access.py`).
- Then the end of the pipeline: [`core/findings/dedup.py`](../src/sentinel/core/findings/dedup.py),
  [`prioritize.py`](../src/sentinel/core/findings/prioritize.py),
  [`core/review/summary.py`](../src/sentinel/core/review/summary.py).

**Run.**
```bash
pytest tests/unit/test_verification.py tests/golden -v
```
In the web UI, open the demo review's *Findings*, tick *Include suppressed*, and read why
each rejected claim was rejected.

**Try.** Write a probe for a new claim type, e.g. "unbounded `while True` loop without
`break`" (follow *Add a verification probe*), with one supporting and one contradicting test.

**Check yourself.**
1. What makes a contradiction *decisive*? Give two examples.
2. Why can a rejected AI claim never be merged with a real static finding?
3. Walk through the score for "SQL injection in `search_products`" using the checks shown in
   the UI.

## Day 10 — GitHub integration

**Goal.** Explain the webhook → job → review → comments flow, how comments are not
duplicated, and which permissions are needed.

**Read.**
- [`apps/api/routes/github.py`](../src/sentinel/apps/api/routes/github.py) — `github_webhook`.
- [`integrations/github/webhooks.py`](../src/sentinel/integrations/github/webhooks.py) —
  `verify_signature`, `parse_pull_request_event`.
- [`integrations/github/client.py`](../src/sentinel/integrations/github/client.py) —
  `GitHubAppAuth` (JWT → installation token, `MIN_PERMISSIONS`), `GitHubClient`,
  `download_tree`.
- [`services/reviews.py`](../src/sentinel/services/reviews.py) — `create_github`,
  `_run_github`, `publish`.
- [`integrations/github/publisher.py`](../src/sentinel/integrations/github/publisher.py) and
  [`render.py`](../src/sentinel/integrations/github/render.py).
- [ARCHITECTURE.md §7](ARCHITECTURE.md#7-github-workflow), [GITHUB_APP.md](GITHUB_APP.md).

**Run.** `pytest tests/unit/test_github.py tests/e2e/test_github_flow.py -v` — the end-to-end
test drives the real API, worker and pipeline against a fake GitHub.

**Try.** Change the summary comment's footer in `render.py`, run the e2e test, and see which
assertion protects the marker that makes updates idempotent.

**Check yourself.**
1. Why does the webhook handler return before the review runs?
2. How does the second push to a PR avoid re-posting the same inline comments?
3. Why is `issues: write` needed for a pull-request comment?

## Day 11 — Database and jobs

Current additions: read [DATABASE_MIGRATIONS.md](DATABASE_MIGRATIONS.md), then trace
`schema.initialize` versus `schema.upgrade` in
[`schema.py`](../src/sentinel/infrastructure/database/schema.py). Run
`pytest tests/integration/test_migrations.py tests/unit/test_validation_worker.py -v`.
Explain why startup refuses an old populated schema, why adoption is explicit, how leases
fence stale workers, and why fix jobs go to a different worker in Compose.

**Goal.** Explain the schema, tenancy, and how the job queue survives crashes without Redis.

**Read.**
- [`infrastructure/database/models.py`](../src/sentinel/infrastructure/database/models.py),
  [`session.py`](../src/sentinel/infrastructure/database/session.py),
  [`store.py`](../src/sentinel/infrastructure/database/store.py) (`review_for`,
  `finding_for`, `can_access`, `save_result`, `load_result`).
- [`infrastructure/queue/jobs.py`](../src/sentinel/infrastructure/queue/jobs.py) — `claim`,
  `heartbeat`, `fail`.
- [`apps/worker/main.py`](../src/sentinel/apps/worker/main.py) — `run_once`, `_heartbeat`.
- [`apps/api/dependencies.py`](../src/sentinel/apps/api/dependencies.py) and
  [`routes/reviews.py`](../src/sentinel/apps/api/routes/reviews.py) — `progress_events` (SSE).
- [ARCHITECTURE.md §8–9](ARCHITECTURE.md#8-data-model).

**Run.**
```bash
pytest tests/unit/test_store_and_queue.py tests/integration/test_api.py -v
# with a PostgreSQL you can throw away:
SENTINEL_TEST_DATABASE_URL=postgresql://user:pass@localhost/sentinel_test pytest -m postgres -v
```

**Try.** Kill a worker mid-review (start `sentinel worker`, queue a review from the UI,
press Ctrl-C) and watch another worker pick the job up after the lease expires (lower
`DEFAULT_LEASE_S` temporarily to see it quickly).

**Check yourself.**
1. What guarantees two workers never run the same job, on SQLite and on PostgreSQL?
2. How does the browser get live progress if the review runs in a different process?
3. Where exactly is tenancy enforced, and how is it tested?

## Day 12 — Frontend

**Goal.** Explain how the UI is structured, how it talks to the API, and how it is built
and served.

**Read.**
- [`web/src/main.tsx`](../web/src/main.tsx) → [`app/App.tsx`](../web/src/app/App.tsx) (routing,
  theme) → [`pages/ReviewPage.tsx`](../web/src/pages/ReviewPage.tsx) (tabs, live progress).
- [`web/src/lib/api.ts`](../web/src/lib/api.ts) (typed client, CSRF header, SSE),
  [`lib/hooks.ts`](../web/src/lib/hooks.ts) (`useQuery`, routing),
  [`lib/types.ts`](../web/src/lib/types.ts) (mirrors the API).
- [`findings/`](../web/src/findings/) — `FindingsTab`, `FindingDetailView`, `FixPanel`.
- [`review/ArchitectureTab.tsx`](../web/src/review/ArchitectureTab.tsx) and
  [`lib/graphLayout.ts`](../web/src/lib/graphLayout.ts) (layered layout, unit-tested).
- [`web/build.mjs`](../web/build.mjs) and [`apps/api/routes/web.py`](../src/sentinel/apps/api/routes/web.py).

**Run.**
```bash
cd web && npm ci && npm run lint && npm test && npm run build
```
Then reload the running `sentinel serve` page.

**Try.** Add a "Copy location" button to the finding header that copies `file:line`
(`navigator.clipboard.writeText`). Keep the component small; put it next to `FindingHeader`.

**Check yourself.**
1. Why does every state-changing request send `X-Sentinel-Client`?
2. How does the Findings tab decide which finding is selected?
3. Why is the built UI committed inside the Python package?

## Day 13 — Sandbox and fix engine

Read [MULTI_FILE_FIXES.md](MULTI_FILE_FIXES.md) and the scratch-transfer section of
[DEPLOYMENT.md](DEPLOYMENT.md). Run `pytest tests/unit/test_multi_file_fixes.py
tests/unit/test_sandbox_transfer.py -v`. Explain a fail-before/pass-after regression test,
why missing validators cannot prove a patch safe, which worker receives Docker access,
and what ordinary-error rollback does not guarantee about power loss.

**Goal.** Explain how a fix is generated, validated and applied without ever running
untrusted code on the host.

**Read.**
- [`core/fixes/engine.py`](../src/sentinel/core/fixes/engine.py) — `generate`, `_try_patch`,
  `validate`, `_checks_on_copies`, `_verdict`, `apply_fix`.
- [`core/fixes/validation.py`](../src/sentinel/core/fixes/validation.py) — `check_resolved`,
  `check_no_new_issues`, `check_tests`, `detect_test_command`.
- [`core/fixes/patch.py`](../src/sentinel/core/fixes/patch.py), [`scratch.py`](../src/sentinel/core/fixes/scratch.py).
- [`sandbox/runners.py`](../src/sentinel/sandbox/runners.py) — `DockerSandbox.command` (read
  each flag), `ProcessSandbox`.
- [`services/fixes.py`](../src/sentinel/services/fixes.py), [`Dockerfile.sandbox`](../Dockerfile.sandbox).

**Run.**
```bash
docker build -f Dockerfile.sandbox -t sentinel-sandbox .
pytest tests/unit/test_fix_engine.py tests/integration/test_sandbox.py -v
```
In the UI, open the demo's SQL-injection finding and read the validated fix's checks.

**Try.** Make a test fix that passes the static re-check but breaks a test, and confirm the
verdict is *failed* with the test output in the detail.

**Check yourself.**
1. Why search/replace edits instead of letting the model write files?
2. What does "tests already fail before the patch" protect against?
3. List the isolation properties of the Docker sandbox, and what the process sandbox lacks.

## Day 14 — The full system

**Goal.** Explain the whole system end to end, defend the design decisions, and know where
you would take it next.

**Read.**
- [WALKTHROUGH.md](WALKTHROUGH.md) top to bottom, opening each linked function.
- [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md).
- [ARCHITECTURE.md §10](ARCHITECTURE.md#10-security-boundaries) — the security table.
- [PROGRESS.md](../PROGRESS.md) — what is verified only with mocks, and what needs review.

**Run.** The full gate, as CI runs it:
```bash
ruff check src tests scripts tools/opencode_bridge
ruff format --check src tests scripts tools/opencode_bridge
mypy
mypy --strict tools/opencode_bridge
MYPYPATH=demo:scripts mypy --strict scripts/demo_support.py scripts/seed_demo.py scripts/serve_demo.py
pytest --cov=sentinel --cov-fail-under=80
coverage report --include="*/sentinel/core/*" --fail-under=90
cd web
npm run lint
npm test
npm run build
```

**Try.** Pick one recipe from *How to change common things* you have not done yet and do it
end to end, with tests.

**Check yourself.** Explain, without notes:
1. The life of `sentinel review --staged`, naming every stage.
2. The life of a pull request from webhook to inline comment.
3. Why the demo's `find_user` "SQL injection" never reaches the developer.
4. Three security threats specific to an AI code reviewer and how each is handled.
5. Two things you would build next and why (see spec §46 and the current [completion report](SPEC_COMPLETION.md), rather than historical gaps in PROGRESS.md).
