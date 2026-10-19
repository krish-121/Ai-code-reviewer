# Cross-file Python, JavaScript and TypeScript quality evaluation

Verified **19 October 2026 (India time)** using actual free DeepSeek through the
existing OpenCode bridge and the normal Docker fix sandbox.

**Observed repeat review result:** all six planted bug cases detected, all three
correct changes without warnings. **Fix result: five of six cases independently
checked and applied. One Python proposal missed a pricing helper contract and was
not applied, even though Sentinel's normal validation checks passed it.**

The first review round had one false alarm; it is retained. These results are not
a perfect-accuracy claim, and the remaining fix miss is not hidden by the later checks.

| Language | Bug cases detected, repeat round | Correct changes without warnings, repeat round | Fix cases independently checked and applied |
|---|---:|---:|---:|
| Python | 2 / 2 | 1 / 1 | 1 / 2 |
| JavaScript | 2 / 2 | 1 / 1 | 2 / 2 |
| TypeScript | 2 / 2 | 1 / 1 | 2 / 2 |

## Step 1: make the problem cross a file boundary

Each of nine authored applications has six application files, existing tests and
three staged source changes. Application source ranges from **43 to 71 physical
lines**, with another **20 to 27 lines of ordinary tests**. These are larger than the
original single-file snippets, but still small dependency-light learning applications,
not large production repositories or a test of maximum context capacity.

| Case | Files that must agree | Behaviour checked independently |
|---|---|---|
| Python checkout | model, pricing, service, receipt, API | Every public pricing boundary and checkout receipt preserves minor currency units. |
| Python reservations | validation, service, inventory repository, API | Repeated SKU lines cannot overdraw stock; rejected requests change nothing. |
| JavaScript jobs | worker, scheduler, outcome store, report, API | A worker failure reaches the caller instead of becoming a successful partial response. |
| JavaScript pagination | request defaults, service, repository, response | Page numbers become row offsets; consecutive pages have no duplicates or missing items. |
| TypeScript organization access | principal, service, repository, response | Data and total counts belong only to the authenticated organization. |
| TypeScript cancellation | API, service, reader adapter, snapshot | The same AbortSignal reaches the reader; cancellation never writes a successful snapshot. |

Three controls make correct multi-file changes: a Decimal checkout refactor, an
all-settled job refactor that still propagates failures, and required organization
options passed consistently through the service and repository.

Before any model request, each safe baseline passed separate held-out checks. Buggy
heads passed their deliberately limited existing tests but failed the held-out checks;
correct heads passed both. Repositories had neutral names such as `case-01`. Answer
metadata and held-out tests were outside the reviewed source and fix feedback.
All example/generated-code execution was inside Docker, with its existing network,
memory and filesystem limits. The preparation helper ran trusted Git operations locally.

## Step 2: distinguish a service outage from a clean review

The first configured Gemini request returned **HTTP 503, temporarily unavailable**.
It produced a partial review, not a clean result. That attempt is excluded from quality
counts and retained in the evidence. A subsequent Gemini request was interrupted
before a complete response and is also not counted.

The saved automatic fallback handles quota errors, not arbitrary service errors.
For this experiment only, settings were copied in memory to select the already
configured **`opencode / deepseek-v4.1-flash-free`** directly. Saved Gemini-first
preferences, keys and billing settings were unchanged. No Ollama or paid model was used.

## Step 3: run reviews and investigate the false alarm

The first complete nine-case round found all six planted bugs, but only **two of three
correct changes** received zero warnings. The correct Python Decimal refactor received
a warning about fractional-price truncation. This application uses integer minor-unit
prices and quantities; the claimed weighted/fractional-input requirement was unsupported.

The recorded provider request showed why the evidence was incomplete: it included the
changed pricing functions and callers, but not the imported `CartLine` data definition.
A type mentioned only in an annotation is not necessarily a call-graph callee.

Added [`analysis/graph/import_context.py`](../src/sentinel/analysis/graph/import_context.py).
It follows existing resolved local import edges and exact named data imports, including
aliases. It does not choose an unrelated same-name class or expand external packages.
The ordinary source windows, overlap deduplication, redaction and character budget
remain in force. Python/JavaScript/TypeScript tests cover this behaviour and its limits.
A general review instruction now asks for a concrete supported failure rather than a
hypothetical new feature. There is no special suppression for money or Decimal findings.

We repeated **all nine reviews**, retaining the original round. Every counted review
had three reviewed source files, a completed AI stage and no review error. The repeat
found all six planted bug cases and left all three correct changes without warnings.
There were **seven findings for six bug cases**: the organization case had related
warnings at the service and repository boundaries. These are not counted as two seeded
bugs, nor silently merged with potentially independent authorization problems.

Both complete rounds used real free DeepSeek: **18 completed review executions on
nine applications**, not 18 independent examples. This is human contract/source grading
plus execution evidence, not an AI grading itself or a statistically calibrated benchmark.

## Step 4: repair a verification mistake without inventing proof

One correct JavaScript finding was marked uncertain because the explanation mentioned
the standard rejected-result property `reason`, which was not declared in this repository.
The verifier incorrectly treated that absent property as a hallucinated function.

Separated symbol evidence into
[`core/verification/symbol_evidence.py`](../src/sentinel/core/verification/symbol_evidence.py).
Unknown data/member references are now **neutral**, not supporting evidence and not proof
of nonexistence. Explicit invented free function calls still contradict the explanation;
existing hallucinated-function tests remain. Calls with arguments are also recognized.

