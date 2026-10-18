# GitHub source upload and the reviewing bot

Source destination: [krish-121/Ai-code-reviewer](https://github.com/krish-121/Ai-code-reviewer).
The repository is public. Its main pushes run the existing Python, frontend and Docker
CI jobs. Source hosting and a real pull-request review are different milestones.

## What the first upload contains

Sentinel source, tests, demo fixtures, documentation, lock files, Dockerfiles, the CI
workflow, `.gitignore` and an empty-credential `.env.example` belong in Git. Installed
dependencies, local databases/caches, real `.env` files and authentication keys do not.
The owner's real Gemini/OpenCode configuration remains in the private WSL user settings
outside this project. No vendor credentials are required by the offline CI suite.

Two deliberately tracked `.env` fixtures under demo/tests contain invented values for
secret-detection tests. They are not deployment settings. Never replace them with real
credentials. The ignore rules also exclude PEM/key files and additional SQLite files.

## Why old commits needed cleaning

GitHub push protection rejected a generated Stripe-shaped value in the demo and its
end-to-end assertion. It appeared in earlier commits, so changing the latest file alone
would still upload the old value. We did not bypass push protection.

A separate publication copy replaced that exact invented fixture throughout the 27
commits. The original history was backed up and verified locally before any branch
replacement. Cleaned commits keep the same authors, timestamps, messages and parent
structure, but their IDs change when content or parents change. Original signatures
cannot certify changed commits; they remain with the original objects in the backup.
Rewritten publication commits do not claim those invalid signatures.

The current fixture uses a conspicuously synthetic 20-character suffix, exercises
Sentinel's Stripe detector and redaction, and is too short to be a usable provider key.
The existing end-to-end test verifies the finding appears and the value never reaches
the model. Original history stays local; push the normal main branch, not all backups.

## Real hosted verification

[GitHub Actions run](https://github.com/krish-121/Ai-code-reviewer/actions/runs/39141482827) passed on `8eb6c44679cb9e0f7ff41c60a5bdd7f93d766864`:
Python/PostgreSQL 544 passed with 1 skip, frontend 21 passed with type/format/build,
and Docker/Compose validation succeeded. The first run exposed one frontend test
formatting issue; the follow-up code run is green. CI uses controlled external-service
fixtures. This is hosted acceptance of the repository, not a live GitHub App review.

## What connects the bot

1. A separate disposable project provides a safe real pull request with a deliberate bug.
2. A GitHub App gives Sentinel a bot identity and narrowly scoped repository permissions.
3. A signed webhook notifies Sentinel that the pull request changed. A reachable HTTPS
   endpoint is needed for GitHub to deliver it.
4. A worker runs the review and posts its summary/inline comments as the App.

These steps are not completed merely by uploading source. Follow [GITHUB_APP.md](GITHUB_APP.md)
and [LOCAL_SETUP_AND_GITHUB.md](LOCAL_SETUP_AND_GITHUB.md). The completed delivery, review,
comment, redelivery and second-push evidence is recorded in [GITHUB_LIVE_TEST.md](GITHUB_LIVE_TEST.md).

## Reviewing App milestone completed

The private `sentinel-integration-demo` repository and personal App are now connected.
Actual signed GitHub notifications triggered Gemini reviews and App-authored comments;
repeat delivery and a corrected second push passed, including summary updates and
user isolation. The test PR remains unmerged. See [GITHUB_LIVE_TEST.md](GITHUB_LIVE_TEST.md).
The connection currently runs on this computer through a webhook-only temporary tunnel;
it is not an always-on hosted service.
