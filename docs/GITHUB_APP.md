# Setting up the GitHub App

Sentinel reviews pull requests as a GitHub App: GitHub sends a webhook when a PR is opened
or updated, a worker reviews it, and Sentinel posts one summary comment plus inline
comments for new findings. Using an App (instead of a personal token) means short-lived,
per-installation tokens with only the permissions below.

> **Real local acceptance passed on 18–19 October 2026:** private test installation,
> signed GitHub delivery, actual Gemini review, database/dashboard display, bot summary
> and inline comments, repeat delivery and second-push updates. See
> [GITHUB_LIVE_TEST.md](GITHUB_LIVE_TEST.md) for evidence and beginner explanations.
> The public source repo and private reviewed test repo have different purposes.

## 1. Create the App

GitHub → *Settings* → *Developer settings* → *GitHub Apps* → *New GitHub App*.

| Field | Value |
|---|---|
| Webhook URL | `https://<your-sentinel-host>/api/github/webhook` |
| Webhook secret | a long random string (`python -c "import secrets; print(secrets.token_hex(32))"`) |
| Repository permissions → **Contents** | Read-only (download the PR's code) |
| Repository permissions → **Pull requests** | Read and write (read the diff, post review comments) |
| Repository permissions → **Issues** | Read and write (PR *conversation* comments use the Issues API) |
| Repository permissions → **Metadata** | Read-only (GitHub requires it) |
| Subscribe to events | **Pull request** |
| Where can it be installed | Only on this account (until you are confident) |

Nothing else is needed: no checks, no administration, no organisation permissions.
Sentinel additionally asks for *only* `contents: read`, `pull_requests: write` and
`issues: write` when it requests each installation token
([`MIN_PERMISSIONS`](../src/sentinel/integrations/github/client.py)), so even an App
configured with more permissions gets tokens with just these.

After creating it, note the **App ID** and generate a **private key** (`.pem`). Store the key
outside any repository with `chmod 600`.

## 2. Configure Sentinel

```bash
SENTINEL_GITHUB_APP_ID=123456
SENTINEL_GITHUB_PRIVATE_KEY_PATH=/run/secrets/sentinel-github.pem
SENTINEL_GITHUB_WEBHOOK_SECRET=<the webhook secret>
SENTINEL_PUBLIC_URL=https://<your-sentinel-host>      # links in comments point here
SENTINEL_AUTH_MODE=token                              # the server is reachable by others
SENTINEL_PROVIDER=claude                              # and its key, see .env.example
```

For GitHub Enterprise Server also set `SENTINEL_GITHUB_API_URL=https://<ghe-host>/api/v3`.

Start the API and at least one worker (`docker compose up`, or `sentinel serve` and
`sentinel worker`; see [DEPLOYMENT.md](DEPLOYMENT.md)).

For a local installation, these values can also be saved in the private user config:

```bash
sentinel config set github_app_id 123456
sentinel config set github_private_key_path /absolute/private/path/sentinel-github.pem
sentinel config set github_webhook_secret   # hidden prompt; do not paste it into a command
sentinel config set auth_mode token
```

Use the actual App ID/path. The writer preserves existing provider settings, creates
owner-only config files, and masks the webhook secret in normal config output. The
private key file itself must remain outside the repo with owner-only permissions.

## 3. Install it and link it to a user

Install the App on the repositories to review (App settings → *Install App*). The
installation id is the number at the end of the installation's settings URL.

Reviews are owned by a Sentinel user (that is the tenancy boundary). Create one and link
the installation so its reviews appear in that user's UI and API:

```bash
sentinel users create alice                 # prints alice's API token once
sentinel users link-installation <installation-id> <user-id>
```

Without a link, reviews are stored under a non-admin system user `github` and are visible
to admins only.

## 4. What happens on a pull request

| PR event | Sentinel |
|---|---|
| opened, reopened, synchronize (new push), ready_for_review | queues a review |
| draft PRs | ignored until marked ready for review |
| anything else | acknowledged (`200`) and ignored |

Each distinct base/head revision queues one review; repeated deliveries return its existing ID.
Workers reject superseded PR revisions before analysis and before publication. The summary identifies
the reviewed commit. GitHub has no atomic compare-and-comment operation, so a push concurrent with
the final network request can still leave a comment explicitly labeled with the older commit.
The summary comment (marked
`<!-- sentinel:summary -->`) is **edited in place**; inline comments are posted only for
findings whose fingerprint is not already in comments owned by the authenticated bot/user.
Markers in other users' comments never suppress findings or select a comment for editing.
Findings on lines outside the diff (GitHub cannot comment there) are listed in the summary.
Sentinel posts reviews with the `COMMENT` event: it never approves or blocks a PR.

## 5. Testing the webhook locally

GitHub must reach your machine. For local development, run three terminals from the
project root (with the installed environment active):

```bash
# Terminal 1: private local dashboard/API and worker
sentinel serve --host 127.0.0.1 --port 8000

# Terminal 2: expose only the webhook route to the tunnel
python scripts/github_webhook_gateway.py --port 8765 --target http://127.0.0.1:8000

# Terminal 3: official Cloudflare helper, installed separately
cloudflared tunnel --url http://127.0.0.1:8765
```

Set App settings → Webhook URL to the printed HTTPS address + `/api/github/webhook`.
The address changes after a new Quick Tunnel starts; update the App before another PR
test. Keep all three terminals running. This is temporary development connectivity,
not permanent hosting. The owner's exported Start/Stop helpers automate these steps
on the already-configured Windows/WSL machine; they use local API port 8810.

Set `SENTINEL_AUTH_MODE=token` (or save `auth_mode token`) and configure the webhook secret
before connecting the tunnel. Never tunnel the full local/no-login app. The gateway
forwards only bounded POST requests on the exact webhook path; the main API still checks
GitHub's signature. Confirm other public routes return 404, unsigned webhooks return 401,
and a real signed GitHub delivery succeeds. The gateway is a development helper, not a
replacement for a properly configured production proxy.

GitHub's App settings → *Advanced* → *Recent deliveries* shows each webhook and Sentinel's
response (`202` with a `review_id` when a review was queued). A `401` means the webhook
secret does not match; `503` means `SENTINEL_GITHUB_WEBHOOK_SECRET` is not set.

## Reviewing a PR without the App

For a one-off review from your terminal, a personal access token with read access is
enough; nothing is posted to GitHub:

```bash
SENTINEL_GITHUB_TOKEN=<token> sentinel review --pr 42 --repo owner/name
```
