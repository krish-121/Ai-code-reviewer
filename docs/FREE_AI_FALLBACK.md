# Gemini with automatic free DeepSeek fallback

Sentinel tries Gemini first. If Google returns **HTTP 429** (rate limit or quota
exhausted), Sentinel asks **DeepSeek V4.1 Flash Free through official OpenCode**.
GLM is excluded because both live tests returned service-unavailable errors.
This option is disabled by default; enabling it permits sending the same redacted
review/fix context to OpenCode's online service.

## 1. Understand the pieces

| Piece | Purpose | Where it runs |
|---|---|---|
| Gemini provider | Normal first choice, using your Google AI Studio API key | Sentinel |
| Fallback provider | Recognizes quota errors, selects DeepSeek and records the reason | Sentinel |
| OpenCode adapter | Sends the prepared review text to the local bridge using HTTP | Sentinel |
| Bridge | A small messenger that starts the official OpenCode command | Docker |
| DeepSeek | The AI model answering the review | OpenCode's online service |

An image is a saved application setup; a container is a running copy. The bridge
image includes Python and the OpenCode application, not DeepSeek model weights.
Internet access is needed for inference. Docker Desktop must be running when the
fallback is needed. Gemini can still answer when the bridge is stopped.

## 2. Start the bridge

Use the same Linux/WSL environment where Sentinel is installed. From the Sentinel
source checkout, with its virtual environment active:

```text
python scripts/opencode_bridge.py start --build
```

This builds only `tools/opencode_bridge/`, not the whole project. The helper creates
a random **local bridge token** and saves it privately in Sentinel's user config.
That token is a password between Sentinel and its local messenger. It is not an
OpenCode account key, a Gemini key, or a paid-service credential. You do not need to
paste it into chat. WSL configuration is separate from native Windows configuration.

The helper publishes only `127.0.0.1:4097`, uses no shared project folder or Docker
socket, and gives the container no vendor credentials. Its image filesystem is read
only and the process is unprivileged. Each request has its own temporary session and
cache directories, which are removed afterward. Its child OpenCode process does not
inherit even the local bridge token.

## 3. Enable the automatic switch

Your Gemini key should already be configured. Otherwise enter it with the hidden
prompt `sentinel config set gemini_api_key` in this environment.

```text
sentinel config set provider gemini
sentinel config set model gemini-3.8-flash
sentinel config set free_fallback true
sentinel config
```

The last command shows settings with secrets masked. Use the Google Free Tier project
without billing for this no-purchase setup. Gemini chat subscriptions and API quotas
are separate. OpenCode's free offer can change; Sentinel never selects a paid model.
The bridge accepts only `deepseek-v4.1-flash-free`, and no OpenCode account is attached.

## 4. Review normally

```text
sentinel review --staged --details
```

You do not select DeepSeek on every review. A successful Gemini answer stays with
Gemini. Choosing Claude, Ollama or standalone OpenCode still selects that provider;
the Gemini-only fallback preference is ignored for those choices.
An explicit 429 switches immediately, without repeatedly retrying that same
quota error. Wrong keys, refusals, malformed answers, network failures and other HTTP
errors do not initiate the quota fallback. The existing schema-correction attempt
still applies to malformed model answers.

After a quota error, Gemini waits for `fallback_cooldown_s` (default 300 seconds), or
longer if Google's `Retry-After` asks for it, capped at 24 hours. This is a waiting
period, not knowledge of your actual remaining quota. When it expires, the next
request tries Gemini again. Identical reviews can reuse a cached DeepSeek answer
without another model call. Cooldown persistence needs a shared writable cache.

The saved review shows the actual model/provider and the fallback reason in its AI
stage. If DeepSeek is also unavailable, the review keeps local findings and reports
the incomplete AI stage. It does not claim a complete AI review.

## 5. Operating limits and tool permissions

The bridge handles one inference at a time, with a 75-second CLI deadline and 1 MiB
request/output budgets. Concurrent requests get a clear busy response. It configures
OpenCode with the requested temperature and an output limit up to 4,096 tokens;
larger Sentinel output settings are capped for this fallback. The CLI's local context
budget is 131,072 tokens. Sentinel's usual context selection runs before that.

OpenCode's free gateway rejected the earlier configuration that disabled every tool.
The working configuration keeps tools present with approval required. Its
noninteractive CLI rejects tool requests automatically. A live diagnostic attempted
a shell write inside Docker: permission was rejected and the marker was absent.
The bridge also rejects any answer containing a tool event, and never exposes a
shell/files/configuration endpoint to Sentinel. Only text completions are accepted.

The JSON answer still passes Sentinel's existing schema, claim checks and ranking.
A proposed fix still needs Docker validation and the existing Apply rules. An AI
answer is a suggestion, not proof. Cached input and reasoning tokens are included in
the existing input/output counters; these counters do not show remaining free quota.

## 6. Check, stop or disable it

```text
python scripts/opencode_bridge.py status
python scripts/check_free_models.py
```

The second command sends one invented example to real DeepSeek. It uses the local
bridge token and shares no vendor credential. It is a connectivity/schema check,
not a broad accuracy benchmark.

To return to Gemini only and stop the local service:

```text
sentinel config set free_fallback false
python scripts/opencode_bridge.py stop
```

Starting with `--build` rebuilds and recreates this helper's labelled container.
Starting without it reuses the existing image. The image remains on disk after stop;
the private user settings remain too. OpenCode is not installed on the Windows/WSL
host, and no offline AI model is downloaded.

## 7. Optional Compose deployment

Use `docker-compose.opencode.yml` alongside the ordinary Compose file, with a separate
random `SENTINEL_OPENCODE_TOKEN` in the deployment environment. Keep that token out of
Git. The override selects Gemini with fallback, provides a private bridge hostname
and waits for bridge health. Only the bridge receives its local token; it does not
receive the application's Gemini environment. It mounts no repository or daemon.
The existing review/API workers still have no Docker socket. This session checks the
merged configuration; a fresh full deployment acceptance run is separate.

## 8. Source tour and verification

- `src/sentinel/ai/providers/factory.py`: chooses the two adapters from settings.
- `fallback.py`: selects DeepSeek after quota exhaustion and remembers cooldown.
- `opencode.py`: local HTTP request and strict response parsing; no subprocess here.
- `core/configuration/config.py`: explicit opt-in, private token, URL and cooldown.
- `tools/opencode_bridge/server.py`: authentication and bounded single-purpose API.
- `tools/opencode_bridge/runner.py`: official CLI, deadlines, cleanup and event checks.
- `scripts/opencode_bridge.py`: trusted start/stop helper, the only setup code using Docker.

See [DEEPSEEK_FALLBACK_VERIFICATION.md](DEEPSEEK_FALLBACK_VERIFICATION.md) for the current
live and automated results. The earlier [Docker experiment](FREE_AI_VERIFICATION.md)
records why the direct free inference adapter was replaced. GitHub is not needed for
these local reviews; connecting GitHub remains a separate later milestone.
