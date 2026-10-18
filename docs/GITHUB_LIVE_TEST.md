# Real GitHub App test: what was connected and why

Verified on **18–19 October 2026 (India time)** using real GitHub delivery, the normal
Sentinel worker, and actual Gemini `gemini-3.8-flash`. This completes the local live
pull-request integration milestone. It does not establish production readiness or
general AI accuracy.

## The two repositories have different jobs

| Item | Purpose | Why we used it |
|---|---|---|
| [Ai-code-reviewer](https://github.com/krish-121/Ai-code-reviewer) | Public Sentinel implementation, tests and learning documents | Your portfolio project and its automated checks live here. |
| [sentinel-integration-demo](https://github.com/krish-121/sentinel-integration-demo) | Private, invented SQLite example | We can introduce and correct a bug without changing Sentinel itself or exposing real application data. |
| Sentinel Review krish-121 | Personal GitHub App, installed on the private test repository | This is the bot identity and its permission to read code and comment. It is not an AI model. |

You do not need a fresh repository for every review. The second repository is a safe
test target. The App is currently selected for this one repository; it was not
installed on the public Sentinel source repository.

## Step 1: give the bot narrow permissions

The App can **read code and metadata**, and **read/write issues and pull requests**.
GitHub treats a pull request's conversation comments as issue comments, which is why
the Issues permission is needed. Contents is read-only: this App cannot push a fix.
Sentinel requests each short-lived installation token for the specific reviewed repo.
It never approves, blocks or merges a pull request automatically.

The setup used GitHub's official
[manifest registration flow](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest).
GitHub generated the private key and notification secret. A temporary page bound only
to this computer received them; the key and saved settings are outside Git with
owner-only Linux file permissions (`0600`). That completed setup page was stopped.
Neither the private key nor a provider key belongs in the repository or walkthrough.

The installation is linked to a non-admin Sentinel user. This matters because an App
installation and a Sentinel user are different identities: the link decides whose
dashboard owns the resulting reviews. An existing SQLite file was backed up before
initializing the normal versioned database; existing data was not deleted.

## Step 2: let GitHub deliver notifications to this computer

A **webhook** is a notification: “this pull request opened” or “another commit was
pushed.” GitHub needs an internet address for it; it cannot reach your `localhost`.

The official Cloudflare helper supplies a free temporary HTTPS address. Its small
download is connection software, not an AI model. The models remain online. The
download was checked against the official release's SHA-256 digest. No Cloudflare
account, domain, payment card or purchased credit was used.

The connection has three parts:

```text
GitHub sends a signed notification
    -> temporary Cloudflare HTTPS address
    -> local gateway: only POST /api/github/webhook
    -> local Sentinel API: verify signature, queue review
    -> worker: read PR, analyze, ask Gemini, verify, save
    -> App installation token: publish summary and inline comments
```

The gateway in [`scripts/github_webhook_gateway.py`](../scripts/github_webhook_gateway.py)
forwards only that exact POST route and GitHub's required headers. It caps the body
at 1 MiB and does not pass through browser authorization headers. Other routes return
404. Sentinel's own signature check remains responsible for authenticating the sender.
Token login also protects the local API. The dashboard is not available through the
temporary public address, so comments deliberately omit a public dashboard link.

Actual public checks: dashboard/API/docs paths **404**, unsigned notification **401**,
correctly signed ping **200**. Local review requests without a user token **401**.

## Step 3: open an intentionally unsafe pull request

Test: [pull request #1](https://github.com/krish-121/sentinel-integration-demo/pull/1).
It proposes changes from `demo/unsafe-query` into `main`; it remains **open and unmerged**.
Its original head was `8dc442fda3dfbf7940b76dd340248341c05ba8c4`.

The example changed a parameterized SQLite query into an f-string containing a name.
Treating input as part of SQL lets a name such as `' OR 1=1 --` change the query's meaning.
There are no real users, records or credentials in this exercise.

GitHub's actual `pull_request/opened` delivery returned **202** and queued
`R-c49951efc9`. All eight stages completed. Gemini returned one SQL-injection candidate;
the built-in analyzer, Ruff and Bandit independently supported the query construction.
The resulting high-severity finding appeared in the database, authenticated dashboard,
one bot summary and one inline comment on `lookup.py:8`.

The AI request used **1,694 input / 165 output tokens**, one attempt, no quota fallback.
The review pipeline took approximately **16 seconds**; acquisition and GitHub publication
add time around it. “Supported” means the listed checks support that finding; it is
not a proof of every possible exploit or every sentence generated by a model.

## Step 4: ask GitHub to send the same event again

Networks can retry. A reviewer must not spam the pull request on every retry.
GitHub's actual redelivery returned **the same review ID**. The database still held one
review, and GitHub still held one summary and one inline comment. This was not a
handcrafted substitute notification.

The automatic ping and installation notification initially arrived before the local
API was ready and returned 502. Once ready, their real redeliveries returned 200.
The later opened, repeated-opened and new-push deliveries all returned 202. The setup
failure is retained in the evidence rather than hidden or counted as a successful ping.

## Step 5: correct the query and push again

We restored the parameterized query and added
`test_sql_like_name_cannot_return_other_users`. In the normal Docker sandbox, that
regression failed against the unsafe query and all **three tests passed** against the
correction. No repository test code ran directly on the host.

Pushing `333803b0af4001430e1c1f8a833e02770ada38a7` triggered GitHub's real
`pull_request/synchronize` notification and review `R-2c71ba233a`.
Gemini used **1,537 input / 4 output tokens** and returned no findings. The net PR diff
against `main` now contains the new regression test; the lookup is restored to its
original safe implementation. This is a review of that changed code, not a new claim
that the entire repository has been exhaustively proved safe.

Sentinel edited summary **6253466035** in place to “No problems found in this change,”
with the new reviewed commit. Inline comment **4308162024** remains as outdated review
history. There was no second inline warning and the main branch was not merged or changed.

## Step 6: check privacy between Sentinel users

The linked owner received 200 for the saved review, findings, file diff, graph and source
snapshot. Another non-admin test user received **404** for each and an empty review list.
The real owner logged in and opened the original finding in Sentinel's served dashboard.
The saved login token was not printed in chat or placed in the project directory.

## How the code fits together

| File/function | Responsibility | Why separate it |
|---|---|---|
| `integrations/github/client.py::GitHubAppAuth` | Sign App JWTs and request short-lived repository tokens | Authentication stays out of the analysis engine. |
| `apps/api/routes/github.py::github_webhook` | Verify notification signature and queue work | GitHub gets a quick response instead of waiting for the AI. |
| `services/reviews.py::ReviewService` | Acquire snapshots, orchestrate review, save and request publication | Local and GitHub reviews share the same review pipeline. |
| `apps/worker/main.py::Worker` | Claim and execute persistent jobs | Slow model requests do not block the notification request. |
| `integrations/github/publisher.py::GitHubPublisher` | Update the bot-owned summary and deduplicate inline comments | Publishing policy stays separate from finding generation. |
| `infrastructure/database/store.py::Store` | Installation ownership and user-scoped reads | One user's repository results must not appear in another user's account. |
| `core/configuration/config.py` | Private settings and masked secret display | The webhook secret now uses the same hidden prompt/masking path as provider secrets. |

The new gateway has focused HTTP tests for route denial, header filtering, body limits
and loopback target validation. Private App settings preserve the existing Gemini and
free DeepSeek configuration. Full local checks: **525 passed, 27 PostgreSQL skips**;
all seven Docker tests ran, overall coverage **93.38%**, core **96%**; lint, formatting
and strict typing passed. PostgreSQL variants run in hosted CI.

## Running it again and what remains

This is a **local development connection**. It works while your computer, Docker,
Sentinel and the tunnel are running. Closing them or sleeping the computer stops new
live reviews; it does not erase saved reviews or uninstall the App. Cloudflare's
[Quick Tunnel documentation](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
describes these temporary addresses and their testing limits.

The owner's exported `Start-Sentinel-GitHub.cmd` starts the existing free DeepSeek bridge,
the local API/worker, the webhook-only gateway and tunnel. It checks local access restrictions,
updates this App's notification URL, and confirms a real signed GitHub ping. `Stop-Sentinel-GitHub.cmd` stops only the three
connection processes. The AI bridge remains reusable. These helpers contain paths and
code, not credentials, and depend on this computer's existing WSL runtime and checkout.
Initial start-helper trials exposed delayed local DNS recognition of fresh tunnel
addresses and one GitHub connection timeout. The final helper uses a real GitHub ping
and bounded connection retries; its successful restart preserved both reviews, and an
actual repeated synchronize event returned the existing second review without new AI work.
No system DNS or certificate settings were changed.

For a fresh machine, follow [GITHUB_APP.md](GITHUB_APP.md) and the normal installation
guide instead of assuming these machine-specific paths exist.

Gemini was available for both live PR reviews; no paid account was connected. The
separately verified Gemini-to-free-DeepSeek quota fallback remains enabled. This PR run
does not claim to have exercised quota fallback inside a GitHub job. Claude and Ollama
remain optional; no local model download is required. GLM remains excluded after its
earlier unavailable responses.

Remaining release work includes representative review/fix quality evaluation, simultaneous
push/publication races on GitHub, wider browser/reconnection coverage, current full-stack
OpenCode failure acceptance, backup/restore, load/retention measurements and durable
hosting if wanted. See [PROJECT_STATUS.md](PROJECT_STATUS.md).
