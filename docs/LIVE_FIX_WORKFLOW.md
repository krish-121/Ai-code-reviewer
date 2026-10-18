# A real AI review, validated fix and Apply

Verified on **18 October 2026**, using the installed main checkout at
`D:/sentinel-final-v2/sentinel`. This completes the local live-AI fix acceptance step.
GitHub and the full deployed web workflow are separate remaining checks.

## What the two Docker environments do

An **image** is a saved setup containing a program and its tools. A **container** is
a running copy of that setup. Neither image here contains downloaded AI model weights.

| Environment | Job | Internet | Access to files and keys |
|---|---|---|---|
| OpenCode bridge | Send a request to the online free DeepSeek model after a Gemini quota error | Yes | Receives bounded prompt text and a separate local bridge token. No project mount, Gemini key or Docker socket. |
| Fix sandbox | Check and test a proposed change | Disabled for validation | Receives a filtered temporary project copy. No vendor keys or Docker socket. The original project is not mounted with the configured `copy` transport. |

The bridge helps obtain an answer. The fix sandbox checks that answer. These are
different jobs, so their permissions and images are deliberately separate.

## 1. Prepare the normal fix sandbox

The saved configuration previously named `sentinel-sandbox:latest`, but that image
was missing. Earlier checks used a differently named test image. We built the normal
image from the current [`Dockerfile.sandbox`](../Dockerfile.sandbox).

It contains Python, Node, pytest and the trusted analyzers. Building it may download
these development tools. The resulting image is about **706 MB**. No local AI model,
paid account or AI credits are needed for this image.

For a fresh setup, with Sentinel installed and Docker working, run in **Ubuntu/WSL**:

```bash
cd /mnt/d/sentinel-final-v2/sentinel
docker build -f Dockerfile.sandbox -t sentinel-sandbox:latest .
sentinel config set sandbox docker
sentinel config set sandbox_image sentinel-sandbox:latest
sentinel config set sandbox_transport copy
```

These settings are already saved for the owner's existing WSL runtime. They use the
same private user configuration as the Gemini connection; no key needs to be pasted
again. The settings writer preserves the other settings and private file permissions.
Its missing `sandbox_transport` entry was added, with a regression test for saving a
valid value and rejecting an invalid value without changing the file.

**Why `copy`?** Windows Docker Desktop and Ubuntu can use different names for the same
folder. Sentinel sends a filtered archive into a temporary container workspace, which
avoids that path mismatch. The workspace disappears when the container ends. Source
files change only at the later Apply step.

The sandbox uses a read-only system filesystem, disabled networking, a 1 GB memory
limit, one CPU, a process limit, dropped Linux capabilities and a timeout. A trusted
project needing extra test dependencies needs a prepared custom image; generated code
does not install packages during validation.

## 2. Review a deliberately broken example

We created a new disposable local Git repository:
`/var/tmp/sentinel-full-live-3q54db6a`. It has no GitHub remote or user project files.
The original committed function used SQL parameters. A staged change deliberately
replaced those parameters with a formatted SQL string:

```python
return connection.execute(f"SELECT id, name FROM users WHERE name = '{name}'").fetchall()
```

That lets specially crafted input change the meaning of the SQL query. Its two
existing tests cover ordinary names and missing names. Both pass before the fix,
showing why an apparently green test suite can still miss a security bug.

We used the normal CLI command `sentinel review --staged --format json` with the
saved Gemini-first configuration. Only the example's database/cache locations were
redirected to keep its history separate. No provider or sandbox override was needed.

- Actual model: **Gemini `gemini-3.8-flash`**; DeepSeek fallback remained enabled.
- Review: `R-d92914d7e9`; all eight stages completed without errors, in **17.661 s**.
- Usage reported for review: **1,683 input / 213 output tokens**.
- Finding: `F-57d5249522`, high-severity SQL injection at `lookup.py:8`.
- Local Sentinel, Ruff and Bandit independently supported the AI finding.

Gemini did not report a quota error in this run, so this particular workflow did not
use DeepSeek. The earlier controlled-quota test with real DeepSeek is documented in
[DEEPSEEK_FALLBACK_VERIFICATION.md](DEEPSEEK_FALLBACK_VERIFICATION.md).

## 3. Generate the fix without changing the example

`sentinel fix F-57d5249522` asked the real model for a small search/replace proposal.
Gemini produced the following fix and a new security test:

```python
return connection.execute("SELECT id, name FROM users WHERE name = ?", (name,)).fetchall()
```

