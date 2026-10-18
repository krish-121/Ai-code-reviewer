# Sentinel: live Gemini verification

Date: **18 October 2026**. Model: **gemini-3.8-flash**. OpenCode fallback: **off**.

## Result

The configured Gemini key works through Sentinel. A complete review succeeded, and
Gemini proposed a SQL-injection fix that passed independent before/after testing in
Docker. The fix engine correctly retained its conservative **unverified** verdict
because the existing test suite already failed before the proposal. No patch was
applied to the owner's Sentinel repository or the original test repository.

## What ran

| Check | Observed result |
|---|---|
| Provider connection using invented `average.py` | Gemini correctly identified division by zero for an empty list; valid structured response in 6.675 seconds |
| Full CLI review of a disposable SQLite project | All eight pipeline stages completed; total review time 35.196 seconds; no errors |
| Finding | One surfaced, HIGH-severity SQL-injection finding at `lookup.py:8` |
| Independent support | Sentinel's SQL rule, Ruff S608 and Bandit B608 corroborated the model's claim |
| Fix generation | Gemini replaced string interpolation with a parameterized SQLite query |
| Sandbox analysis | Syntax passed; all analyzers completed; three injection reports became zero; no new issues |
| Original fix verdict | Unverified: existing tests already failed before the patch, so the automatic tests gate withheld validation |
| Separate Docker diagnosis using the exact proposed edit | Original: two tests ran, one failed. Patched copy: both passed |

The full review ran diff parsing, file filtering, graph building, context extraction,
static analysis, AI review, claim verification and finalization. Its recorded provider
is `gemini`, model `gemini-3.8-flash`; the SQL finding combined local and AI evidence.

## Why the patch remains unverified

The deliberately introduced vulnerability already broke the example's security test.
Sentinel's current automatic validation policy requires the existing suite to pass
before and after a patch. It therefore refused to call this proposal validated, even
though analysis confirmed the SQL warnings disappeared.

The separate diagnosis ran the same two tests on original and patched copies inside
Docker. It confirmed the exact proposed edit fixes the demonstrated vulnerability.
This diagnosis did **not** rewrite the saved fix verdict or bypass the Apply guard.
Supporting repairs when a project's baseline tests already fail would be a separate,
carefully tested policy change.

## Usage and privacy

- The connection example reported 1,088 input and 195 output tokens.
- The full review reported 1,683 input and 174 output tokens.
- Fix generation used additional Gemini quota; this outcome record does not contain
  a complete token ledger. These figures are not the account's remaining allowance.
- Model requests contained only invented examples. The owner's project was not
  uploaded as review input, and no key is included in this report or evidence archive.
- The key remains in the owner's local WSL Sentinel configuration, outside the source
  repository. No billing setup, subscription purchase or OpenCode installation occurred.

## Scope and remaining work

The tests used Sentinel's prepared working copy in
`C:/Users/Krishna/Documents/Codex/2026-10-18/i-was-preparing-ai-code-reviewer-3/work/sentinel`,
the existing WSL Python runtime, an isolated test database, and the existing Docker
sandbox image. Runtime settings now select Gemini 3.8 Flash with fallback disabled.

This verifies one live provider and one small Python workflow. It does not establish
accuracy across large repositories, browser acceptance with a live model, GitHub
acceptance, or live OpenCode fallback. Direct OpenCode free-model requests previously
returned a restriction saying free-tier inference is only available within OpenCode.
Its official application route remains untested and has not been installed.

The setup helper now uses the actual CLI module,
`python -m sentinel.apps.cli.main`; `python -m sentinel` is not supported by the
current package. The hidden key-entry flow was tested separately with a dummy key.

## Evidence

The accompanying `Sentinel-Gemini-Evidence.zip` contains the live connection response,
full review, proposed fix with validation checks, and separate Docker test results.
It contains no API key or private configuration file.
