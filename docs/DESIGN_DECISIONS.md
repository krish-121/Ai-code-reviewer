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
17. [Why `create_all()` instead of migrations (for now)?](#17-why-create_all-instead-of-migrations-for-now)
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
([`DockerSandbox`](../src/sentinel/sandbox/runners.py)). A weaker process sandbox exists for
machines without Docker but must be explicitly enabled and reports its isolation level
honestly; without any sandbox, tests are simply skipped and the fix is "unverified".

**Trade-offs.** Strong isolation with a tool developers already have. Containers share the
host kernel (a micro-VM would isolate better), and with no network the image must already
contain the project's test dependencies — for real projects, extend `Dockerfile.sandbox`.

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

## 17. Why `create_all()` instead of migrations (for now)?

**Problem.** The schema needs to exist on first start.

**Alternatives.** Alembic migrations from day one.

**Decision.** `Database.create_all()` creates missing tables
([`session.py`](../src/sentinel/infrastructure/database/session.py)).

**Trade-offs.** Simplest possible setup for a new install; but schema *changes* on an
existing database need a migration tool. Adding Alembic is the first step before running
this with data you want to keep (NEEDS REVIEW in [PROGRESS.md](../PROGRESS.md)).

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