The captured findings were replayed against their **original source snapshots** with
zero new AI calls. The affected job finding moved from uncertain to likely. This is
structural consistency, not independent proof of runtime behaviour. Original stored
review records are preserved; the replay is separate evidence.

## Step 5: generate fixes and challenge the result

The first six normal fix runs returned **four validated and two unverified**.
The initial TypeScript organization run used the built-in second attempt; these are
final outcomes per case, not first-attempt accuracy rates. Five
proposals passed the independent checks. Three were both validated and independently
acceptable and were applied normally. The pagination and organization proposals were
correct but added no reproducing regression, so they remained unverified.

The Python checkout proposal passed Sentinel's checks and corrected the top-level
receipt. However, it compensated in the service while leaving the public pricing
helper returning major units. That failed the prewritten helper contract. This is a
specific, observable contract miss, not a claim that the checkout output was still wrong.
The independent evaluator withheld Apply.

This exposed a context gap: fix generation saw current files and the finding but not
the original reviewed change, which contained a removed pricing-unit contract.

Added [`core/fixes/review_context.py`](../src/sentinel/core/fixes/review_context.py).
Normal `FixService` supplies the saved ChangeSet; the engine filters it again, restricts
it to current allowed context files and caps historical diff text at **16,000 characters**.
The prompt fences/redacts it as untrusted history. Only current file contents may supply
search text. Historical context grants no new edit permissions and needs no database
migration. Focused tests check service wiring, filtering, secret redaction, size bounds
and prompt-injection boundaries. The fix instruction now explicitly requests a new
regression when an allowed absent test path is available, and preserving public contracts.

We made **three clearly separated follow-up fix runs**, with no held-out test contents
or failure output supplied to the model. Pagination and organization then gained real
before/after regression tests, validated, passed the independent checks and applied.
The organization patch changed **two production files plus a new test**; strict
TypeScript compilation checked that the required repository option reached its caller.

**The Python retry still missed the helper contract.** Additional context and a better
prompt did not solve that model-quality limitation. Both original engine-validated
proposals remain in the raw evidence. After blind generation ended, the independent
failure was recorded as an evaluation-only failed check in the isolated database;
normal Apply then refused both proposals, and the example source stayed unchanged.
This external rejection is not a new general-purpose semantic checker in Sentinel.

Final Docker checks of the **actual five applied working trees** passed ordinary and
held-out tests, with selected fix/finding history `applied`/`fixed`. The related old
organization warning is historical review data; Apply changes the selected finding,
not every related finding automatically. The Sentinel source checkout was never an
AI fix-Apply target. Intentionally buggy public fixtures remain buggy for future tests.

## Step 6: close a multi-file validation boundary bug

A focused safety test reproduced another product bug: `apply_edits` returns touched
files, not the whole context. For a helper-only patch, `after.get(target)` was None.
Comparing the old target text with None incorrectly claimed the target itself changed.

The engine now requires explicit target membership **and** different contents before
using test-backed resolution. Both an omitted target and an explicit no-op target stay
unverified. Actual target edits still work. Failed static checks, incomplete analysis,
old/new test failures, unsafe paths and stale source hashes remain blocking.
This is a conservative text-change boundary, not causal proof of the claimed behaviour.

## Step 7: preserve privacy across renames

Final inspection of historical fix context found that the diff filter checked a file's
new name but not its old path. A rename from a protected/ignored name could therefore
carry old content under an ordinary source filename. No example source contained real
credentials; this was reproduced using authored marker values.

The shared filter now applies sensitive/ignored/generated path policy to both sides of
the rename. Public-to-public renames remain reviewable. `reviewed_fix_config` also
carries filtered/saved skip paths into graph-based fix context, so a skipped file cannot
return as a helper. Effective ignore lists are copied in memory; saved user settings
are not changed. Focused tests cover protected and public renames, old diff exclusion
and related-file selection. The required full suite was rerun after this repair.

## Reproduce and learn

See the [corpus guide](../evals/review_quality/README.md) and the walkthrough's cross-file
section. The corpus now has **24 cases**: the previous 15 plus these nine. Existing
corpus tests now verify every staged overlay file and absence of each held-out answer,
instead of assuming each example changes only one file. Fix context lists ordinary
tests and application files within the default eight-file limit; it never lists oracles.
Normal tests and CI use controlled providers and Docker, never live AI allowance.

## Automated verification

Required local checks passed: **631 tests passed, 27 PostgreSQL-dependent skips**,
with **93.51% overall coverage** and **97% core coverage**. All **34 real Docker tests**
ran, including all 24 corpus truth checks. Lint, formatting, application/bridge typing
and the preparation helper's strict typing passed. No failing test was removed.
The interrupted intermediate runs are retained as partial logs, not counted as passes.
Hosted GitHub CI additionally runs PostgreSQL, frontend and full Compose acceptance.

## What remains

- The observed pricing-contract miss is unresolved model quality. Do not equate a
  validated proposal with complete semantic correctness; inspect the patch and contracts.
- Repeat on larger real repositories, dependencies, more negative controls and multiple
  model runs. These 43–71-line applications do not establish production-scale accuracy.
- Explore related cross-file finding grouping without hiding independent defects.
- Existing browser, concurrent GitHub publication, load, retention and hosting work
  remain separate. See [PROJECT_STATUS.md](PROJECT_STATUS.md).

The local GitHub connection was also restored after initial reachability failures.
Its machine-local helper now retries signed setup pings within fixed attempt/time
limits, verified with controlled HTTP and a real GitHub HTTP 200 delivery. Only the
webhook route is public; the dashboard remains local and authenticated. This is a
temporary test tunnel, not permanent hosting or an availability guarantee.