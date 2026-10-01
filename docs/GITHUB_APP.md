# Setting up the GitHub App

Sentinel reviews pull requests as a GitHub App: GitHub sends a webhook when a PR is opened
or updated, a worker reviews it, and Sentinel posts one summary comment plus inline
comments for new findings. Using an App (instead of a personal token) means short-lived,
per-installation tokens with only the permissions below.

> The App integration is tested against a faked GitHub API (see
> [PROGRESS.md](../PROGRESS.md), *Verified only with mocks*). Follow this guide on a test
> repository first.

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

Each push produces a new review. The summary comment (marked
`<!-- sentinel:summary -->`) is **edited in place**; inline comments are posted only for
findings whose fingerprint is not already on the PR, so re-pushing does not repeat comments.
Findings on lines outside the diff (GitHub cannot comment there) are listed in the summary.
Sentinel posts reviews with the `COMMENT` event: it never approves or blocks a PR.

## 5. Testing the webhook locally

GitHub must reach your machine. With any tunnel (e.g. `cloudflared tunnel --url
http://127.0.0.1:8000` or `ngrok http 8000`), set the App's webhook URL to the tunnel URL +
`/api/github/webhook`. Note that `sentinel serve` refuses to listen on a public interface in
`local` auth mode; the tunnel connects to `127.0.0.1`, so local mode is fine for testing.

GitHub's App settings → *Advanced* → *Recent deliveries* shows each webhook and Sentinel's
response (`202` with a `review_id` when a review was queued). A `401` means the webhook
secret does not match; `503` means `SENTINEL_GITHUB_WEBHOOK_SECRET` is not set.

## Reviewing a PR without the App

For a one-off review from your terminal, a personal access token with read access is
enough; nothing is posted to GitHub:

```bash
SENTINEL_GITHUB_TOKEN=<token> sentinel review --pr 42 --repo owner/name
```
