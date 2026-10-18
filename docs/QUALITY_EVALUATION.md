# Python, JavaScript and TypeScript review/fix evaluation

Verified **19 October 2026 (India time)** with the installed Sentinel application,
actual Gemini/free DeepSeek responses, and the normal Docker fix sandbox.

**Result on this controlled corpus:** all **9 known bugs detected**, all **6 correct
changes left without warnings**, and all **9 final generated fixes validated, applied
to disposable examples and independently checked**. These are observed results on 15
small examples, not a general “100% accurate” claim about real repositories.

| Language | Known bugs detected | Correct changes without warnings | Applied fixes passing independent checks |
|---|---:|---:|---:|
| Python | 3 / 3 | 2 / 2 | 3 / 3 |
| JavaScript | 3 / 3 | 2 / 2 | 3 / 3 |
| TypeScript | 3 / 3 | 2 / 2 | 3 / 3 |

## Step 1: define the right answer before asking the AI

An AI's confidence score is not a measurement of correctness. Each invented example
therefore has a short behaviour contract, a safe base, a proposed change, normal tests,
and separate **held-out checks**. Held out means these checks stay outside the reviewed
repository and are never given to the model as source or feedback.

The safe base passed the independent check. Each intentionally broken change passed
its limited existing tests but failed the relevant held-out check. Correct changes
passed both. This distinguishes a real seeded bug from a broken experiment fixture.
All example tests and generated code ran in Docker, never directly on the host.

The public examples are in [`evals/review_quality/cases`](../evals/review_quality/cases).
Their `case.json` files are the answer key, not part of the materialized review input.
[`prepare_quality_case.py`](../scripts/prepare_quality_case.py) builds a fresh Git repo,
forces content-based staging and refuses existing destination folders. This is useful
learning material and an offline CI regression corpus; it makes no AI requests itself.

## Step 2: include bugs and correct code

| Example | What the check establishes |
|---|---|
| Python mutable default | Two calls without a list must not share labels. |
| Python binary-search boundary | A final single candidate and last item must be searched. |
| Python sibling path | `/tmp/uploads-backup` is outside `/tmp/uploads` despite the shared text prefix. |
| Python correct zero handling | An explicit zero survives a behaviour-preserving refactor. |
| Python parameterized SQL | Quotes and SQL-like names remain bound data. |
| JavaScript zero default | `0` must not become `3` through `value || 3`. |
| JavaScript async completion | The returned promise must wait for the save operations. |
| JavaScript SQL binding | User text goes in the driver's separate values array. |
| JavaScript numeric sort | A numeric comparator handles multi-digit numbers without mutating input. |
| JavaScript object copy | Object spread preserves the original and the explicit override. |
| TypeScript missing user | A non-null assertion cannot create a user that `find` did not return. |
| TypeScript boolean string | The literal string `"false"` must decode to false. |
| TypeScript SQL binding | A type annotation cannot make interpolated SQL safe. |
| TypeScript correct type guard | Null and property type are checked before access. |
| TypeScript correct await | Accessing the result's property after `await` is valid. |

The SQL driver examples test the binding boundary with a controlled driver double;
they are not live PostgreSQL exploit tests. The examples cover the listed behaviour,
not every input or every possible security property.

## Step 3: run normal reviews and inspect the findings

The initial diagnostic round used **13 Gemini** and **2 free DeepSeek** review responses.
Gemini returned a real quota/rate-limit error during the run; the existing automatic
fallback switched to DeepSeek. No billing setting or saved provider preference changed.
One extra review checked the repaired duplicate behaviour.

We then repeated all 15 cases with neutral repository names such as `case-01`. Names
such as `python_mutable_default` were not sent as repository metadata in this final
round. All 15 counted neutral-name reviews used actual free DeepSeek through OpenCode.
Every counted run had one reviewed file, a completed AI stage and no review error.

The findings' titles/explanations were manually compared with the contracts and withheld
execution results. This was not another AI grading itself, nor a loose “any warning
means success” keyword count. The final round produced one matching finding per known
bug and none for the six correct changes. Verification labels were **3 supported,
5 likely and 1 uncertain**. The path-prefix problem remained uncertain in the review
verifier even though the independent behaviour check demonstrated it; the report does
not relabel every detected bug as statically proved.

One attempted neutral-name review had an empty staged diff and made no AI call. Its
zero warnings were **excluded**. The intended change was explicitly restaged and the
case was reviewed again successfully. The helper now refuses an empty staged snapshot.
The empty-review summary also says no code was assessed, instead of presenting a
clean-change headline. No system-wide Git settings were changed.

## Step 4: generate fixes, then challenge them

The normal fix generator produced proposals for all nine bugs using actual free
DeepSeek. It permits up to two attempts; the JavaScript SQL and TypeScript missing-user
cases used two attempts.
The model's final proposals passed the independent held-out checks. However, the first
validation round exposed real product problems: **3 validated, 5 unverified, 1 failed**.
Those original results are retained in the evidence, not replaced by the final results.

There are three different kinds of evidence:

