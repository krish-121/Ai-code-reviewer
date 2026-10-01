# Benchmarks

How review time and memory grow with repository size (spec §42). Every number below was
produced by [`scripts/benchmark.py`](../scripts/benchmark.py) on the machine described at
the bottom; re-run it to get numbers for yours:

```bash
python scripts/benchmark.py                    # small, medium, large; median of 3 runs
python scripts/benchmark.py --sizes large --runs 1 --json results.json
```

## What is measured

For each size the script generates a Python + TypeScript repository — modules that call
each other across files, SQL access, HTTP routes, TypeScript services, pytest files and a
`tsconfig.json` — commits it, then stages a realistic small change: three Python modules gain
a function with an injectable f-string query and an N+1 loop, and one TypeScript file gains
an interpolated query. Then the **whole review pipeline** runs on that staged change, exactly
as `sentinel review --staged` would.

The AI stage is the one thing replaced: `MeasuringProvider` builds the real prompt (diff,
context blocks, static hints, redaction), counts its tokens, and returns no findings
instantly. Model latency depends on the provider, model and network, not on Sentinel, so it
is listed separately below rather than mixed into these numbers.

Each run is a fresh process (cold caches, separate memory measurement).

## Results

| | small | medium | large |
|---|---:|---:|---:|
| Files in repository | 43 | 388 | 2,304 |
| Lines of code | 986 | 9,641 | 57,721 |
| Files in the change | 4 | 4 | 4 |
| Code-graph nodes | 308 | 2,933 | 16,909 |
| `parse_diff` (ms) | 0 | 0 | 0 |
| `filter_files` (ms) | 4 | 2 | 3 |
| `build_graph` (ms) | 394 | 670 | 2,762 |
| `extract_context` (ms) | 2 | 11 | 80 |
| `static_analysis` (ms) | 2,404 | 2,416 | 3,841 |
| `ai_review` (ms, provider excluded) | 2 | 2 | 2 |
| `verification` (ms) | 0 | 2 | 19 |
| `finalize` (ms) | 1 | 3 | 11 |
| **Total review latency (ms)** | **2,833** | **3,196** | **6,771** |
| Peak memory (max RSS, MiB) | 54 | 72 | 167 |
| AI prompt size (tokens, estimated) | 2,430 | 2,430 | 2,430 |

Static analyzers that ran: Sentinel's built-in rules, Ruff, mypy and `tsc`. Bandit was not
installed, and ESLint needs `@typescript-eslint/parser` for TypeScript files, which was not
installed either; both report themselves as *unavailable* rather than failing.
Machine: 2 vCPUs, 8 GB RAM, Linux x86_64, Python 3.11. Median of 3 runs. The same 4 findings
were surfaced for every size, so the result does not depend on repository size.

## Reading the numbers

- **Static analysis dominates small and medium reviews.** It runs only on the changed files,
  so it stays almost flat (2.4 s → 3.8 s); most of that is mypy and `tsc` start-up. The
  analyzers run in parallel threads.
- **The code graph is the part that scales with repository size** (0.4 s → 2.8 s). It parses
  every code file, because callers, tests and entry points can live anywhere. The large
  repository has 2,304 code files, more than the default limit of 2,000
  (`DEFAULT_MAX_GRAPH_FILES` in `core/review/orchestrator.py`): the graph then covers the
  files nearest the change first (same directories, then shallower paths), and the summary
  says the graph was limited. Analyzer results are cached by content hash
  (`infrastructure/storage/cache.py`), so a second review of the same repository only
  re-parses changed files.
- **The prompt does not grow with the repository.** The context engine sends the changed
  symbols, their callers, callees, tests and entry paths within a character budget
  (`review.max_context_chars`), never the whole repository. Here that is about 2,400 tokens
  for every size — which is also what keeps AI cost and latency independent of repo size.
- **Memory grows roughly linearly with the graph** (≈ 7 KiB per graph node on top of a ~50 MiB
  baseline), so very large monorepos are bounded by the file limit, not by RAM.

## Model latency (not measured here)

Add the provider's response time to the totals above. It was not measured here (no network
access in the build environment). Measure it on your setup by running `sentinel review --staged --details` with a key
configured: the `ai_review` stage duration is shown in the progress display and stored on
the review (`stages` in the API, `sentinel_stage_duration_ms{stage="ai_review"}` in
`/metrics`).
