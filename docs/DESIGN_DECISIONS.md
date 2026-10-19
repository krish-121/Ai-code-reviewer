# Design decisions

Each decision follows the same shape: **Problem → Alternatives → Decision → Trade-offs**,
with a pointer to the code that implements it. The first twelve are the questions the spec
(§50) asks; the rest are decisions this implementation had to make on its own.

1. [Why Python?](#1-why-python)
2. [Why httpx instead of vendor SDKs?](#2-why-httpx-instead-of-vendor-sdks)
3. [Why Pydantic?](#3-why-pydantic)
4. [Why PostgreSQL?](#4-why-postgresql)
5. [Why background jobs (and why no Redis)?](#5-why-background-jobs-and-why-no-redis)
6. [Why a code graph?](#6-why-a-code-graph)
7. [Why AST instead of only embeddings?](#7-why-ast-instead-of-only-embeddings)
8. [Why deterministic verification?](#8-why-deterministic-verification)
9. [Why BYOK?](#9-why-byok-bring-your-own-key)
10. [Why a Docker sandbox?](#10-why-a-docker-sandbox)
11. [Why not review the entire repository?](#11-why-not-review-the-entire-repository)
12. [Why not let the AI directly edit files?](#12-why-not-let-the-ai-directly-edit-files)
13. [Why a deterministic summary?](#13-why-a-deterministic-summary)
14. [Why treat pull-request workspaces as untrusted?](#14-why-treat-pull-request-workspaces-as-untrusted)
15. [Why Server-Sent Events for progress?](#15-why-server-sent-events-for-progress)
16. [Why a React SPA bundled with esbuild (not Next.js)?](#16-why-a-react-spa-bundled-with-esbuild-not-nextjs)
17. [Why versioned migrations?](#17-why-versioned-migrations)
18. [Why content-addressed caching?](#18-why-content-addressed-caching)
19. [Why suppress instead of delete?](#19-why-suppress-instead-of-delete)

---

## 1. Why Python?

**Problem.** The core of a reviewer is parsing and analysing code. The tools it orchestrates
(Ruff, mypy, Bandit) and the best-supported AST tooling for the first target language are
Python.

**Alternatives.** TypeScript/Node (natural for the web UI and the TS compiler API); Go (fast,
single binary); Rust.

**Decision.** Python 3.11 for the engine, API, worker and CLI; a small Node script
([`ts_extract.js`](../src/sentinel/analysis/ast/ts_extract.js)) only where the TypeScript
compiler itself is the right parser.

**Trade-offs.** Python's `ast` module gives exact Python structure for free, and the static
tools are a subprocess away. Raw speed is lower than Go or Rust, but [the
benchmarks](BENCHMARKS.md) show the time goes to graph building and external tools, not
Python overhead. Strict typing (mypy `--strict`) recovers most of what a compiled language
would catch.

## 2. Why httpx instead of vendor SDKs?

**Problem.** Sentinel talks to three AI providers and GitHub. Each vendor SDK brings its own
retry policy, timeout semantics, error types and dependency tree.

**Alternatives.** `anthropic`, `google-genai` and `ollama` SDKs; a multi-provider library
such as LiteLLM.

**Decision.** Plain HTTPS with `httpx` for every provider and for GitHub. One base class,
[`HTTPProvider`](../src/sentinel/ai/providers/base.py), owns the reliability policy (backoff
honouring `Retry-After`, one retry on timeout, auth errors as configuration errors, one
repair retry on invalid JSON); each provider in
[`http_providers.py`](../src/sentinel/ai/providers/http_providers.py) only describes its
wire format in `_complete`.

**Trade-offs.** Identical behaviour across providers, a tiny dependency surface, and every
failure mode is testable with `httpx.MockTransport` (no network in tests). The cost is
following API changes by hand and not getting SDK conveniences (streaming helpers, typed
responses) — acceptable because Sentinel needs one request/response shape per provider.

## 3. Why Pydantic?

**Problem.** Data crosses many boundaries: model output, `.sentinel.yml`, environment
variables, the database (JSON columns) and the HTTP API. Model output in particular is
untrusted and often malformed.

**Alternatives.** dataclasses + manual validation; `attrs`; JSON Schema validation only.

**Decision.** Pydantic v2 models for the domain
([`models.py`](../src/sentinel/core/domain/models.py)) and *strict* models for what the AI
must return ([`ai.py`](../src/sentinel/core/domain/ai.py): unknown fields are rejected,
lengths and ranges are bounded). The JSON schema sent to providers is generated from the
same models ([`ai/schemas`](../src/sentinel/ai/schemas/__init__.py)), so the contract has
one source of truth.

**Trade-offs.** A response is either a valid typed object or a precise error message that is
sent back to the model for one correction. Free-form Markdown is never parsed. The cost is
some runtime validation overhead (negligible next to model latency) and a dependency that
the domain layer does use — accepted, because Pydantic is a data-modelling tool, not a
framework.

## 4. Why PostgreSQL?

**Problem.** Review history, finding status changes, fix attempts and the job queue must
survive restarts and be shared by the API and several workers. (Not "because real apps use
Postgres" — §29.)

**Alternatives.** Files on disk; SQLite only; a document store.

**Decision.** SQLAlchemy 2.0 with PostgreSQL for deployments and SQLite for the CLI and most
tests ([`session.py`](../src/sentinel/infrastructure/database/session.py)). The store, queue,
API and end-to-end tests run against both (set `SENTINEL_TEST_DATABASE_URL`).

**Trade-offs.** PostgreSQL gives row locking (`SKIP LOCKED`) for the queue and safe
concurrent writers; SQLite gives a zero-setup local tool. Supporting both means sticking to
portable SQL and JSON columns instead of PostgreSQL-only types.

## 5. Why background jobs (and why no Redis)?

**Problem.** A review takes seconds to minutes (static tools, model latency). An HTTP
request — and certainly a GitHub webhook, which GitHub times out after 10 s — must not wait
for it. Work must also survive a worker crash.

**Alternatives.** Run reviews inside the request; Celery or RQ with Redis; a cloud queue.

**Decision.** The API only creates a `Review` row and a job, then returns `202`. Workers
claim jobs from a table ([`jobs.py`](../src/sentinel/infrastructure/queue/jobs.py)) with a
lease, keep it alive with heartbeats, and retry failures with exponential backoff. A crashed
worker's lease expires and another worker picks the job up. Redis is not used: the spec says
"Redis only if actually required" (§32), and the database the system already needs can do
the job.

**Trade-offs.** One less moving part, transactional enqueueing (the review row and its job
commit together), and jobs are inspectable with SQL. Polling adds up to a second of pickup
latency and the design is not meant for thousands of jobs per second — far beyond a code
review tool's needs.

## 6. Why a code graph?

**Problem.** A diff alone hides most of what makes a change dangerous: who calls the changed
function, whether user input reaches it, which tests cover it, what data it touches.

**Alternatives.** Send the diff only; send whole changed files; send files that share a
directory or import the changed file.

**Decision.** Build a lightweight graph of files, symbols, endpoints and data stores with
calls, imports, routes, tests and reads/writes
([`builder.py`](../src/sentinel/analysis/graph/builder.py),
[`graph.py`](../src/sentinel/core/domain/graph.py)). The context engine, the verifier and the
architecture view all query it.

**Trade-offs.** The graph answers "is this reachable from `GET /search`?" and "does
`search()` really call `search_products()`?" — the questions that turn an AI guess into a
checked claim. It is not compiler-grade: dynamic dispatch and metaprogramming are missed,
and resolution is conservative on purpose (a missing edge costs context; a wrong edge would
mislead the verifier). Building it is the step that grows with repository size.

## 7. Why AST instead of only embeddings?

**Problem.** The reviewer needs the *right* surrounding code, not merely *similar-looking*
code.

**Alternatives.** Embed chunks and retrieve by vector similarity; let the model ask for
files; keyword search.

**Decision.** Use ASTs (Python `ast`, the TypeScript compiler) to extract symbols and
relationships, and select context by graph structure: changed symbols, callers at the call
site, callees, tests, entry paths and data access, fitted into a character budget by priority
([`ContextEngine`](../src/sentinel/analysis/graph/context.py)).

**Trade-offs.** Structural retrieval is exact, explainable ("included because it calls
`find_user` at line 42") and deterministic (same input → same prompt → cacheable), and it
needs no embedding model, vector store or API key. Embeddings would find conceptually similar
code that is not structurally linked (e.g. a duplicated validation routine elsewhere); that is
a reasonable V2 addition *on top of* the graph, not instead of it.

## 8. Why deterministic verification?

**Problem.** Language models produce plausible but wrong findings: hallucinated functions,
"SQL injection" in parameterized queries, style remarks filed as bugs. A reviewer that cries
wolf gets ignored.

**Alternatives.** Trust the model; ask a second model to judge the first; show everything
with a confidence number.

**Decision.** *AI proposes, deterministic systems verify.* Every AI claim is checked against
the code by independent checks and probes
([`checks.py`](../src/sentinel/core/verification/checks.py),
[`probes/`](../src/sentinel/analysis/static/probes/)); decisive contradictions reject it,
strong independent evidence supports it
([`engine.py`](../src/sentinel/core/verification/engine.py)). Every check is shown in the UI.

**Trade-offs.** Rejections are explainable ("the query is parameterized (placeholders + a
separate parameters argument)") and reproducible, and the model cannot talk its way past a
probe. The cost is engineering: probes exist for the most common, most consequential
claim types (injection, async misuse, N+1, quadratic loops, secrets, auth order, error
handling); other claims can only reach *likely* or *uncertain*, and the UI says so.

## 9. Why BYOK (bring your own key)?

**Problem.** Code is sensitive. Teams have different provider contracts, data-handling rules
and budgets, and some cannot send code to a third party at all.

**Alternatives.** A hosted key owned by the tool; a single fixed provider.

**Decision.** Users configure their own provider and key (Claude, Gemini) or a local model
(Ollama); `none` runs a deterministic-only review
([`factory.py`](../src/sentinel/ai/providers/factory.py),
[`config.py`](../src/sentinel/core/configuration/config.py)). Keys come from the environment
or a `0600` config file and are scrubbed from every child process environment.

**Trade-offs.** No vendor lock-in, costs land with the user, and a fully local setup is
possible. Results vary by model quality — which is exactly why verification does not depend
on the model being right.

## 10. Why a Docker sandbox?

**Problem.** Validating a fix means running the project's tests on AI-written code. That
code — and the tests themselves in a pull request — must be assumed hostile.

**Alternatives.** Run tests on the host; a subprocess with a clean environment; gVisor or
Firecracker micro-VMs; a remote CI runner.

**Decision.** Docker containers with no network, a read-only root filesystem, a small
writable `/tmp`, memory/CPU/PID limits, all capabilities dropped, no new privileges, the
caller's UID, a scratch copy of the repository and a hard timeout
([`DockerSandbox`](../src/sentinel/sandbox/runners.py)). A weaker process runner remains
available for explicitly requested diagnostics, but fix validation refuses it. Both
generated-code analysis and tests require Docker. Without Docker these checks are skipped
and the fix is "unverified". Passing an existing suite alone does not establish resolution.
A reproduced static rule or genuine new before/after regression can confirm it; the latter
is explicitly labelled test-backed and still requires every other gate.

**Trade-offs.** Strong isolation with a tool developers already have. Containers share the
host kernel (a micro-VM would isolate better), and with no network the image must already
contain the project's test dependencies — for real projects, extend `Dockerfile.sandbox`.

**Containerized workers.** Compose separates review/publication jobs from a fix-only worker
that controls Docker. Its copy transport sends a bounded, link-free scratch archive to an
installed launcher and private tmpfs instead of binding worker paths on the daemon host.
The API and review worker have no daemon access. This fixes path translation and limits
the credential boundary, but socket access still gives the trusted fix worker authority
over that engine's host. A dedicated engine/VM is the deployment boundary, not the worker's
non-root UID. See [DEPLOYMENT.md](DEPLOYMENT.md).

## 11. Why not review the entire repository?

**Problem.** Reviewing everything on every change is slow, expensive and noisy, and it
buries the issues the author can act on now.

**Alternatives.** Whole-repository scans; whole changed files.

**Decision.** Review the *change*: the diff plus the context that explains it. Static tools
run on changed files; deterministic findings outside the changed lines are suppressed as
"pre-existing"; the AI is told to report problems introduced or made worse by the change.
`sentinel review --path` exists for deliberately reviewing whole files.

**Trade-offs.** Prompt size stays constant as the repository grows (≈2,400 tokens in every
benchmark size), feedback stays relevant, and costs stay predictable. Old problems in
untouched code are out of scope unless the change makes them reachable.

## 12. Why not let the AI directly edit files?

**Problem.** A model with write access to a working tree can break code, delete files or be
steered by injected text into doing something else entirely.

**Alternatives.** Let an agent edit and run commands; accept a full rewritten file; accept a
unified diff from the model.

**Decision.** The model returns *search/replace edits* as JSON. Each `search` text must
occur exactly once ([`apply_edits`](../src/sentinel/core/fixes/patch.py)); the result is
applied to scratch copies, parsed, re-analysed and tested in the sandbox
([`FixEngine`](../src/sentinel/core/fixes/engine.py)). The developer's files change only
when they click *Apply*, and only if the files' hashes still match.

**Trade-offs.** Small, reviewable, verifiable patches; the model never runs anything. It
needs an extra round trip when edits do not apply (handled by one retry with feedback), and
large refactors are out of scope by design.

## 13. Why a deterministic summary?

**Problem.** A model-written summary can contradict the verified findings ("no security
issues") or overstate them.

**Alternatives.** Ask the model for a summary; no summary.

**Decision.** The summary — risk level, headline, what changed, what deserves attention, what
was verified, what remains uncertain — is assembled from the diff, the findings and the
verification results ([`summary.py`](../src/sentinel/core/review/summary.py)). Risk is only
HIGH with a *confirmed* high-severity finding.

**Trade-offs.** It can never claim something the evidence does not show; it is less fluent
than prose a model would write.

## 14. Why treat pull-request workspaces as untrusted?

**Problem.** A pull request controls its own repository contents — including
`node_modules/.bin/eslint`, a `mypy.ini` that loads plugins, or a local `typescript`
package. Running "the project's own tools" would run the attacker's code.

**Alternatives.** Run tools as for a local review; run all analysis inside the sandbox.

**Decision.** `trust_workspace=False` for GitHub reviews: tools come only from the server's
PATH, mypy runs with an isolated configuration, and the workspace's TypeScript package is
never loaded ([`runner.py`](../src/sentinel/analysis/static/runner.py),
[`bootstrap.py`](../src/sentinel/bootstrap.py)).

**Trade-offs.** Results may differ slightly from the project's own tool configuration on
PRs; in exchange, opening a pull request cannot execute code on the review server.

## 15. Why Server-Sent Events for progress?

**Problem.** The UI shows each stage as it happens (§30).

**Alternatives.** WebSockets; client polling; an in-memory pub/sub between worker and API.

**Decision.** A one-way SSE stream that reads stage rows from the database
([`progress_events`](../src/sentinel/apps/api/routes/reviews.py)).

**Trade-offs.** Updates only flow server → browser, which is all progress needs; SSE works
through proxies and needs no extra protocol. Reading the database (rather than a pub/sub
channel) means it works whichever worker process runs the review, at the cost of
half-second polling.

## 16. Why a React SPA bundled with esbuild (not Next.js)?

**Problem.** The spec recommends Next.js, Tailwind, shadcn/ui, Monaco and TanStack Query
(§31). The build environment for this project had no access to the npm registry.

**Alternatives.** Wait for registry access; vendor the whole Next.js toolchain by hand.

**Decision.** React 19 + TypeScript, bundled with esbuild into the Python package and served
by FastAPI ([`web/`](../web/), [`routes/web.py`](../src/sentinel/apps/api/routes/web.py)).
Hand-written CSS with design tokens, a small syntax highlighter
([`highlight.ts`](../web/src/lib/highlight.ts)) and a tiny data hook
([`hooks.ts`](../web/src/lib/hooks.ts)) replace Tailwind, Monaco and TanStack Query.

**Trade-offs.** One process serves everything and `sentinel serve` works offline. Fewer
ready-made components and no server-side rendering (not needed for an authenticated tool).
Components are plain React, so moving to Next.js later is mostly routing and bundling.
Listed as *NEEDS REVIEW* in [PROGRESS.md](../PROGRESS.md).

## 17. Why versioned migrations?

**Problem.** Fresh installs and upgrades must preserve existing review and job data.

**Alternatives.** Continuing to call the latest ORM metadata's `create_all()` cannot
provide a schema-upgrade history or safely recognize legacy installations.

**Decision.** Packaged Alembic revisions initialize fresh databases. Existing databases
upgrade explicitly, with locked transactions and validated legacy adoption.
See [DATABASE_MIGRATIONS.md](DATABASE_MIGRATIONS.md).

**Trade-offs.** Operators must back up and stop application processes for upgrades. Unknown
or custom legacy schemas are refused rather than guessed, and future revisions need
data-preservation and rollback tests on both database backends.

## 18. Why content-addressed caching?

**Problem.** Re-reviewing after a small push repeats expensive work: parsing unchanged files,
and possibly an identical model call.

**Alternatives.** Time-based caches; no caching.

**Decision.** Cache keys are hashes of the *content* that produced the value (file text +
analyzer version, or the full prompt + model + temperature)
([`cache.py`](../src/sentinel/infrastructure/storage/cache.py)).

**Trade-offs.** An entry can never be stale — changed input produces a different key — so
there is no invalidation logic. The cache only grows; entries are small and the cache
directory can be deleted at any time.

## 19. Why suppress instead of delete?

**Problem.** Rejected claims, findings below a threshold and findings over the display
budget must not clutter the review, but silently dropping them would hide the system's
reasoning.

**Decision.** [`select`](../src/sentinel/core/findings/prioritize.py) splits findings into
*surfaced* and *suppressed*, recording a reason for each suppressed one ("rejected by
verification: …", "over the display budget of 10", "pre-existing issue outside the
change"). The UI and CLI can show them on request.

**Trade-offs.** Full transparency (you can see what the AI claimed and why Sentinel
disagreed) at the cost of storing a few more rows per review.

## 20. Why lexical variable dependencies and independent graph views?

**Problem.** A changed constant needs its unchanged consumers as context. Matching names
alone confuses globals with locals. Sharing mutable graph nodes lets a UI view change
analysis state by marking its nodes as changed.

**Alternatives.** Ignore variables; connect every matching name; execute repository code
to observe values; build a complete compiler/taint engine; maintain one mutable graph.

**Decision.** Use Python's symbol table and TypeScript's lexical binder for bounded
module-variable reads/writes and known import bindings. The virtual TypeScript host reads
no project config, plugins or files. Independent UI projections copy node metadata, break
budget ties deterministically and respect their node limit. Endpoint identity includes file
and handler. Bump the symbol-cache version when the extractor contract changes.

**Trade-offs.** Some extra parser work and graph nodes; incomplete local/class/dynamic
relationships. A missing edge does not prove safety. Copying small projected graphs costs
memory but keeps presentation separate from analysis without another framework.
See [GRAPH_ANALYSIS.md](GRAPH_ANALYSIS.md).

## 21. Why require validation before Apply?

**Problem.** An incomplete fix was labelled unverified but could still be written through
the UI, API and CLI. That contradicted the validated-fix workflow and our documentation.

**Alternatives.** Permit an override with a warning; disable only the UI button; require
the same validated status at the application boundary and every delivery surface.

**Decision.** The core writer refuses every nonvalidated outcome before opening files.
The API advertises Apply only for validated local patches; the UI also checks that status.
CLI `--apply` exits with a clear failure when validation is incomplete. Download and review
remain available. No force flag bypasses validation.

**Trade-offs.** A missing tool or broken project baseline can prevent Apply. Complete the
checks, fix the baseline or inspect the downloaded proposal separately. This is deliberate:
a warning cannot supply evidence that tests and analysis never produced.

## 22. Why separate structured-report and test-log budgets?

**Problem.** The demo's valid analyzer JSON exceeded the 20 KB test-log display limit.
Truncating it made validation fail even though the container completed successfully.

**Alternatives.** Remove output caps; truncate findings silently; compress every report;
or keep separate finite budgets for machine-readable reports and human-facing logs.

**Decision.** Trusted container analysis explicitly requests a 1 MiB output allowance and
shared 2 MiB pipe capture. Normal test commands retain their smaller limits. The caller
cannot request an unlimited budget. Truncated reports remain incomplete, with a useful
reason. The packaged demo now includes TypeScript configuration so that compiler can run.

**Trade-offs.** More bounded memory per concurrent analysis, and very large reports can
still exceed the budget. They must be reported incomplete, rather than losing diagnostics
while claiming success. Existing baseline diagnostics are compared, not silently removed;
project dependencies still belong in a trusted sandbox image.

## 23. Why a separate OpenCode bridge for quota fallback?

**Problem.** Gemini's free quota is limited. The direct OpenCode free API candidate
was blocked, while official OpenCode produced real free DeepSeek responses in Docker.

**Decision.** Keep the existing AIProvider interface and use an opt-in decorator that
switches from Gemini only on an explicit quota/rate-limit error. A small authenticated
HTTP bridge runs official `opencode run` inside Docker. Sentinel uses plain httpx,
without a vendor SDK or Docker access in review/API workers. Only the tested free
DeepSeek ID is accepted; GLM is excluded after service failures. Requests are bounded,
temporary sessions are discarded, and actual model/fallback reasons are persisted.

**Alternatives.** Spoof the free API client; pass a user's paid account to OpenCode;
give every worker a Docker socket; require local Ollama; or host a full OpenCode
server exposing file/shell/configuration APIs. The narrow bridge preserves the current
deployment boundary and the user's zero-purchase constraint without those changes.

**Tool policy.** Denying every tool triggered a misleading free-tier rejection. The
working official CLI retains approval-required tools, automatically rejects requests
without an interactive user, and the bridge rejects tool-bearing results. A live
diagnostic confirmed rejection and no file creation. No host project, vendor key or
Docker socket enters the bridge. Its local bearer token is not a vendor credential.

**Trade-offs.** An extra service and image need Docker running. Standard OpenCode adds
prompt/token overhead. One active request, time/output limits and free-service outages
can make a review partial; this is reported honestly. Cooldown is best-effort cache
state, not quota accounting. A fallback sends redacted source to another online service,
so users must opt in. Existing schema, verification and validated-only Apply remain.
See [FREE_AI_FALLBACK.md](FREE_AI_FALLBACK.md) for the source and operating steps.

## 24. Why save Docker copy transport for the local WSL setup?

**Problem.** The normal sandbox image was missing, and earlier fix checks relied on
temporary image/transport overrides. Windows Docker Desktop and Ubuntu do not always
resolve a bind-mounted path in the same way.

**Alternatives.** Require a fresh environment override each terminal, depend on matching
host paths, or persist the existing filtered-copy transport through normal settings.

**Decision.** Build `sentinel-sandbox:latest` from the trusted Dockerfile and allow
`sentinel config set sandbox_transport copy`. The settings writer validates the value
and preserves existing private settings. Validation runs on temporary container copies
without a project bind mount, network access, vendor keys or Docker socket. Apply remains
a separate validated-only operation on the original files.

**Trade-offs.** Copying has bounded archive/workspace overhead. Extra project dependencies
must already exist in a trusted image. Docker Desktop must be running. This is a local
WSL setup choice, not a replacement for the dedicated worker boundary in Compose.
The real Gemini fix/Apply acceptance is recorded in [LIVE_FIX_WORKFLOW.md](LIVE_FIX_WORKFLOW.md).

## 25. Why allow test-backed resolution for logic fixes?

**Problem.** Live examples produced correct patches and reproducing tests for logic bugs
that no linter rule recognized. Resolution stayed skipped while other checks passed.
Node's TAP output was also mistaken for missing pytest evidence.

**Decision.** Keep static rechecks. If resolution is unavailable, a changed target and
the same new test failing on original code and passing on the patch can supply test-backed
evidence. Complete Docker analysis, no new serious diagnostics, passing existing tests,
supported output, path/hash checks and validated-only Apply remain required. A failed
static recheck cannot be overwritten; editing only another context file is insufficient.

**Alternatives.** Leave every AI-only logic proposal permanently unverified; use a second
model as judge; or permit Apply because old tests pass. A reproduced regression adds
deterministic behaviour evidence without another model or host execution.

**Trade-offs.** A model's test may assert the wrong requirement. Validation proves tested
behaviour, not all semantics; developers still inspect the patch/tests. This evaluation
also used independent held-out checks never shown to the model. Pytest and Node TAP
test-case failures are supported; failed module loading, cancellation, timeouts and
unsupported/incomplete reports do not establish a regression.
See [QUALITY_EVALUATION.md](QUALITY_EVALUATION.md) for original and repaired outcomes.

## 26. Include named imported data contracts in review context

A multi-file clean Decimal refactor exposed a false alarm about fractional amounts:
the AI saw pricing functions but not the imported cart model's integer fields.
Imported types are not necessarily callees. Add bounded class/data definition blocks
through existing resolved import edges and exact named imports, including aliases.
Reuse context budgets, overlap deduplication and redaction. Avoid whole-module dumps,
global same-name guesses and a special-case suppression for Decimal findings. Add a
general prompt reminder to demonstrate a concrete supported failing input. Tests cover
Python/JS/TS aliases, unrelated same-name classes, caps, missing imports and redaction.

This supplies evidence; it does not make Python annotations runtime validation or turn
the graph into a full type checker. Models can still invent unsupported requirements.

## 27. An omitted fix target is not a changed fix target

`apply_edits` returns touched files rather than the entire context. A helper-only patch
therefore has no entry for an unchanged target. Comparing the original target text to
`after.get(target)` compared text with None and incorrectly promoted test-backed
resolution. Require explicit membership plus different content. Keep missing/no-op
targets unverified; keep existing static failures and other incomplete gates blocking.
This preserves the conservative current rule rather than assuming any passing new
test establishes every claimed cross-file correction. Broader causal validation would
need separate design and evidence, not a changed comment to satisfy a text gate.

## 28. Unknown runtime properties are neutral, not invented functions

An actual job finding mentioned a rejected-result `reason` field; the verifier treated
its absence from repository declarations as a contradiction. Extract symbol evidence
into a focused module. Preserve checks for explicit invented free function calls, but
leave unresolved fields/object members neutral: a property can belong to a library or
runtime value. This does not claim it exists or independently confirm runtime behaviour.
Retain the original captured review and record deterministic replay separately.

## 29. Give fixes the original reviewed change as bounded untrusted history

A checkout proposal corrected the API output while missing an old pricing helper unit
contract, and two other proposals lacked new regressions. The generator previously saw
only current files plus the finding. Supply the saved ChangeSet through the normal fix
service without a schema migration. Re-filter it, scope it to allowed current context
files, cap historical diff text at 16,000 characters and fence/redact it in the prompt.
It grants no new paths or edits; search strings still come from current files. Explicitly
request a new reproducing regression when a slot is available and preservation of public
contracts. Do not expose held-out tests or their failure output as generation feedback.

The follow-up fixed missing-test cases but still missed the pricing helper contract.
Keep that failure visible. These are context/guidance improvements, not a semantic proof
system. A validated result states which checks passed; independent business tests and
developer inspection remain necessary. Separate evaluation-only rejection from built-in
validation so the project does not pretend to have an oracle on arbitrary repositories.

## 30. Historical paths cannot bypass the shared privacy policy

Historical fix diffs prompted inspection of renames. Check sensitive names and ignored/
generated paths on both old and new sides. A public destination cannot authorize old
protected content. Carry review skip paths into a copied effective fix config so graph
neighbors cannot reintroduce excluded source. Keep public renames reviewable and user
configuration unchanged. This is shared source policy, not a model-specific redaction
patch, and does not claim perfect semantic secret detection for arbitrary source text.


## 31. Localize contract failures before choosing a workaround

The Python pricing retry already saw the original diff but followed the review's
conditional caller compensation. It fixed checkout while leaving the public helper
wrong. Review should identify the first changed operation violating a visible
established contract. Fix generation should treat the suggestion as an unverified
hypothesis and request direct producer plus consumer regressions. Do not infer an
intentional API change from a representation refactor alone.

Keep the existing target-change rule: general causal verification of arbitrary
helper-only fixes is a larger problem than import reachability. Improve its skipped
message instead of accepting an unrelated test or cosmetic target edit. A fresh
review can correctly locate the root defect and complete guarded Apply. Preserve
the legacy unverified outcome and original rejected proposals as separate evidence.

An offline Docker regression replays actual old/new patches with the same stronger
model-generated tests. It guards this failure shape without an AI key or changing
the original hidden tests. Prompt guidance does not automatically enforce every
contract, and stronger tests must actually be present to detect the old shortcut.
See [the focused investigation](PRICING_FIX_INVESTIGATION.md).


## 32. Verify public readiness before changing a development webhook address

A tunnel can connect to its provider while its generated public name remains absent
from authoritative DNS. Do not treat process startup or an edge registration log as
working GitHub delivery. The computer-specific connector now probes its strict HTTPS
Quick Tunnel origin before updating GitHub: hidden private API (404), unsigned hook
rejected (401). Build unsigned independent requests, disable redirects and omit client
authentication/cookie/query defaults. A real signed GitHub ping is still required.

Keep the reusable probe in the GitHub integration; core code gains no tunnel or vendor
dependency. Keep machine-specific process orchestration in the exported local helper.
Offline tests guard the probe; a real PR demonstrates the wider delivery path.

Do not silently switch a private repository's notifications to another intermediary.
The Smee experiment required explicit temporary data-sharing consent and retained
signature validation. Cleanup removed its route, container/image, gateway and private
channel/restoration records. Preserve the existing App and AI credentials. State that
new reviews are disconnected afterward and do not claim remote event erasure.
See [GITHUB_CONNECTION_RECOVERY.md](GITHUB_CONNECTION_RECOVERY.md).


## 33. Version bundled browser assets by content

The actual browser retained old JavaScript after the server's rebuilt file changed.
Stable `app.js`/`app.css` paths alone did not establish that a client loaded the new UI.
The build now adds a short SHA-256 version derived from both outputs to their HTML
URLs. An esbuild end hook writes the index after every successful normal/watch build.
Stable file paths also require revalidation. This preserves package/server paths and
gives changed builds distinct browser URLs; fully hashed filenames plus a manifest
would require a larger serving/build contract. Revalidation adds modest requests.
The live same-tab rebuild and HTTP/real Compose assertions establish the selected path.

## 34. Keep completed evidence separate from missing review work

An unavailable AI stage can coexist with a supported deterministic finding. Carry
failed stages into summary limitations and protect older partial summaries in the UI.
Pending labels must not imply static-only completion; a configured default must be
distinguished from a saved review/fix's actual model. Keep generation and Apply gates
unchanged. Hiding local findings would discard useful evidence; claiming complete AI
coverage would overstate it. Display both the useful result and the missing work.

A test-location warning likewise cannot gain strong support merely because no test
calls that test function. Treat cited test code as neutral coverage evidence. Preserve
the original model run and replay saved sources separately, so a verifier correction
does not masquerade as a fresh accurate model response. Broader assertion semantics
remain outside this structural check. See [BROWSER_LIVE_WORKFLOW.md](BROWSER_LIVE_WORKFLOW.md).