1. **Existing tests:** they must pass before and after, so ordinary behaviour is preserved.
2. **New regression tests:** the same generated test must fail on original code and pass
   on the patch. Merely adding a test that passes on both versions proves no bug was fixed.
3. **Independent held-out checks:** authored outside the model's context, used here to
   check whether the proposed behaviour actually matches the example's contract.

The six previously blocked proposals were revalidated through the repaired normal
engine **without generating replacement patches or making new AI calls**. All checks
passed. Normal `FixService.apply` then wrote the disposable files. Every actual applied
example passed its ordinary suite and held-out checks, and database history records
its fix as `applied` and its finding as `fixed`. The three already validated proposals
also passed these final checks. The Sentinel source project was never a fix-Apply target.

## What was repaired, and why

### Duplicate reports for one mutable default

The AI said “mutable default argument shares state”; Ruff reported B006 with different
wording. The same issue appeared twice because AI normalization lacked the existing
`mutable-default` concept. Added that narrow concept pattern in
[`findings/normalize.py`](../src/sentinel/core/findings/normalize.py). Existing overlapping
location and concept rules now merge the reports while preserving both origins/evidence.
The similarity threshold was not lowered; nearby unrelated bugs remain separate.

### JavaScript/TypeScript regression output

[`fixes/regression.py`](../src/sentinel/core/fixes/regression.py) previously looked only
for pytest's `N failed` text. Node's built-in runner uses **TAP**, a text format listing
each test and its result. Genuine Node failures were being rejected as missing evidence.

The validator now recognizes completed Node test-case failures, including a TypeError
inside a named test callback. A missing import that prevents loading the test file is
still rejected, as are cancelled tests, wrong exit codes, timeouts, mixed incomplete
runs and unsupported reporters. Pytest collection errors also remain failures; its
summary is parsed without confusing assertion-message text with collection status.
Real Docker tests cover assertions, callback exceptions and failed module loading.

### Logic fixes with strong test evidence but no linter rule

A linter can identify some patterns, such as interpolated SQL. It usually cannot know
that this application's zero means “disable retries.” Requiring a matching linter rule
for every fix left useful, tested logic fixes permanently unverified.

The engine now permits **test-backed resolution** when static resolution is unavailable,
the targeted source file changed, and the same new regression really fails before and
passes after in Docker. Existing tests, complete before/after static analysis and the
no-new-issues check must still pass. A failed static recheck cannot be overwritten by
a passing test; changing only another context file cannot confirm the target. With no
new reproducing test or an unsupported framework, the proposal remains unverified.
The check detail explicitly identifies this evidence as `test-backed`.

This is reproducible evidence about tested behaviour, not proof of every sentence in
an AI explanation or every possible program input. Apply still requires validation,
unchanged source hashes, safe paths and absent new-file destinations.

### Empty review clarity and reproducible samples

[`review/summary.py`](../src/sentinel/core/review/summary.py) now explicitly identifies
empty/fully filtered reviews as unassessed. The sample helper uses fresh text copies,
portable shell newlines and forced Git content hashing; test cases cover a real staged
change, withheld answer files and preservation of an existing destination folder.

## Reproduce and learn from it

Start with [`evals/review_quality/README.md`](../evals/review_quality/README.md). Prepare
one example under a neutral directory name and use Sentinel's ordinary review/fix CLI.
The `--check` helper option validates fixture truth through Docker without contacting
an AI. Ordinary pytest/CI tests use fixtures and controlled provider responses, not
live model quotas. Application TypeScript is checked strictly; the examples transpile
Node test files using the installed compiler and run them with Node's built-in test runner.
No new test framework or local model download is required.

The walkthrough links the source and explains why the three test layers differ. The
design notes record the trade-off behind test-backed resolution. Raw review records,
initial/final fix checks, case grading and independent Docker results are available in
the exported quality evidence archive. Automated regression results are recorded below.

## Automated regression verification

Required local checks passed: **590 tests passed, 27 PostgreSQL-dependent skips**,
**93.42% overall coverage** and **96% core coverage**. All **25 Docker tests** ran,
including the 15 fixture truth checks and three Node regression failure cases.
Lint, formatting and application/bridge/helper type checks passed. The existing empty
review test now requires the clearer unassessed headline and verifies zero AI calls;
no failing test was removed. GitHub CI additionally runs the PostgreSQL-dependent
checks, frontend checks and full Docker/Compose acceptance.

## What this does and does not establish

This is a repeatable small-corpus acceptance result for Sentinel's complete pipeline:
AI plus context, static hints, verification and fix gates. It is not a Gemini-versus-
DeepSeek model comparison, a calibrated confidence score, or representative precision/
recall on large real projects. Contracts are explicit, bugs are seeded, dependencies are
minimal and the changes are small. Results can vary on another model run.

Next quality work should add realistic multi-file changes, larger dependency-heavy
repositories, more subtle clean controls, adversarial cases, multiple runs and failure
examples. Operations, concurrent GitHub publication races, browser resilience and load
work remain separate. See [PROJECT_STATUS.md](PROJECT_STATUS.md).