Here, SQL structure and the supplied name travel separately. A name containing SQL
punctuation stays a value instead of becoming another part of the SQL command.

The proposed new file was `tests/test_lookup_regression.py`. It tests the malicious
input `' OR '1'='1`. Sentinel offered that exact absent test path; the model did not
receive permission to create arbitrary files.

Fix **`X-756e0181ec`** used Gemini on its first generation attempt. We confirmed that
the example's original source was unchanged after generation and validation.

## 4. Validate before allowing Apply

Sentinel checked temporary copies through its normal fix engine:

| Check | Result and meaning |
|---|---|
| Patch application | The exact search text matched; two permitted files could be patched. |
| Syntax | Both proposed Python files parsed. |
| Analysis | All configured analyzers completed inside Docker. |
| Finding resolved | The three SQL-injection diagnostics disappeared: **3 → 0**. |
| No new issues | No new medium/high diagnostics from Sentinel, Ruff, mypy or Bandit. |
| Existing/project tests | The baseline passed, and the patched suite passed inside Docker. |
| New regression test | It failed against the buggy code and passed against the patched code, inside Docker. |

All seven checks passed, so the saved proposal became **validated**. We did not lower
the validation policy or bypass a missing check. The earlier Gemini-only example
remains historically unverified because its existing suite already failed; this new
example demonstrates the normal passing-baseline path.

## 5. Apply, then verify the saved result

The normal [`FixService.apply`](../src/sentinel/services/fixes.py) method wrote only
`lookup.py` and `tests/test_lookup_regression.py` in the disposable repository. This
is the method used by the CLI and the web Apply route. It rechecks the stored verdict
and original file hashes before writing.

After Apply:

- The full example suite passed: **3 tests**, inside Docker.
- A separate trusted Docker probe checked an ordinary name, SQL-injection input and
  an apostrophe-containing name; all passed.
- The stored fix status became **applied** and the finding status became **fixed**.
- Finding history recorded both successful generation and application.

No AI-generated code was executed on the host. Apply wrote only the invented example;
the only Sentinel source change was support for saving the sandbox transfer setting.

## 6. Normal app startup and limits

We also started the actual local `sentinel serve` command with its ordinary in-process
worker and the example database. `/api/health` reported Gemini, SQLite, an empty queue
and status `ok`; the web page returned HTTP 200. The temporary server was then stopped.
The saved normal sandbox was available throughout this check.

This is a startup check, not a browser interaction or a fresh Compose acceptance run.
The live review/fix/Apply sequence above used the CLI and shared application services.
One SQL example does not measure accuracy across projects, languages or models.
Keep Docker Desktop running for fix validation and the optional OpenCode bridge.
Ollama is optional and was not involved.

## 7. Project checks after the setting change

- Full Python suite: **518 passed, 27 PostgreSQL checks skipped**, in 211.65 s.
  All seven actual Docker integration cases ran against the normal sandbox image.
- Overall branch-inclusive coverage: **93.36%**; core coverage: **96%**.
- Ruff lint/format checks passed; strict typing passed for 151 Sentinel modules and
  the three standalone bridge modules. The focused setting/transfer checks also passed.
- The final sandbox image ID is
  `sha256:8b06ccc7f4a077991e6e145b1fab2e7586b7ddde46fb5478142ea466e8d715f7`.

The first suite invocation omitted the Node analyzer environment and failed 11 TS/JS
checks; an intermediate invocation was stopped before completion to add the WSL Docker
test transfer flag too. The final complete run above includes both prerequisites and
passes. No product logic was changed to suppress those checks. PostgreSQL was not
retested in this continuation; its earlier acceptance remains recorded separately.

For a future real project, review the proposed diff and its checks before Apply. The
normal commands are `sentinel review --staged`, then `sentinel fix F-… --apply`.
The latter asks for confirmation after validation; replace `F-…` with a current finding
from that project's review. This report's IDs belong to its separate example database.

Source trace: [CLI review](../src/sentinel/apps/cli/review_commands.py) →
[ReviewService](../src/sentinel/services/reviews.py) →
[CLI fix](../src/sentinel/apps/cli/fix_command.py) →
[FixEngine](../src/sentinel/core/fixes/engine.py) →
[DockerSandbox](../src/sentinel/sandbox/runners.py) →
[validation](../src/sentinel/core/fixes/validation.py) and
[regression checks](../src/sentinel/core/fixes/regression.py) →
[FixService.apply](../src/sentinel/services/fixes.py) →
[confined file writes](../src/sentinel/core/fixes/apply.py).
