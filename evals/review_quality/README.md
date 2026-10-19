# Small review-quality corpus

The corpus contains 24 invented changes across Python, JavaScript and TypeScript:
the original 15 small cases (nine bugs, six correct changes), plus nine multi-file
applications (six bugs, three correct changes). They are learning examples and regression cases.
The live results and limits are in [QUALITY_EVALUATION.md](../../docs/QUALITY_EVALUATION.md).

Each case contains:

```text
case.json   expected behaviour and test commands — the answer key
base/       safe source, existing tests and normal project configuration
change/     source overlay containing a bug or a correct change
oracle/     separate behaviour checks, withheld from the model
```

The existing tests deliberately omit one edge case in the buggy examples. They pass
before the fix. The withheld tests fail on a buggy change and pass on the safe base.
Correct changes pass both. An offline Docker test checks this contract for every case.

## Try one example

Use the installed environment and Docker setup described in the main README. From the
Sentinel checkout, in Ubuntu/Linux:

```bash
python scripts/prepare_quality_case.py javascript_zero_default /var/tmp/review-case-01 --check
cd /var/tmp/review-case-01
sentinel review --staged --format json > /var/tmp/review-case-01-result.json
```

The first command creates a fresh repository, checks the safe/changed behaviour in
Docker, and stages a real source change. It makes no AI request. The second command
reviews the change using your saved provider and consumes that provider's allowance.
Choose a neutral destination such as `review-case-01` so the directory name does not
reveal the expected bug to the model. Use a new destination for another case; existing
directories are refused to preserve your work.

Read the JSON finding and compare its explanation with the contract in the original
case folder. Check the actual file/line and AI-stage status; an empty diff is not a
successful clean review. False alarms, missed bugs and duplicate reports are different
outcomes and should be recorded separately.

For a detected bug, use its actual `F-...` identifier with `sentinel fix F-...`.
Inspect the patch and every check. `sentinel fix F-... --apply` only writes a validated
proposal and refuses stale source files. Use disposable examples while learning.

## Interpreting the results

A passing existing suite alone does not prove a fix. A new regression must fail on
original code and pass after the patch. The separate oracle is an additional check;
do not copy it into the model's repository before review or generation.

Python uses pytest. JavaScript uses Node's built-in test runner. TypeScript's example
`test.sh` first checks the application with strict TypeScript, then transpiles the Node
test files using the installed compiler and executes them. The test transpilation uses
`--noCheck` to avoid downloading Node declaration packages; it does not disable the
application's strict type check. The Node test runner is the runtime authority for
these small tests. Everything executes inside the normal sandbox when checking fixes.

These fixtures do not need paid credentials, network access inside the sandbox, or a
local model. Live reviews do require an available configured provider. The default
test suite and CI never call a live AI service.

## Cross-file examples

Names containing `multifile` have six application files and three changed source files.
They exercise checkout units, cumulative stock reservations, background-job failure
propagation, page-to-offset conversion, organization-scoped invoices and cancellation.
These are still small, dependency-light learning applications, not large real products.
See [MULTIFILE_QUALITY_EVALUATION.md](../../docs/MULTIFILE_QUALITY_EVALUATION.md)
for actual sizes, both model rounds, the observed false alarm and generated-fix results.

Try `python_multifile_checkout`, `javascript_multifile_jobs` or
`typescript_multifile_organization` with the same preparation command above. The helper
stages every source file in `change/`; `case.json` and all `oracle/` checks stay outside
the reviewed repository. Fix context explicitly lists the six application files and
ordinary tests, within the default eight-file limit; it never includes the oracle.

The offline suite validates every case. It does not assert that a future model run
must reproduce today's result, and does not consume free-provider allowance in CI.
