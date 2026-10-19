# Python pricing fix: investigation and retest

19 October 2026. This follows [the original multi-file evaluation](MULTIFILE_QUALITY_EVALUATION.md).
Its two rejected pricing proposals and original scores remain historical evidence.

## What failed, in everyday language

The example stores money as an integer number of minor units: 1299 means 12.99 in a
currency with 100 minor units per major unit. This avoids accidentally mixing the two
representations. A **contract** is the meaning callers can rely on, such as
“`line_total` returns minor units.” Decimal arithmetic itself is not a bug.

The changed helper divided by 100. The checkout service still expected minor units
and converted the result to an integer. For two items costing 1299 each:

| Stage | Broken change | Old compensation patch | New root-cause repair |
|---|---:|---:|---:|
| `line_total` | 25.98 | 25.98 | 2598 |
| Checkout subtotal | 25 | 2598 | 2598 |
| Public helper contract preserved? | No | No | Yes |

The old patch multiplied the subtotal back by 100 in the service. It repaired the
final answer while leaving other users of the helper exposed to the wrong answer.
That is why checking only the checkout screen was insufficient.

## Why Sentinel accepted the old proposal

1. The review traced the mismatch correctly but cited `app/service.py:8`, where the
   bad value was consumed. It suggested either restoring minor units or converting
   back in the caller “if” major units were intended. No such new requirement existed.
2. Both fix attempts chose that suggested caller workaround. The second already had
   the original diff, so this was not just missing historical context.
3. Ordinary tests covered empty carts, shipping and validation. The generated tests
   covered quote/checkout totals, but did not assert the public pricing helper's result.
4. Parsing, static checks and those tests all passed. The separate, prewritten helper
   contract test failed. The evaluator withheld both proposals. That independent
   rejection was not a built-in check magically available on arbitrary repositories.

## Changes in Sentinel

- Review instructions now ask for the first changed operation that breaks an
  established contract, with its downstream effect explained. They discourage a
  workaround justified by an undocumented hypothetical requirement.
- Fix instructions label the review suggestion an **unverified hypothesis**. They ask
  the model to check pre-change contracts, test an affected public producer directly
  as well as its consumer, and explain the preserved contract in the patch summary.
- If a new regression passes but only a related helper changes, the unverified check
  now explains why: the cited source file did not change. It recommends a fresh review
  to locate the root cause. The conservative validation rule and Apply restrictions
  are unchanged; there is no cosmetic target edit or automatic approval of helpers.
- An offline Docker regression replays the actual old and new production edits with
  the **same newly generated helper/caller tests**. The old shortcut fails normal
  tests/regression checks; the root repair validates. CI needs no AI key for this test.

Trace the code in [`ai/prompts/__init__.py`](../src/sentinel/ai/prompts/__init__.py),
[`core/fixes/regression.py`](../src/sentinel/core/fixes/regression.py),
[`test_pricing_contract.py`](../tests/integration/test_pricing_contract.py) and the
[captured patch pair](../evals/review_quality/regressions/pricing_patch_pair.json).
This is a small instruction/evidence improvement, not a new semantic-proof engine.

## Live retest, step by step

We used the already configured official OpenCode bridge and **free DeepSeek
`deepseek-v4.1-flash-free`**. The evaluation selected it explicitly in memory; this was
not a Gemini quota-fallback event. Saved Gemini-first settings, credentials, App
permissions and the normal review database were not changed. No paid model or new
software was installed.

1. **Prepare fresh copies.** Use neutral temporary Git repository names and the same
   original buggy change plus its correct Decimal companion. Verify the safe base and
   correct change pass separate tests, while the buggy head fails them. Ordinary
   buggy-head tests still pass, confirming the original coverage gap.
2. **Review normally.** `ReviewService` completes all stages on both examples. The
   buggy review produces one finding at `app/pricing.py:6`, the actual division by 100.
   The correct Decimal change receives no findings. Both real calls have no errors.
3. **Generate normally.** `FixService` receives the saved finding and filtered history.
   DeepSeek restores integer minor units in `line_total`/`subtotal`, removes the now
   redundant service cast, and creates three regression tests covering helpers,
   quote/receipt amounts and quantity scaling.
4. **Validate in Docker.** All seven normal gates pass: apply, syntax, complete
   analysis, test-backed finding resolution, no new serious issues, ordinary tests,
   and new tests failing before/passing after. No check status is overridden.
5. **Challenge independently.** The original withheld tests also pass: **12 tests**
   including ordinary, generated and independent checks. Their text/output was never
   included in either generation request or retry feedback.
6. **Apply normally.** Only after both checks pass, normal Apply writes the two source
   files and new test into the disposable example. The actual applied tree passes
   again, and the isolated database records fix `applied` / finding `fixed`.
7. **Test supported edge cases.** After generation, run 63 combinations of integer
   unit amounts, quantities and shipping values, including zero, one minor unit and a
   large integer; also mixed and empty carts. Assert exact amounts and integer types.
   All pass in Docker. These extra checks were written after generation and are not
   counted as prewritten blind tests.

Fresh review: `R-7859e7a89b`; finding: `F-0a45a82535`; applied fix: `X-b7873873e6`.

### What happens to the older saved review?

We also gave the original downstream finding, including its misleading suggestion,
to the improved fix generator on a separate untouched copy. It produced a correct
helper repair and producer/caller tests; independent checks passed. Because it left
the originally cited service file unchanged, normal validation kept it **unverified**.
Actual Apply refused it and the workspace stayed unchanged. That is a safe outcome.

The workflow for this situation is **fresh review → root-cause finding → generate fix →
validate → inspect → Apply**, as demonstrated above. Do not edit a comment merely to
make the target-change check green. Older stored results are not silently rewritten.
The improved explanation is covered by unit tests; the captured live legacy outcome
predates that wording-only change and retains its original generic message.

| Check | Observed result |
|---|---|
| Fresh buggy review | Root pricing defect detected, one finding |
| Correct Decimal companion | No findings |
| Fresh fix | Validated, independent tests passed, normal Apply succeeded |
| Fix from original saved finding | Independent tests passed; unverified and not applied |
| Actual applied source/history | Ordinary + independent checks passed; applied/fixed |
| Additional integer scenarios | 63 plus mixed/empty carts passed |
| Offline captured-patch regression | Old shortcut fails; corrected patch validates |

## Verification and limits

Required local checks: **633 passed, 27 PostgreSQL skips**; all **36 Docker tests** executed. Overall/core coverage: **93.55% / 97%**. Ruff lint/format, application typing (154 source files), strict bridge typing (3 files) and the strict case-preparation helper check passed. The normal sandbox image was rebuilt. No frontend source changed.

The original two bad proposals remain recorded as failures. This follow-up repairs
the observed case; it does not retroactively change the original six-case fix score.
One fresh buggy review and one clean companion, plus a second fix from the old finding,
are a focused retest of a known case, not independent population accuracy measurements.

Sentinel still cannot infer every unstated business rule. Stronger instructions make
the model more likely to generate useful tests, but do not ensure it always will.
The Docker regression proves rejection of the captured shortcut **when those stronger
tests are present**; it does not automatically add hidden business tests to other
repositories. Preserve project contract tests and inspect generated patches/tests.
Broader causal validation of dependency-only fixes remains a separate design task.
