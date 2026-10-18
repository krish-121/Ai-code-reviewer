# OpenCode free-model test in Docker

> Historical experiment before integration. The current working fallback is described
> in [FREE_AI_FALLBACK.md](FREE_AI_FALLBACK.md) and its
> [verification report](DEEPSEEK_FALLBACK_VERIFICATION.md). Status statements below
> describe the earlier experiment, when fallback was still off.

Tested on **18 October 2026**, using official **OpenCode 1.19.3**.

## What worked

**DeepSeek V4.1 Flash Free worked without an API key, account login, payment card,
or purchased credits in the container.** OpenCode recorded a cost of **0** for its
successful responses. This proves free access for these tests, not an unlimited
allowance or a promise that the offer will continue.

| Requested model | Check | Result |
|---|---|---|
| `deepseek-v4.1-flash-free` | Empty-list average function | Correctly identified division by zero; answered in 6.84 seconds |
| Same | Sentinel's actual review instructions and JSON schema, invented unsafe SQL change | Validated answer in 9.11 seconds; identified SQL injection at `lookup.py:2` |
| Same | Safe SQL change using bound parameters | Validated answer in 5.28 seconds; returned `{"findings": []}` |
| `glm-5.3-flash-free` | Average function | HTTP 503: upstream endpoint unavailable, after 76.70 seconds |
| Same | Sentinel instructions and schema, invented unsafe SQL change | HTTP 503 again, after 75.79 seconds; no review answer to validate |

GLM's failures were service errors, not requests to add money. Its review quality
could not be assessed. Three small DeepSeek examples are useful compatibility checks,
not a benchmark establishing accuracy on large projects or superiority to Gemini.
The SQL finding was appropriate; its discussion of additional stacked statements
was conditional on the database driver and should not be assumed true for SQLite.

## What Docker means here

An **image** is a saved application setup. A **container** is a running copy of it.
We downloaded an official Node Linux base and installed the official OpenCode npm
package inside the image. Node is the runtime used by that installation package.

We did **not** download the DeepSeek or GLM model weights. Those models run online;
the container sent invented examples to OpenCode's service over the internet.
We installed no OpenCode package directly into Windows or the WSL host environment.

The resulting image is `sentinel-opencode-test:1.19.3`, reported as **825,360,419 bytes**
(about 825 MB decimal). This is an image size, not a precise measurement of additional
disk usage: Docker shares layers and maintains its own storage. The image remains
cached for repeat tests. Each test container was disposable and removed afterward.

## What the container could access

- Its Linux/application files and temporary files inside `/tmp`.
- Internet access, needed to contact the online models.
- Only the invented prompt and explicit non-secret OpenCode settings we supplied.

No Windows/WSL project directory, user configuration directory, Gemini key, OpenCode
login, browser session, or Docker control socket was mounted or forwarded. No port
was published. Processes ran as the image's unprivileged `node` user, with dropped
Linux capabilities, no privilege escalation, a read-only image filesystem, temporary
storage, and limits on memory, CPU and process count. A container reduces exposure;
it is not a claim of perfect isolation from every possible software vulnerability.

## Why the first attempts failed

The first two configurations denied all OpenCode tools: one custom agent and the
standard Plan agent. Both models returned HTTP 403 saying its free tier must be
used inside OpenCode, even though the application was official.

OpenCode's [issue tracker](https://github.com/anomalyco/opencode/issues/56324)
links reports that denying read/shell tools can trigger this misleading error.
We then used its standard Build agent, with global permissions set to **ask** and
one agent step. We supplied no tool approvals. The three successful DeepSeek event
streams contain only start, text and finish events: **no tool calls occurred**.
GLM instead reached an upstream-unavailable error. We did not spoof client headers,
patch OpenCode, or copy authentication credentials to get around a service restriction.

These observations make tool configuration the likely explanation for the earlier
403 responses, but do not establish every rule enforced by OpenCode's gateway.

## Why install OpenCode instead of calling its API directly?

The direct HTTP adapter previously received HTTP 403 from the free-model endpoint.
The working test uses the actual OpenCode application through its documented
[`opencode run` interface](https://opencode.ai/docs/cli/). OpenCode itself still uses
an online API internally. We installed a client application, not an offline AI.

This has a cost in complexity and prompt size. In the SQL check OpenCode reported
1,508 input tokens, 345 output tokens, 282 reasoning tokens and 7,680 cached-read
tokens, for a total of 9,815. Those are OpenCode's event counters, not a measurement
of remaining daily quota or a direct comparison with Gemini's accounting.

## What this means for Sentinel

- Gemini has already passed a separate live review test.
- DeepSeek through official OpenCode is now a demonstrated free candidate.
- GLM remains an unverified backup because its service was unavailable.
- **Automatic fallback remains off.** The experimental fallback implementation in
  the prepared working copy still calls the direct HTTP endpoint. This Docker
  experiment has not replaced that adapter or shipped a working automatic chain
  into the main Sentinel repository.

Remaining integration work is to implement the supported OpenCode transport,
validate rejection of tool requests without interactive approvals, bound response
size/time, handle 503 errors with cooldown, and test an actual Gemini-quota fallback.
Keep the existing review/API workers without Docker-daemon access; a future bridge
must preserve that separation rather than give every worker control of Docker.
Reviews and proposed fixes must still pass Sentinel's schema, evidence checks and
Docker validation. Free-model output is not automatically trustworthy.

The walkthrough and progress notes record these results separately from completed
project features. No source patch or generated fix was applied during this experiment.

## Evidence

The accompanying `Sentinel-OpenCode-Docker-Evidence.zip` contains the synthetic
response events, image/container inventory, Dockerfile, and experiment helpers.
It contains no API key or user configuration. The schema experiment imports the
existing Sentinel prompt builder and Pydantic review contract from the prepared
working copy; it is not an end-to-end Sentinel pipeline run.
