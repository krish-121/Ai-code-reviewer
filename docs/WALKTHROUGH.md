# Walkthrough: one review, from the command line to the output

This document follows a single `sentinel review --staged` through the code, in the order
it executes, and names the file and function at every step. Open the files side by side
as you read. Paths are relative to the repository root; `src/sentinel/` is the Python
package.

```
CLI command → application service → review orchestrator → diff parser → context engine
            → AI provider → finding verifier → output
```

At the end: [the pull-request path](#the-pull-request-path),
[the fix path](#the-fix-path), and **[How to change common things](#how-to-change-common-things)**.

> Tip: to watch it happen, build the demo repository and step through a review:
>
> ```bash
> python demo/build_demo_repo.py /tmp/demo && cd /tmp/demo
> # put `breakpoint()` as the first line of ReviewOrchestrator.review, then:
> sentinel review --range main..feature/search-and-reports --no-ai
> ```
>
> At the `(Pdb)` prompt, `n` runs the next line, `s` steps into a call, `p changeset` prints a
> variable and `c` continues.

---

## 1. The CLI command

**File:** [`src/sentinel/apps/cli/main.py`](../src/sentinel/apps/cli/main.py)

The `sentinel` executable is declared in `pyproject.toml` as
`sentinel.apps.cli.main:main`. `main.py` creates the Typer `app` and registers every
command; it is the table of contents of the CLI. `review` is implemented in
[`review_commands.py`](../src/sentinel/apps/cli/review_commands.py).

**Function:** `review_commands.review(...)` — one parameter per command-line option.

1. `load_cli_settings(provider=..., model=...)` ([`common.py`](../src/sentinel/apps/cli/common.py))
   reads settings: `~/.config/sentinel/config.toml`, then `SENTINEL_*` environment
   variables, then the flags (see `load_settings` in
   [`config.py`](../src/sentinel/core/configuration/config.py)).
2. `open_database(settings)` connects to the database (SQLite file by default). Empty
   databases are initialized through versioned migrations; existing databases must have a
   compatible schema. See [DATABASE_MIGRATIONS.md](DATABASE_MIGRATIONS.md).
3. `_local_request(...)` turns the flags into a
   [`LocalRequest`](../src/sentinel/services/workspaces.py): *what* to review
   (`mode="staged"`, the repository path).
4. `_review_local(...)` creates a `ReviewService`, calls `create_local`, then `run` inside a
   `LiveProgress` display.
5. `_print_result(...)` prints the result; `_reaches_threshold` implements `--fail-on`.

Expected errors (`SentinelError` and its subclasses, e.g. `GitError` when you are not in a
repository) are turned into a red message and an exit code by `fail()`.

## 2. The application service

**File:** [`src/sentinel/services/reviews.py`](../src/sentinel/services/reviews.py) —
class `ReviewService`

Services are the use cases shared by the CLI, the API and the worker. They own database
transactions; the engine below them never touches the database.

- **`ReviewService.create_local(user_id, request, enqueue=False)`** stores a `Review` row
  (status `queued`) through [`Store.create_review`](../src/sentinel/infrastructure/database/store.py).
  The CLI passes `enqueue=False` because it runs the review itself; the API passes `True`
  so a worker picks it up.
- **`ReviewService.run(review_id, progress)`** loads the request, wraps the progress
  listener in `DBProgress` (which writes every stage change to the review row — that is
  what the web UI's live progress reads), and calls `_run_local`.
- **`_run_local`** calls [`prepare_local(request)`](../src/sentinel/services/workspaces.py),
  a context manager that yields the change set and a *workspace* directory whose contents
  match the code being reviewed. For staged changes it calls
  [`staged_changeset`](../src/sentinel/analysis/diff/git.py), which runs
  `git diff --cached` and hands the text to the diff parser (step 4). If some of the staged
  files also have unstaged edits, the index is exported to a temporary directory so the
  analysers see exactly what is staged.
- It then loads `.sentinel.yml` ([`load_repo_config`](../src/sentinel/core/configuration/config.py)),
  builds an orchestrator with [`build_orchestrator`](../src/sentinel/bootstrap.py) — the
  *composition root*, the one place that chooses concrete analyzers, probes, the AI provider
  and the cache — and calls `orchestrator.review(...)`.
- Finally [`Store.save_result`](../src/sentinel/infrastructure/database/store.py) saves the
  status, summary, findings (surfaced and suppressed), tool runs, the architecture graph and
  a redacted snapshot of the source files the UI may display.

## 3. The review orchestrator

**File:** [`src/sentinel/core/review/orchestrator.py`](../src/sentinel/core/review/orchestrator.py)
— `ReviewOrchestrator.review(changeset, workspace, ...)`

`review` creates a [`PipelineState`](../src/sentinel/core/review/state.py) and runs eight
stage methods in order. Each runs inside `_stage(...)`, a context manager that marks the
stage running, times it, reports it to the progress listener, logs a structured line
(`stage finished review_id=… stage=… duration_ms=…`) and — if the stage raises — marks
*only that stage* failed so the review ends `PARTIAL` instead of crashing. `_final_status`
decides COMPLETED / PARTIAL / FAILED at the end.

| Method | What it does |
|---|---|
| `_parse_diff` | Records counts; the diff was already parsed (step 4). |
| `_filter_files` | [`filter_changeset`](../src/sentinel/analysis/diff/filtering.py): drops binary/generated/lock/minified/oversized files, **drops sensitive files** (`.env`, keys) and reports them, **redacts secrets** on every diff line, then [`scan_for_injection`](../src/sentinel/analysis/diff/injection.py) flags text aimed at an AI reviewer. |
| `_build_graph` | Reads code files ([`collect_sources`](../src/sentinel/core/review/workspace.py): changed files first), extracts symbols with the language registry, builds the graph (step 5). |
| `_extract_context` | The context engine (step 5). |
| `_static_analysis` | [`StaticAnalysisRunner.run`](../src/sentinel/analysis/static/runner.py) on the changed files. |
| `_ai_review` | The AI provider (step 6); skipped without a provider. |
| `_verify` | The verifier (step 7). |
| `_finalize` | Deduplicate, rank, select, summarise (step 8). |

## 4. The diff parser

**File:** [`src/sentinel/analysis/diff/parser.py`](../src/sentinel/analysis/diff/parser.py)
— `parse_unified_diff(text)`

The parser is a small line-by-line state machine (`_DiffParser.feed`):

- `diff --git a/x b/x` starts a new file (`_FileBuilder`);
- `---`/`+++` headers set old/new paths (`/dev/null` means added or deleted);
- `new file mode`, `deleted file mode`, `rename from/to`, `Binary files …` set the change
  type (`_file_metadata`);
- `@@ -a,b +c,d @@` starts a hunk; `_HunkCursor.consume` then reads `+`, `-` and context
  lines, numbering each one on the old and new side.

Every path goes through `safe_path`, which rejects absolute paths and `..` — diff text can
come from an untrusted pull request. The result is a
[`ChangeSet`](../src/sentinel/core/domain/models.py) of `FileChange`s, each with `Hunk`s of
`DiffLine`s. `FileChange.added_lines()` and `touches(start, end)` are used everywhere to ask
"did this change touch line N?".

## 5. The code graph and the context engine

For the current file/module/variable passes and a constant-to-consumer example, read
[GRAPH_ANALYSIS.md](GRAPH_ANALYSIS.md). This includes lexical binding, cache versioning,
independent UI subgraphs and the exact boundaries of variable analysis.

**Language analyzers.** [`LanguageRegistry.analyze`](../src/sentinel/analysis/ast/registry.py)
routes each file to its analyzer by extension and caches results by content hash:

- [`PythonAnalyzer.analyze`](../src/sentinel/analysis/ast/python_analyzer.py) walks the
  standard-library `ast` with `_Visitor`: symbols with spans, imports, call sites (with
  "inside a loop" and "awaited" flags), HTTP endpoints from decorators
  (`endpoints_from_decorator`) and database operations
  ([`db_operation_kind`](../src/sentinel/analysis/ast/python_sql.py)).
- [`TypeScriptAnalyzer.analyze_many`](../src/sentinel/analysis/ast/typescript_analyzer.py)
  sends all TS/JS files to one Node process running
  [`ts_extract.js`](../src/sentinel/analysis/ast/ts_extract.js), which uses the TypeScript
  compiler's parser; without Node it falls back to
  [`regex_extract`](../src/sentinel/analysis/ast/typescript_fallback.py).

Both produce [`FileSymbols`](../src/sentinel/core/domain/code.py).

**Graph.** [`build_graph`](../src/sentinel/analysis/graph/builder.py) runs `GraphBuilder`'s
passes: index module names → add file and symbol nodes → resolve imports → inheritance →
endpoints, calls and database edges. Turning `self.repo.find(...)` into an edge to
`UserRepo.find` is the job of [`CallResolver.resolve`](../src/sentinel/analysis/graph/resolution.py).

**Context.** [`ContextEngine.build`](../src/sentinel/analysis/graph/context.py):

1. `changed_symbols` — the functions/classes containing changed lines (blank and comment
   lines ignored);
2. `_candidates_for` each of them — the changed code (tier 0), callers around the call
   site, callees, tests, the entry path (`GET /search → search() → search_products()`) and
   data access, each as a `ContextBlock` with a reason;
3. `_fit` — keeps blocks in priority order until `max_chars`, skipping code another block
   already covers;
4. `_redact` — redacts secrets in the chosen blocks again (defence in depth);
5. [`architecture_subgraph`](../src/sentinel/analysis/graph/architecture.py) — the small
   graph the web UI draws.

## 6. The AI provider

**Building the request.** [`build_review_request`](../src/sentinel/core/review/ai_request.py)
assembles a [`ReviewRequest`](../src/sentinel/core/domain/ai.py): the size-capped diff
(`render_diff_for_prompt`), the context blocks, up to 40 static-analysis hints and the
enabled categories.

**The port.** The orchestrator only knows the `AIProvider` protocol in
[`ports.py`](../src/sentinel/core/domain/ports.py). The concrete object was created by
[`create_provider`](../src/sentinel/ai/providers/factory.py) from `settings.provider`.

**The call.** [`HTTPProvider.review`](../src/sentinel/ai/providers/base.py):

1. [`build_review_prompt`](../src/sentinel/ai/prompts/__init__.py) — rules and the JSON
   schema go in the system prompt; the diff and context are wrapped in
   `<untrusted_diff nonce="…">` tags (`_wrap`), anything that looks like those tags inside
   the code is neutralised (`_neutralize`), and the whole prompt is redacted once more.
2. A cache lookup keyed by the prompt's content (`content_key`).
3. `_structured(...)` → `_complete(...)` — implemented per provider in
   [`http_providers.py`](../src/sentinel/ai/providers/http_providers.py) (e.g.
   `ClaudeProvider._complete` forces a tool call so the answer is JSON) → `_post(...)`,
   which applies the retry policy (backoff with `Retry-After`, one retry on timeout, clear
   errors for bad keys).
4. `extract_json` + `AIReviewPayload.model_validate` — strict validation. If it fails, the
   validation errors are sent back once (`correction_message`) and the model tries again.

**Normalising.** Back in the orchestrator,
[`normalize_ai_findings`](../src/sentinel/core/findings/normalize.py) converts each
`AIFinding` into a domain `Finding` (source `ai`), matching file paths to real files and
deriving tags such as `sql-injection` from the text (`derive_tags`).

### 6.1 Automatic DeepSeek fallback when Gemini reaches its limit

The complete beginner setup is in [FREE_AI_FALLBACK.md](FREE_AI_FALLBACK.md).
The important flow is:

```text
Review text -> Gemini -> answer -> normal verification
                 |
                 +-> HTTP 429 (quota/rate limit)
                          |
                          v
                 local bridge -> official OpenCode -> free DeepSeek
                          |
                          v
                 strict JSON -> normal verification -> saved review
```

**Why a wrapper?** The engine already understands `AIProvider`. The factory wraps
the normal Gemini provider in `FallbackProvider` rather than adding vendor branches
to the review engine. A successful Gemini response stays with Gemini. Only an explicit
quota error can switch; a wrong key, refusal or different error stays visible.

**Why a waiting period?** After a quota error, the wrapper records a cooldown in the
cache: normally five minutes, extended by `Retry-After` up to a day. New provider
objects can reuse that state. After it expires the next request tries Gemini again.
Identical requests can reuse a cached DeepSeek answer too, saving more free quota.

**Why install OpenCode?** Its direct free HTTP endpoint rejected Sentinel. The supported
route uses the actual OpenCode application. DeepSeek itself stays online: no AI model
weights are downloaded. The small bridge gives Sentinel a normal HTTP connection to
that application while keeping it inside Docker.

**Why a separate password?** The bridge generates a local token so other callers cannot
use it freely. It is saved privately outside the repository, just like runtime settings.
It is unrelated to a paid service account. The Google key goes only to Google, and the
bridge token is removed from its child OpenCode environment. No project folder or Docker
control socket is shared into the bridge. Review/API workers still do not control Docker.

**Why approval rather than disabling tools?** The free gateway returned a misleading
403 when all tools were denied. In the working mode tools require approval; the
noninteractive CLI automatically rejects requests. A live command diagnostic was denied
and created no file. The bridge additionally rejects any response containing tool events.

The bridge serializes requests, caps input/output, sets a 75-second deadline and removes
each temporary session. Only the approved free DeepSeek ID is accepted. GLM is excluded
after two service failures. The returned text passes the same schema, repair, claim
verification and fix-validation rules as the existing providers. The saved review records
the actual winner and the reason for switching. Both services failing leaves local results
with an incomplete AI stage, rather than a false success.

Follow the source in this order:

1. [`config.py`](../src/sentinel/core/configuration/config.py): opt-in, private token and cooldown.
2. [`factory.py`](../src/sentinel/ai/providers/factory.py): builds Gemini and DeepSeek adapters.
3. [`fallback.py`](../src/sentinel/ai/providers/fallback.py): recognizes quota exhaustion and chooses.
4. [`opencode.py`](../src/sentinel/ai/providers/opencode.py): sends the existing prompt to the bridge.
5. [`server.py`](../tools/opencode_bridge/server.py): authenticates and validates the narrow local API.
6. [`runner.py`](../tools/opencode_bridge/runner.py): runs official OpenCode inside Docker.
7. [`opencode_bridge.py`](../scripts/opencode_bridge.py): trusted start/stop helper.

Start with `python scripts/opencode_bridge.py start --build`, then enable
`sentinel config set free_fallback true` with Gemini selected. The normal review command
does the rest. See [live verification](DEEPSEEK_FALLBACK_VERIFICATION.md) for the actual
Gemini-first review, controlled quota switch with real DeepSeek, cache check and limits.

## 7. The finding verifier

**Files:** [`core/verification/engine.py`](../src/sentinel/core/verification/engine.py),
[`checks.py`](../src/sentinel/core/verification/checks.py),
[`analysis/static/probes/`](../src/sentinel/analysis/static/probes/)

`_verify` builds a `VerificationContext` (graph, sources, change set, deterministic
findings, symbols). Deterministic findings get `VerificationEngine.deterministic` — they
are proven by the rule that produced them. Every AI finding goes through
**`VerificationEngine.verify`**:

1. every verifier's `check(finding, ctx)` runs — the generic checks (`LocationCheck`,
   `ChangeRelevanceCheck`, `SymbolEvidenceCheck`, `CallPathCheck`, `ReachabilityCheck`,
   `StaticCorroborationCheck`, `TestClaimCheck`, `StyleOnlyCheck`) and the probes
   (`SqlInjectionProbe`, `AsyncProbe`, `NPlusOneProbe`, …). A check that crashes is
   recorded, not raised.
2. `_decide` combines them: a *decisive* contradiction rejects the claim; otherwise a
   weighted score plus "is there strong independent support?" gives SUPPORTED, LIKELY,
   UNCERTAIN or REJECTED.
3. `apply_verification` writes the result onto the finding and blends the model's
   confidence with the evidence.

Example (the demo's planted false positive): the model claims `find_user` has SQL
injection. `SqlInjectionProbe.check` finds the `execute(...)` call at the cited lines,
sees a constant SQL string with `?` placeholders and a separate parameter tuple
(`is_parameterized`), and returns a *decisive* contradiction: "the query is parameterized".
The claim is rejected and appears in the summary as a rejected claim, not as an issue.

## 8. Finalising and the output

`_finalize` (orchestrator):

- `_annotate` — enclosing symbol, "on changed lines?", tags, and a stable
  [`fingerprint`](../src/sentinel/core/findings/dedup.py) (file + category + concept +
  symbol, so it survives line shifts);
- [`deduplicate`](../src/sentinel/core/findings/dedup.py) — union-find over findings that
  overlap and share a concept; Ruff's S608, the built-in rule and the AI claim about the
  same SQL injection become one finding with three origins (`merge`);
- [`select`](../src/sentinel/core/findings/prioritize.py) — `score` (severity × confidence ×
  reachability × change relevance × verification, with a written explanation), then
  suppression with a reason, then the display budget;
- [`build_summary`](../src/sentinel/core/review/summary.py) — risk, headline, what changed,
  what was verified, what remains uncertain, all derived from the evidence;
- the architecture subgraph and [`snapshot_sources`](../src/sentinel/core/review/workspace.py)
  (redacted file copies for the UI).

**Output.** Back in the CLI, [`render_review`](../src/sentinel/apps/cli/render.py) prints
the summary panel (`render_summary`) and each finding (`render_finding`): location, code
snippet, verification checks with `--details`. `--format json` prints the
`ReviewResult` model; `--format markdown` prints the same comment GitHub would get
([`summary_comment`](../src/sentinel/integrations/github/render.py)).

---

## The pull-request path

The source repository is [krish-121/Ai-code-reviewer](https://github.com/krish-121/Ai-code-reviewer).
[Hosted CI](https://github.com/krish-121/Ai-code-reviewer/actions/runs/39141482827) has passed Python/PostgreSQL, frontend and Docker/Compose checks.
Pushing Sentinel's implementation there hosts the code and triggers CI. The reviewing
bot is now separately installed on the private `sentinel-integration-demo` test repo.
[Its real PR](https://github.com/krish-121/sentinel-integration-demo/pull/1) completed signed
delivery → Gemini analysis → database → authenticated UI → bot summary/inline publication.
Actual redelivery reused the review; a corrected second push updated the same summary.
See [GITHUB_LIVE_TEST.md](GITHUB_LIVE_TEST.md) for the step-by-step learning guide and
the precise evidence; [GITHUB_UPLOAD.md](GITHUB_UPLOAD.md) explains source publication.

Why the extra pieces? The **App** is permission and bot identity; **Gemini** is the model;
the **webhook** tells Sentinel a PR changed; the **worker** performs the slow review. A
temporary Cloudflare address lets GitHub contact this computer. A separate
[`webhook gateway`](../scripts/github_webhook_gateway.py) exposes only that notification
route, keeping the dashboard/API private. The existing signature check authenticates
every notification. Private App settings use the same normal configuration writer as
the provider settings; `github_webhook_secret` is masked and prompted without echo.
Installation ownership links reviews to a non-admin user so another user's API requests
return 404. Closing local processes stops new delivery, but saved reviews remain.



1. GitHub calls `POST /api/github/webhook`:
   [`github_webhook`](../src/sentinel/apps/api/routes/github.py) verifies the signature
   ([`verify_signature`](../src/sentinel/integrations/github/webhooks.py)), parses the event
   ([`parse_pull_request_event`](../src/sentinel/integrations/github/webhooks.py)) and calls
   `ReviewService.create_github`, which stores the review and enqueues a `review` job. The
   request returns `202` immediately.
2. A [`Worker`](../src/sentinel/apps/worker/main.py) (`run_forever` → `run_once`) claims
   the job ([`jobs.claim`](../src/sentinel/infrastructure/queue/jobs.py)), starts a
   heartbeat thread, and calls `ReviewService.run`.
3. `ReviewService._run_github` fetches the PR, its diff and a tarball of the head commit
   ([`GitHubClient`](../src/sentinel/integrations/github/client.py)), and builds the
   orchestrator with `trusted_workspace=False`: nothing from the PR's repository is executed.
4. After saving, `run` enqueues a `publish` job;
   [`ReviewService.publish`](../src/sentinel/services/reviews.py) →
   [`GitHubPublisher.publish`](../src/sentinel/integrations/github/publisher.py) updates
   the summary comment and posts inline comments for findings whose fingerprint is not
   already on the PR.

## The fix path

**Multilingual quality checkpoint — 19 October 2026:** 15 controlled examples
under neutral project names: nine known bugs detected, six correct changes without
warnings, and nine final real-model fixes validated/applied to disposable examples with
independent held-out Docker checks. The final round used free DeepSeek; the initial
round naturally switched from Gemini on a real quota error. This is a small-corpus
result, not a general perfect-accuracy claim. See [QUALITY_EVALUATION.md](QUALITY_EVALUATION.md).


**Live example completed 18 October 2026:** real Gemini review → generated SQL fix
and security test → all seven validation checks passed → normal Apply → three tests
passed. The saved fix is `applied` and the finding is `fixed`. The normal
`sentinel-sandbox:latest` image and private `sandbox_transport=copy` setting are now
configured. See [LIVE_FIX_WORKFLOW.md](LIVE_FIX_WORKFLOW.md) for the beginner step-by-step
explanation, actual IDs, source trace and acceptance limits.

1. UI: *Generate fix* → `POST /api/findings/{id}/fix`
   ([`request_fix`](../src/sentinel/apps/api/routes/findings.py)) creates a `FixAttempt` and
   a `fix` job. (CLI: `sentinel fix F-…`, [`fix_command.py`](../src/sentinel/apps/cli/fix_command.py).)
2. The fix worker calls [`FixService.run`](../src/sentinel/services/fixes.py), builds a
   [`FixEngine`](../src/sentinel/core/fixes/engine.py) and calls `generate`. The engine
   builds bounded context with [`fix_context`](../src/sentinel/core/fixes/context.py),
   requests coordinated edits, and applies them to a scratch copy through
   [`apply_edits`](../src/sentinel/core/fixes/patch.py). Existing files and advertised new
   regression-test slots are permitted; arbitrary new source files and deletions are not.
   [`validation.py`](../src/sentinel/core/fixes/validation.py) compares before/after
   diagnostics and test results; [`regression.py`](../src/sentinel/core/fixes/regression.py)
   checks that a new regression test fails before and passes after. Pytest and Node TAP
   test-case failures are recognized; failed test loading, cancellation and timeouts are
   not resolution evidence. A changed target and this regression can supply explicitly
   labelled `test-backed` resolution when static rules cannot confirm it. Failed static
   checks cannot be overridden; every other required check must still pass. Executable validators
   and tests run in Docker. An unavailable or incomplete check cannot establish validation.
   See [MULTI_FILE_FIXES.md](MULTI_FILE_FIXES.md) for the complete sequence.
3. *Apply* → `POST /api/fixes/{id}/apply` → `FixService.apply` →
   [`apply_fix`](../src/sentinel/core/fixes/engine.py) delegates confined writes to
   [`apply.py`](../src/sentinel/core/fixes/apply.py). It requires a validated verdict, unchanged
   source hashes and absent new-file destinations. Ordinary write errors roll back;
   power-loss/crash atomicity across multiple files is not guaranteed.

In Compose, [`docker-compose.yml`](../docker-compose.yml) routes review/publication jobs
to one worker and fixes to a separate Docker-capable worker. Only the latter has daemon
access. [`sandbox.launch`](../src/sentinel/sandbox/launch.py) extracts bounded scratch input
into container tmpfs; generated code never gets that daemon socket. Read
[DEPLOYMENT.md](DEPLOYMENT.md) before operating the stack.

For local WSL with Windows Docker Desktop, `sentinel config set sandbox_transport copy`
saves this transfer method. An environment variable is not needed for each new terminal.
Build the trusted image first with
`docker build -f Dockerfile.sandbox -t sentinel-sandbox:latest .`.
This image contains test/checking tools, not AI model weights. It runs the proposed code
with networking disabled. The separate OpenCode bridge described in section 6.1 uses
internet access to request an AI answer and has no project mount. One obtains a proposal;
the other checks it on a temporary copy.

---

## How to change common things

Each recipe lists the exact files to edit, in order. After any change run
`ruff check src tests && mypy && pytest` (and `npm run lint && npm test` in `web/` for UI
changes).

### Add a static analyzer (an external tool)

1. Write a class with `name`, `languages`, `is_available()` and `run(workspace, files)`
   (the `StaticAnalyzer` protocol in [`ports.py`](../src/sentinel/core/domain/ports.py)).
   Copy the shape of `RuffAnalyzer` in
   [`python_tools.py`](../src/sentinel/analysis/static/python_tools.py) or
   `ESLintAnalyzer` in [`js_tools.py`](../src/sentinel/analysis/static/js_tools.py): use
   `find_tool` (respect `trust_workspace`), `run_tool` (timeout + scrubbed environment),
   `static_finding` (consistent findings) and `run_record`.
2. Map the tool's rule ids to category/severity/tags (like `RUFF_RULES`).
3. Register it in `default_analyzers` in
   [`runner.py`](../src/sentinel/analysis/static/runner.py).
4. Test the output parser on recorded output in
   [`tests/unit/test_static_analysis.py`](../tests/unit/test_static_analysis.py), plus a
   real run guarded by `skipif(shutil.which(...) is None)`.

### Add one of Sentinel's own rules

- Python: add a `_check_<rule>` method to `PythonRules` in
  [`python_rules.py`](../src/sentinel/analysis/static/python_rules.py) and call it from
  `visit_Call` (or the relevant `visit_*`). Put reusable pattern recognition in
  [`python_patterns.py`](../src/sentinel/analysis/static/python_patterns.py) so a probe can
  use it too.
- JavaScript/TypeScript: add a `JsRule` to `JS_RULES` in
  [`js_rules.py`](../src/sentinel/analysis/static/js_rules.py).
- Add a case to [`tests/unit/test_static_analysis.py`](../tests/unit/test_static_analysis.py).

### Add a verification probe

1. Write a class with `name` and `check(finding, ctx) -> VerificationCheck | None` in the
   matching module of [`probes/`](../src/sentinel/analysis/static/probes/)
   (`sql.py`, `runtime.py`, `access.py`). Return `None` when the finding is not about your
   topic (check `finding.tags`). Use `result(...)` and the named weights from
   [`common.py`](../src/sentinel/analysis/static/probes/common.py); use `decisive=True`
   only when the code *proves* the claim wrong.
2. Add it to `default_probes()` in [`probes/__init__.py`](../src/sentinel/analysis/static/probes/__init__.py).
3. Test both directions (a true claim supported, a false claim rejected) in
   [`tests/unit/test_verification.py`](../tests/unit/test_verification.py).

### Add an AI provider

1. Subclass `HTTPProvider` in
   [`http_providers.py`](../src/sentinel/ai/providers/http_providers.py): set `name` and
   `default_base_url`, implement `_complete(system, messages, schema, tool)` — build the
   vendor's request, call `self._post(path, payload, headers)`, return a `Completion` with
   the reply text (JSON) and token usage. Retries, validation, caching and repair are
   inherited.
2. Register it in `PROVIDERS` in [`factory.py`](../src/sentinel/ai/providers/factory.py)
   (and in `NEEDS_KEY` if it needs a key).
3. Add its key variables to `KEY_ENV_VARS`, a default model to `DEFAULT_MODELS`, and the key
   field to `Settings` in [`config.py`](../src/sentinel/core/configuration/config.py).
4. Test the wire format with `httpx.MockTransport` in
   [`tests/unit/test_ai_providers.py`](../tests/unit/test_ai_providers.py) (copy
   `test_gemini_response_and_wire_format`).

### Add a new finding type

*A new kind of problem within an existing category* (e.g. "open redirect"):

1. Add a tag and its regex to `TAG_PATTERNS` in
   [`normalize.py`](../src/sentinel/core/findings/normalize.py) so AI findings get tagged.
2. Detect it deterministically: a rule (see above) that sets the same tag.
3. Verify AI claims about it: a probe (see above).
4. Let fixes be re-checked: map the tag to its rule ids in `RULES_FOR_TAG` in
   [`validation.py`](../src/sentinel/core/fixes/validation.py).

*A new category* (e.g. `accessibility`): add it to `Category` in
[`models.py`](../src/sentinel/core/domain/models.py), describe it in `CATEGORY_GUIDE` in
[`prompts`](../src/sentinel/ai/prompts/__init__.py), decide whether it is on by default in
`DEFAULT_CATEGORIES` ([`config.py`](../src/sentinel/core/configuration/config.py)), and add
it to the `Category` type in [`web/src/lib/types.ts`](../web/src/lib/types.ts).

### Add a language

1. Write a `LanguageAnalyzer` (`language`, `extensions`, `analyze(path, source) ->
   FileSymbols`) next to [`python_analyzer.py`](../src/sentinel/analysis/ast/python_analyzer.py).
   The graph only sees `FileSymbols`, so nothing downstream changes.
2. Register it in `default_registry` ([`registry.py`](../src/sentinel/analysis/ast/registry.py)).
3. Add the `Language` value ([`models.py`](../src/sentinel/core/domain/models.py)), its
   extensions to `EXTENSION_LANGUAGE` ([`parser.py`](../src/sentinel/analysis/diff/parser.py))
   and `SOURCE_EXTENSIONS` ([`orchestrator.py`](../src/sentinel/core/review/orchestrator.py)),
   and import/module resolution for it in
   [`resolution.py`](../src/sentinel/analysis/graph/resolution.py).

### Add a pipeline stage

1. Add a `StageName` and its label in `STAGE_LABELS` ([`models.py`](../src/sentinel/core/domain/models.py)).
2. Add any intermediate results it produces to `PipelineState` ([`state.py`](../src/sentinel/core/review/state.py)).
3. Write a `_<stage>(self, state, record)` method in `ReviewOrchestrator` and add it to the
   `stages` list in `review` ([`orchestrator.py`](../src/sentinel/core/review/orchestrator.py)).
   Set `record.detail` and `record.metrics`; raise `StageFailedError` for expected failures.
4. Add the label to `LABELS` in [`web/src/review/Pipeline.tsx`](../web/src/review/Pipeline.tsx).

### Add a setting or a `.sentinel.yml` option

- Per repository: add a field to the right section model (`ReviewSection`,
  `StaticSection`, `FixSection` or `RepoConfig`) in
  [`config.py`](../src/sentinel/core/configuration/config.py); unknown keys are rejected, so
  the field *is* the documentation. Update `REPO_CONFIG_TEMPLATE` in
  [`config_commands.py`](../src/sentinel/apps/cli/config_commands.py).
- Per machine: add a field to `Settings`, its environment variable to `_ENV_MAP`, and
  (if users may set it with `sentinel config set`) to `_WRITABLE_KEYS`.

### Change how findings are ranked or how many are shown

- Weights: `SEVERITY_WEIGHT`, `REACHABILITY_WEIGHT`, `VERIFICATION_WEIGHT` and
  `change_relevance` in [`prioritize.py`](../src/sentinel/core/findings/prioritize.py).
- What is suppressed: `_suppression_reason` (same file).
- How many: `review.max_findings` in `.sentinel.yml`.
- Verification thresholds: the constants at the top of
  [`engine.py`](../src/sentinel/core/verification/engine.py).

### Change the prompt

[`src/sentinel/ai/prompts/__init__.py`](../src/sentinel/ai/prompts/__init__.py):
`SYSTEM_REVIEW` (rules), `CATEGORY_GUIDE`, and `build_review_prompt`. Keep repository
content inside `_wrap(...)`. The expected JSON shape lives in `AIFinding` /
`AIReviewPayload` in [`ai.py`](../src/sentinel/core/domain/ai.py); the schema sent to the
model is generated from it. Run the golden tests afterwards.

### Add an API endpoint (and use it in the UI)

1. Add a route function to the matching module in
   [`apps/api/routes/`](../src/sentinel/apps/api/routes/) (or a new module registered in
   `API_ROUTERS` in [`routes/__init__.py`](../src/sentinel/apps/api/routes/__init__.py)).
   Take `SessionDep` / `UserDep` / `ContextDep` from
   [`dependencies.py`](../src/sentinel/apps/api/dependencies.py), look rows up with the
   `*_or_404` helpers (tenancy), add `dependencies=MUTATING` if it changes state, and shape
   the JSON in [`serializers.py`](../src/sentinel/apps/api/serializers.py).
2. Add the TypeScript type to [`web/src/lib/types.ts`](../web/src/lib/types.ts) and a
   function to `api` in [`web/src/lib/api.ts`](../web/src/lib/api.ts).
3. Test it in [`tests/integration/test_api.py`](../tests/integration/test_api.py).

### Add a CLI command

Write a function with Typer-annotated parameters and a docstring (it becomes `--help`) in
the matching `*_commands.py` module of [`apps/cli/`](../src/sentinel/apps/cli/), use
`load_cli_settings`, `open_database` and `fail` from
[`common.py`](../src/sentinel/apps/cli/common.py), and register it in
[`main.py`](../src/sentinel/apps/cli/main.py). Test with Typer's `CliRunner` in
[`tests/integration/test_cli.py`](../tests/integration/test_cli.py).

### Add a golden regression case

Create `tests/golden/cases/<name>/` with `base/` (the code before), `change/` (files
overlaid and staged), optionally `ai.json` (scripted model findings — include a wrong one)
and `expected.yaml` (`risk`, `surfaced`, `suppressed`; see
[`sql_injection/expected.yaml`](../tests/golden/cases/sql_injection/expected.yaml)).
[`test_golden.py`](../tests/golden/test_golden.py) picks it up automatically.

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

## Learning to measure review and fix quality

Start with [the small corpus](../evals/review_quality/README.md). Its preparation helper
creates a fresh Git repository and stages a real source change, keeping the answer key
and held-out tests outside the model's input. Optional `--check` proves fixture truth in
Docker without calling an AI. Then normal `sentinel review --staged` measures the actual
configured pipeline. Compare explanations with contracts; a high confidence score is
not a measured probability. Record false alarms, missed bugs and duplicates separately.

For fixes distinguish existing tests (preserve working behaviour), the same new test
failing before/passing after (reproduce a behaviour change), and independent held-out
checks (challenge the model's proposal with tests it never saw). Passing old tests alone
does not answer all three. All example code executes in Docker.

Trace normalization/dedup through `core/findings/normalize.py` and `dedup.py`, and fix
evidence through `core/fixes/engine.py` and `regression.py`. The mutable-default concept
now merges Ruff and AI wording without lowering similarity thresholds. Node output and
test-backed resolution have focused regressions; missing imports, incomplete/failed
checks and stale files still cannot reach Apply. Empty reviews say no code was assessed.
Full evidence, original failures and boundaries: [QUALITY_EVALUATION.md](QUALITY_EVALUATION.md).

## Following a change across several files

The [multi-file quality evaluation](MULTIFILE_QUALITY_EVALUATION.md) adds nine applications
to the learning corpus. Read an entry point first, then its service, then its shared
helper/repository and data model. Ask what each caller expects and what each callee
actually returns. Examples: minor currency units must stay consistent across pricing
and receipts; a failed background job must reach the caller; an organization filter
must survive the service-to-repository boundary.

A new context repair lives in
[`analysis/graph/import_context.py`](../src/sentinel/analysis/graph/import_context.py).
Previously a model used only in a type annotation was often absent from the prompt:
it is not a function call, so callee selection did not find it. The helper follows
resolved repository import edges and exact named imports, including aliases, to add
class/data definitions. It does not guess from an unrelated file with the same name.
The ordinary context window, character budget, deduplication and secret redaction
still apply. Wildcard/namespace/external imports are not expanded into whole projects.

One actual clean Decimal refactor received a warning assuming fractional prices that
this application did not support. The original review is retained. We supplied its
missing cart definition and clarified that review claims need a concrete supported
failure, then repeated the model experiment. Read the report for the observed result;
a prompt instruction is not a mathematical guarantee against false alarms.

Also distinguish context from edits. `FixRequest.files` includes related source to help
the model reason, while `apply_edits` returns only touched files. The fix engine's
target-change check must require the cited file to be present in that patch and its
contents to differ. Looking up an omitted file with `dict.get` returns `None`; comparing
that with the original text had incorrectly counted a helper-only edit as a target edit.
Focused tests now keep both an omitted target and an explicit no-op target unverified.
All other analysis, old/new tests, source-hash and Apply checks remain in force.

Correct patches can still remain unverified when only a related helper changes or the
model omits a reproducing regression. Inspect that evidence; never change a source
comment just to pass the target-change check. Only validated proposals reach normal
Apply, and the independent checks in this evaluation are an extra challenge, not AI
generation feedback.

### A review explanation and a passing test can both be incomplete

The wider experiment found two more boundaries. An opaque JavaScript result property
is not a declared repository function: the symbol verifier now leaves such unresolved
references neutral, while invented free function calls still contradict evidence. Read
[`symbol_evidence.py`](../src/sentinel/core/verification/symbol_evidence.py) to follow
that distinction. A captured finding was replayed against its original source snapshot,
without another AI call, so the report separates model output from verifier changes.

Fix requests now also carry bounded original-review history. Trace `Review.changeset`
through `FixService.run`, `FixEngine.generate`,
[`review_context.py`](../src/sentinel/core/fixes/review_context.py), `FixRequest.review_diff`
and `build_fix_prompt`. The diff is filtered/redacted again, restricted to allowed
context files and capped at 16,000 characters. It can explain a removed contract but
cannot authorize edits or replace current source for search strings.

Five fixes passed independent checks and normal Apply in this experiment. One Python
proposal passed normal validation and corrected the receipt, yet still broke the
original pricing helper contract. Its retry made the same mistake. We withheld both
and recorded evaluation-only failures after blind generation ended. Sentinel does not
automatically have these hidden business tests for a new repository. Read the failed
case as carefully as the successes: tests establish the behaviours they check, not
every contract a developer cares about. The examples and original model results remain
available for further learning and quality improvements.

Historical paths matter too: `.env` renamed to `settings.py` still has a protected
old side. The shared diff filter now checks both names, and `reviewed_fix_config`
carries excluded paths into fix context. A copied in-memory ignore list prevents a
graph neighbor from undoing that exclusion; saved configuration stays unchanged.
Public-to-public renames still work. The [evaluation report](MULTIFILE_QUALITY_EVALUATION.md)
records the focused privacy tests and the full regression run after the repair.


## Investigating a fix that passes tests but breaks a public helper

Read [the pricing investigation](PRICING_FIX_INVESTIGATION.md) after the multi-file
evaluation. That earlier checkpoint had one unresolved case; this follow-up repairs
it without erasing the failed attempts.

1. Trace the value: `1299 * 2` should stay `2598` minor units. The changed helper
   divided by 100. Multiplying back in checkout corrected only that caller.
2. Inspect the model's actual input. The review suggested the caller workaround;
   its historical diff already showed the old contract. Missing history alone did
   not explain the second failure. Suggested fixes need checking against evidence.
3. Inspect what the tests assert. Old generated tests checked the final response;
   the new ones also call `line_total` and `subtotal` directly. Tests are executable
   examples of a contract, not proof of behaviours that nobody asserted.
4. Follow `SYSTEM_REVIEW` and `SYSTEM_FIX` in `ai/prompts/__init__.py`. Review now
   asks for the first changed operation breaking a contract; fix generation treats
   suggestions as hypotheses and asks for direct producer plus consumer tests.
5. Follow `confirm_with_regression` in `core/fixes/regression.py`. A related helper
   repair cannot pretend the cited caller changed. Its skipped check now explains
   the reason and recommends rerunning review. No Apply gate was weakened.
6. Follow `tests/integration/test_pricing_contract.py`. It replays real captured old
   and new edits with identical stronger tests, entirely in Docker. The shortcut
   fails; the root repair validates. CI makes no AI call for this regression.

The live fresh review cited the pricing conversion, generated a root fix and three
tests, passed all seven normal gates plus independent checks, and applied normally
to a disposable example. The legacy downstream finding produced a correct helper
fix but stayed unverified and could not Apply. The learning point is to fix the
earliest broken contract and verify callers as well, while retaining conservative
evidence rules. The detailed report separates both outcomes and their limits.


## Following a real notification, then removing temporary access

Read [the GitHub recovery walkthrough](GITHUB_CONNECTION_RECOVERY.md). A GitHub App
installation gives permission; a reachable webhook address supplies the route. Both
are necessary. A running connection program is insufficient when DNS cannot find its
generated name.

1. Follow `public_gateway_ready` in
   [`integrations/github/dev_readiness.py`](../src/sentinel/integrations/github/dev_readiness.py).
   The local connector calls it before changing the App setting. It sends independent
   unsigned requests, hides the private API, checks signature enforcement and rejects
   redirects. It deliberately carries none of the authenticated GitHub client's defaults.
2. Read [`test_github_dev_readiness.py`](../tests/unit/test_github_dev_readiness.py).
   These 14 offline cases cover the failed connection boundary and credential handling;
   they do not contact Cloudflare or replace a real signed GitHub ping.
3. Trace the real event through webhook signature verification, its durable delivery
   reservation, the queued review, all eight stages and GitHub publication. The saved
   PR #2 review completed on `30d0d11e4de9f9d2e1c8f58f5c27100779b5bddd` with Gemini,
   one supported SQL-injection finding, one summary and one inline comment. A relay's
   HTTP 200 alone proves less than that full chain.
4. Distinguish testing from deployment. Smee temporarily forwarded invented test-repo
   events with explicit consent. Its restricted Docker container held no project mount
   or AI/App keys. The original GitHub signature was still checked locally.
5. Finish the lifecycle: restore the prior inactive GitHub webhook setting, remove the
   temporary relay container/image, stop its gateway and delete the saved channel and
   restoration records. All were checked. Existing App permissions and saved review
   data remain; no ongoing notifications are connected. Remote erasure is not claimed.

The PR remains open and unmerged so its result can be inspected. This exercise verified
notification → review → publication; earlier fix/Apply evidence remains separate. A
future permanent service needs a durable reachable HTTPS address and its own acceptance
checks. The normal Cloudflare launcher does not automatically reconnect Smee.


## Understanding GitHub checks and deciding when V1 is finished

Follow [the current release acceptance list](RELEASE_READINESS.md). The important
distinction is what was observed on which version, rather than how many files exist.

GitHub Actions is a separate computer running this repository's
[CI workflow](../.github/workflows/ci.yml). It starts three independent jobs:

- **Python:** install locked tools, build the Docker sandbox, check style/types, run
  tests including PostgreSQL variants, and enforce overall/core coverage gates.
- **Frontend:** install the locked browser dependencies, check types/formatting, run
  component tests and build the UI files.
- **Compose:** start a disposable full server with PostgreSQL and separate workers;
  exercise review, Docker-validated multi-file Apply and persistence, then clean it up.

`queued` means GitHub has not reported a running/completed job. `in_progress` means
work is underway; `success` means its checks passed; `failure` means inspect that
job's failing step/log before changing code. Runner or service problems and assertion
failures require different repairs. Do not call an older green commit proof of a new
commit, remove a failing test, or bypass a coverage gate to obtain a green badge.

At this assessment, code revision `d2cd45c` is queued without assigned runners or
failure annotations. GitHub reports an Actions incident with processing/status delays;
that is consistent with the queue and does not establish a Sentinel code defect.
The previous `ff4759b` run passed; current code separately passed 647 local tests,
with 27 PostgreSQL variants skipped. No new code failure was reported to fix.

The core already completes local review → AI findings → proposed fix → Docker checks
→ explicit Apply. Real GitHub reviews also worked. Final V1 demonstration work is
to confirm latest hosted CI, rehearse today's complete browser workflow with the
configured bridge, and finish a repeatable public demo. Compose's controlled HTTP
provider proves service wiring without spending AI quota; it is not a live Gemini or
DeepSeek acceptance test. The OpenCode Compose profile still needs its own complete run.

Keep a separate list for an always-on public service: stable HTTPS, outage/backup
recovery, concurrent pushes, usability, capacity and retention measurements. Optional
Ollama/Claude/GLM setup and compiler-grade analysis do not block this V1. Smee remains
disconnected; this documentation update did not restore any temporary relay access.
