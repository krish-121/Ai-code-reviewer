# Sentinel — build progress

Living log of what is built, what was decided, and what still needs a human eye.
Spec: `project (1).md` (sections referenced as §N). Last updated: 2026-10-02.

## Steps

| # | Step | Status |
|---|------|--------|
| 1 | Scaffolding, tooling, vendored dependencies | Done |
| 2 | Core review engine (diff, filtering, AST, code graph, context, static analysis, AI providers, verification, findings) | Done |
| 3 | Persistence, job queue, services, API, worker, GitHub integration | Done |
| 4 | Fix engine, sandbox, CLI, demo repository | Done |
| 5 | Test suite (unit, integration, end-to-end, golden) | Done |
| 6 | Web UI | Done |
| 7 | Benchmarks, docs, CI, Docker files | Not started |
| 8 | Final check against the Definition of Done (§54), packaging | Not started |
| — | Readability audit of steps 1–6 (owner's code-quality standard) | Done (see below) |

Step 3/4 note: the API, worker and GitHub integration were half-done when an earlier
session hit its usage limit. They were finished in the following session and are covered by
`tests/integration/test_api.py`, `tests/unit/test_github.py` and
`tests/e2e/test_github_flow.py` (webhook → queue → worker → review → verification →
GitHub comments → re-run deduplication).

## Current verification state

- `pytest`: 250 passed, 1 skipped (the Docker sandbox test skips when the daemon is not
  running; it passes with Docker up).
- `mypy --strict`: clean (118 source files). `ruff check` (now including complexity,
  naming and docstring rules) and `ruff format --check`: clean.
- Coverage (last measured): 93% overall; core packages ≥90%. Re-measured in step 8.
- Frontend: `tsc --noEmit`, prettier, 11 `node --test` tests, esbuild production build: all pass.
- Demo: `scripts/seed_demo.py` reviews the demo repo (scripted AI replay), rejects all three
  planted wrong AI claims, and validates the SQL-injection fix in the Docker sandbox.

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
  and every function in them is short. Natural next splits if wanted: `models.py` →
  `changes.py` / `findings.py` / `review.py`; `store.py` → per-entity stores.
- Verification-check weights in `core/verification/checks.py` are inline keyword arguments
  (`weight=0.75`) rather than named constants; probes use named weights.

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

## Verified only with mocks — test these live with real keys

| Path | How it is tested here | What to try live |
|------|----------------------|------------------|
| Claude provider (`ai/providers/http_providers.py`) | `httpx.MockTransport` with recorded-shape responses | `SENTINEL_PROVIDER=claude ANTHROPIC_API_KEY=… sentinel review --staged` |
| Gemini provider | `httpx.MockTransport` | `SENTINEL_PROVIDER=gemini GEMINI_API_KEY=…` |
| Ollama provider | `httpx.MockTransport` | `ollama serve` + `SENTINEL_PROVIDER=ollama` |
| GitHub App auth (JWT → installation token) | Real RS256 signing; GitHub responses faked (`tests/unit/test_github.py::FakeGitHub`) | Install the App on a test repo |
| GitHub REST calls (PR metadata, tarball, comments, update/dedupe) | Fake GitHub transport | Open a PR on the demo repo |
| Webhook delivery | Locally signed payloads; HMAC check is real | Point the App webhook at `/api/github/webhook` (e.g. via a tunnel) |
| Bandit adapter | Parser tested on recorded JSON (Bandit not installed here) | `pip install bandit` then review the demo repo |
| PostgreSQL | All tests run on SQLite so far; Postgres check planned in step 7 | `docker compose up` |
| Docker sandbox image | Verified with a locally built image (no registry access); `Dockerfile.sandbox` itself not built here | `docker build -f Dockerfile.sandbox -t sentinel-sandbox .` |

## NEEDS REVIEW

1. **Frontend stack (§31).** The spec *recommends* Next.js, Tailwind, shadcn/ui, Monaco and
   TanStack Query. The npm registry is blocked in this workspace, so the UI is React 19 +
   TypeScript bundled with esbuild, hand-written CSS, a small built-in syntax highlighter and
   a tiny `useQuery` hook. It is served by FastAPI as static files. Components are plain
   React, so moving to Next.js later is mostly a routing/bundling change.
2. **Database migrations.** Tables are created with SQLAlchemy `create_all()`; Alembic is
   not set up. Fine for a fresh install, but schema changes on an existing database need a
   migration tool before real use.
3. **GitHub App permissions.** Installation tokens are requested with only
   `contents: read`, `pull_requests: write`, `issues: write` (`MIN_PERMISSIONS` in
   `integrations/github/client.py`); `issues: write` is needed because PR conversation
   comments use the Issues API. Check runs are not used. Confirm this matches how you want
   results to appear on PRs.
