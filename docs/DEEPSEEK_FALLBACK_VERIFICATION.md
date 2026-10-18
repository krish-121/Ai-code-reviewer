# Gemini quota fallback to free DeepSeek

Updated **18 October 2026**. Installed in the main Sentinel folder and enabled in the existing WSL runtime. Gemini remains the first choice. When it reports a quota
or rate limit, Sentinel automatically uses **DeepSeek V4.1 Flash Free through official
OpenCode**. GLM is excluded after its earlier service failures.

## How it works, in everyday language

1. **Prepare a review.** Sentinel reads the change, chooses relevant context and removes
   secrets using its existing filtering rules.
2. **Ask Gemini first.** A successful Gemini answer follows the normal review process.
3. **Recognize a limit.** Google signals a rate/quota problem with HTTP 429. Sentinel
   switches immediately and records why. Wrong keys, refusals and other errors remain
   visible; they do not initiate this quota fallback.
4. **Use a local messenger.** Sentinel sends the prepared text to a small authenticated
   bridge running inside Docker. The bridge starts the official OpenCode application,
   which contacts the online DeepSeek model.
5. **Check the answer.** The response still passes Sentinel's JSON schema, claim checks
   and ranking. The saved review shows the actual provider/model and fallback reason.
6. **Avoid wasting quota.** Gemini normally waits five minutes after a limit, or longer
   if Google's retry instruction requires it, capped at a day. Identical reviews can
   reuse a cached answer. After the waiting period, a new request tries Gemini again.

Docker runs the messenger separately from your main files. We downloaded the OpenCode
application and a small Python environment, not DeepSeek model weights. The new runtime
image is about **443 MB**; the earlier experimental image also remains cached. Docker's
shared layers mean these sizes are not exact additional disk usage.

## What was tested

| Check | Observed result |
|---|---|
| Ordinary real Gemini-first CLI review | Completed with Gemini 3.8 Flash; fallback did not replace the successful answer |
| Controlled Gemini quota response followed by real DeepSeek | Exactly one simulated Google 429, one real DeepSeek call; all eight review stages completed |
| Finding and persistence | SQL injection detected; saved provider `opencode`, model `deepseek-v4.1-flash-free`; local analysis corroborated the HIGH finding |
| Repeat of the same review | Reused persisted cooldown and cached answer; zero additional Gemini or DeepSeek calls |
| Command-permission diagnostic inside Docker | OpenCode automatically rejected the command; the test file was not created |
| Missing local password, paid model, oversized token budget | Rejected with 401, 400 and 400 before inference |
| Container inspection | No host mounts or vendor credential variables; read-only image, unprivileged user, loopback port only |
| Python regression suite | **517 passed, 27 skipped**; **93% overall coverage, 96% core coverage** |
| Lint and strict typing | Passed for Sentinel and the standalone bridge |
| Optional Compose configuration | Validated; existing database dependencies and review/API workers' lack of Docker sockets preserved |

**The quota condition was simulated; the DeepSeek inference and full review were real.**
We did not deliberately exhaust your Google allowance. The final controlled switch took
13.578 seconds; the cached repeat took 1.347 seconds. The ordinary Gemini review was a
separate real Google request. The test repositories contained invented code only.

The 27 skipped tests need a PostgreSQL test database. This continuation exercised SQLite
persistence and the existing Docker sandbox tests. It did not rerun a complete Compose
deployment, create a GitHub repository, or perform live GitHub App acceptance.

## Keys, passwords and permissions

Your Gemini key stays in Sentinel's private runtime configuration and goes only to
Google. OpenCode receives no Gemini key, billing credentials, browser login, shared
project directory or Docker socket.

The setup helper generated a **separate local bridge token**. It is just a password
between Sentinel and its messenger, saved outside Git. The child OpenCode process does
not inherit even that token. No OpenCode account or payment method is required for the
tested free-model route.

OpenCode's gateway rejected the earlier mode that disabled every tool. The working
official CLI keeps tools present with approval required; noninteractive requests are
automatically rejected. The bridge also rejects any tool-bearing answer. This behaviour
was checked with a real attempted command inside Docker.

## Running it later

Keep **Docker Desktop running** when you want the DeepSeek fallback available. The
bridge is configured to restart with Docker unless explicitly stopped. Starting an
already-open Sentinel process again lets it load the updated code and settings.

From the Sentinel checkout in its Linux/WSL environment:

```text
python scripts/opencode_bridge.py status
python scripts/opencode_bridge.py start
```

Use `start --build` after changing the bridge source or when building its image for the
first time. It recreates only the helper's labelled container. The separate Windows
`Start-DeepSeek-Fallback.cmd` helper performs this setup in the existing WSL runtime.

To return to Gemini only and stop the bridge:

```text
sentinel config set free_fallback false
python scripts/opencode_bridge.py stop
```

The source walkthrough and setup guide were updated in Sentinel's `docs` folder. The
saved `Sentinel-WALKTHROUGH.md` copy includes section 6.1 with the flow, file links and
reasons for the design. `Sentinel-Free-AI-Setup.md` contains the complete operating guide.

## Limits that still matter

Free services can become unavailable or change their offers. A successful small test
does not establish accuracy on every project or an unlimited quota. DeepSeek's findings
remain suggestions checked against the available evidence.

The bridge permits one active call, uses a 75-second CLI deadline and 1 MiB input/output
budgets, and configures an output limit up to 4,096 tokens. OpenCode adds prompt overhead.
Its cached input and reasoning tokens are included in Sentinel's existing token counters;
those counters do not measure remaining free allowance or chargeable usage on cached runs.

If the bridge or DeepSeek is unavailable after Gemini reaches its limit, Sentinel retains
local findings and reports the incomplete AI stage. Generated patches still require the
existing Docker validation and Apply rules. No generated patch was applied by these tests.
