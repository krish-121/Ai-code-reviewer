# Working on Sentinel

The rules every change follows, and the checks to run before committing. The spec is
[`docs/SPEC.md`](docs/SPEC.md); build status and open questions are in
[`PROGRESS.md`](PROGRESS.md); a guided tour of the code is in
[`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md).

## Code-quality standard

Working code that is hard to follow counts as unfinished. The automated checks do not
catch everything below, so read your diff with these in mind.

- **Readability beats cleverness.** No dense one-liners, metaprogramming or extra layers.
  Use the simplest design that meets the spec.
- **Small, focused units.** One responsibility per module; functions roughly under 40
  lines; files roughly under 300 lines. Split when bigger.
- **Clear names.** Descriptive, no cryptic abbreviations.
- **Docstrings.** Every module starts with what it does, why it exists and where it sits in
  the flow (what calls it, what it calls). Every public class and function says what it
  does and why. Comments only where the reason is not obvious.
- **Types and data.** Full type hints; Pydantic models for data crossing boundaries. No
  magic numbers or strings — use named constants or settings. No dead or duplicated code.
- **One pattern for each concern.** Errors: raise a `SentinelError` subclass
  (`core/domain/errors.py`). Settings: `core/configuration/config.py`. Wiring:
  `bootstrap.py`. Logging: a named `sentinel.*` logger (`logging.getLogger("sentinel.…")`),
  configured once in `infrastructure/observability/logging.py`.
- **Dependency direction.** `core/` knows nothing about FastAPI, SQLAlchemy, GitHub or AI
  vendors; those live in `apps/`, `infrastructure/`, `integrations/`, `ai/` and `sandbox/`
  and plug into the interfaces in `core/domain/ports.py`.
- **Readable tests.** Names describe behaviour (`test_rejects_hallucinated_symbols`);
  each test is arrange / act / assert.
- **Lint rules are fixed, not silenced.** Ruff enforces complexity (≤ 10), naming,
  bugbear, simplify and docstring rules. Add a `noqa` only with a reason next to it.
- **Frontend** (`web/`): small typed components, feature folders, no giant files.
- **Security rules from the spec are not negotiable:** never send `.env`, keys or
  credentials to a model; treat repository content as untrusted data; never run generated
  code on the host; keep one user's data out of another's; minimal GitHub permissions.

## Checks before committing

```bash
ruff check src tests scripts && ruff format --check src tests scripts
mypy
pytest --cov=sentinel --cov-fail-under=80
coverage report --include="*/sentinel/core/*" --fail-under=90
cd web && npm run lint && npm test && npm run build    # when the UI changed
```

PostgreSQL variants run when `SENTINEL_TEST_DATABASE_URL` is set; Docker sandbox tests run
when Docker and the `sentinel-sandbox` image are available. Otherwise they skip.

When you make a decision the spec does not cover, add it to *Assumptions* in
`PROGRESS.md`; if it is costly to undo, add it to *NEEDS REVIEW*.
