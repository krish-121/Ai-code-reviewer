# Run Sentinel locally, then connect a real model and GitHub

You can develop, learn and test Sentinel without a GitHub account or an AI service.
This guide separates three useful milestones. Finish them in order; GitHub is last.
Commands marked **Ubuntu** go in your WSL Ubuntu terminal. Commands marked **PowerShell**
go in Windows PowerShell. Do not mix their environment-variable syntax.

**Cloud alternative connected 18 October 2026:** Ollama is optional. Gemini and
automatic quota fallback to free DeepSeek through an isolated OpenCode bridge are
verified. Follow [FREE_AI_FALLBACK.md](FREE_AI_FALLBACK.md) for setup and explanation.
GitHub can wait: local Git is sufficient for these tests.

**Live fix milestone completed 18 October 2026:** the normal sandbox image and saved
WSL copy setting are configured. Real Gemini review → generated fix/test → Docker
validation → Apply succeeded on a disposable project. Read
[LIVE_FIX_WORKFLOW.md](LIVE_FIX_WORKFLOW.md) to follow each step and understand why it
is checked before any source is changed.

## 1. Understand what each part does

| Part | Plain-language purpose | Needed now? |
|---|---|---|
| Your Sentinel folder | The program we are building | Yes |
| A local Git repository | Records two versions so Sentinel can review their differences | Yes, the demo builder makes one |
| SQLite | A small local file storing reviews and findings | Used automatically |
| Node and the analyzer packages | Parse TypeScript and run its deterministic checks | For complete JS/TS checks |
| Docker | Runs proposed fixes and the optional OpenCode messenger separately | For DeepSeek fallback and fix validation |
| Ollama | Runs an actual AI model on your computer | Optional alternative to the cloud chain |
| A GitHub repository | Hosts a test project and its pull requests online | Only for GitHub integration acceptance |
| A GitHub App | Gives Sentinel permission to receive PR events and post comments | Only for GitHub integration acceptance |
| PostgreSQL and separate workers | Store and process work across deployment processes | For the full Compose deployment |

A repository is a project folder with Git history. A GitHub repository is an online copy.
A pull request proposes merging one branch into another. A webhook is GitHub notifying
Sentinel that the pull request changed. Local Git is sufficient to build and review code;
the online copy is needed to test those notifications and actual GitHub comments.

## 2. Install and run the offline version

Use WSL for Sentinel because local Apply uses Linux filesystem protections. Keep Docker
Desktop running. In Docker Desktop settings, enable integration for your Ubuntu distribution
under **Resources → WSL Integration**. These steps install project dependencies, not a model.

In **Ubuntu**, check your prerequisites:

```bash
python3 --version   # 3.11 or newer
node --version      # 22.13 or newer
git --version
docker version      # Client AND Server must respond
```

If one is missing, stop at that line and install that prerequisite. Node must be the Linux
version visible in Ubuntu, rather than a Windows npm executable reached through PATH.

Then, in **Ubuntu**:

```bash
cd /mnt/d/sentinel-final-v2/sentinel
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -c requirements.lock -e '.[dev,postgres,analyzers]'
npm ci --prefix tools/analyzers --omit=dev --no-audit --no-fund
export NODE_PATH="$PWD/tools/analyzers/node_modules"
export PATH="$PWD/tools/analyzers/node_modules/.bin:$PATH"
npm ci --prefix web --no-audit --no-fund
npm run build --prefix web
docker build -f Dockerfile.sandbox -t sentinel-sandbox:latest .
sentinel config set sandbox docker
sentinel config set sandbox_image sentinel-sandbox:latest
sentinel config set sandbox_transport copy
```

The virtual environment keeps Python dependencies separate. The lock files give us the
tested package versions. Building the web folder supplies the UI assets served by Python.
The sandbox image supplies trusted validators; `copy` transfers scratch files without
requiring Windows, Ubuntu and Docker to share identical paths. These settings are saved
privately and persist across terminals; existing AI keys are preserved.

Create a fresh learning repository and review its planted problems:

```bash
python demo/build_demo_repo.py .demo/local-learning
cd .demo/local-learning
sentinel review --range main..feature/search-and-reports --no-ai --details
```

The builder creates a base commit and a feature branch containing deliberate bugs. It
refuses to overwrite an existing destination. Choose a new destination on a repeat run.
`--no-ai` still exercises diff parsing, graph/context generation, static checks, finding
processing and persistence. It does not establish AI review quality.

For a visual demonstration, return to Sentinel's root and seed a separate demo database:

```bash
cd /mnt/d/sentinel-final-v2/sentinel
python scripts/seed_demo.py
python scripts/serve_demo.py
```

Open [the isolated demo UI](http://127.0.0.1:8820). Follow [the public demo guide](PUBLIC_DEMO.md). The seed script uses scripted model responses,
explicitly labelled replay; the analysis and Docker validation are real. Keep this server
local. Ctrl+C stops it. Its default demo destination also must be new; for repeat seeding
use fresh `--repo` and `--db` paths instead of deleting learning work.

## 3. Add Ollama for a real AI check

Ollama is the model server; the downloaded model is the AI it runs. Start with a small
connection test, then evaluate quality separately. No cloud-provider key is needed for a
local model. The [official Windows guide](https://docs.ollama.com/windows) describes the
installer and the local API on port 11434.

1. Download and run the [Windows installer](https://ollama.com/download/windows).
2. Open a **new PowerShell** window, so it sees the installed command.
3. Run these **PowerShell** commands:

```powershell
ollama --version
ollama pull qwen2.5-coder:3b
ollama run qwen2.5-coder:3b "Say hello in one short sentence."
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

The [model library](https://ollama.com/library/qwen2.5-coder) lists the 3B download at about
1.9 GB and 7B at about 4.7 GB. Runtime memory is additional. The smaller model is a starting
point for checking the connection, not a claim of good review accuracy. Later, test a larger
model if your available memory permits it. Download time and CPU-only inference may be slow.

4. In **Ubuntu**, verify that Sentinel's environment can reach the same server:

```bash
curl --fail http://127.0.0.1:11434/api/tags
```

If PowerShell succeeds but Ubuntu cannot connect, this is Windows/WSL networking, not a
Sentinel analysis failure. Keep Ollama bound locally; use WSL mirrored networking where
available or run Ollama inside Ubuntu following its [official guide](https://docs.ollama.com/quickstart).
Do not expose an unauthenticated Ollama server publicly just to solve this connection.
If a model request times out, check that this direct connection still succeeds first.

5. In the activated Sentinel environment in **Ubuntu**:

```bash
export SENTINEL_PROVIDER=ollama
export SENTINEL_MODEL=qwen2.5-coder:3b
export SENTINEL_OLLAMA_URL=http://127.0.0.1:11434
sentinel config
cd /mnt/d/sentinel-final-v2/sentinel/.demo/local-learning
sentinel review --range main..feature/search-and-reports --details
```

Environment settings last only for this terminal session. `sentinel config` shows the
effective settings. Check the AI stage actually completed: a partial review with static
findings alone is not a successful provider test. Compare the real output with `--no-ai`;
expect variation, and inspect the evidence rather than assuming every AI claim is correct.

Large reviews need a context window large enough for their prompts. Ollama's
[context-window documentation](https://docs.ollama.com/faq#how-can-i-specify-the-context-window-size)
explains `OLLAMA_CONTEXT_LENGTH`; increasing it also increases memory needs. Begin with
the small demo. Do not treat a successful short prompt as acceptance for large repositories.

Use the UI to inspect a real finding and generate a fix only after Docker is available.
Require a **validated** result and inspect its checks and patch before Apply. A failure or
unverified result is useful evidence to diagnose, not permission to skip validation.

## 4. Create a disposable GitHub repository when you reach the PR milestone

This repository is for testing Sentinel's GitHub integration. It does not need to contain
Sentinel's implementation. Keeping the two separate makes the results easy to understand.

1. Sign in to GitHub. Use **+ → New repository**, name it `sentinel-integration-demo`,
   and choose **Private** while learning. Leave README, license and gitignore unselected
   because the generated demo already has Git history. See the
   [GitHub repository quickstart](https://docs.github.com/en/repositories/creating-and-managing-repositories/quickstart-for-repositories).
2. Copy its HTTPS URL. In **Ubuntu**, inside `.demo/local-learning`, inspect `git remote -v`.
   If no `origin` exists, add your copied URL. Replace `YOUR-USERNAME` below:

```bash
git remote add origin https://github.com/YOUR-USERNAME/sentinel-integration-demo.git
git push -u origin main
git push -u origin feature/search-and-reports
```

GitHub will ask you to authenticate through your configured Git credential method.
Do not put passwords or access tokens in the remote URL or paste them into this chat.
If a remote already exists, inspect it before changing anything. GitHub documents
[pushing commits](https://docs.github.com/en/get-started/using-git/pushing-commits-to-a-remote-repository).
The generated demo includes fake secret examples on purpose; inspect them before upload.
Do not replace them with real credentials or bypass an unexpected secret-scanning warning.

3. On GitHub choose **Pull requests → New pull request**. Base: `main`; compare:
   `feature/search-and-reports`. Give it a descriptive title and create the PR.
4. Stop here until Sentinel's GitHub App is configured. Creating a repository alone does
   not connect Sentinel or cause reviews to appear.

## 5. Connect the GitHub App and record acceptance

Follow [GITHUB_APP.md](GITHUB_APP.md) for the exact permissions, private key, webhook secret,
installation ID and Sentinel user link. The official
[App registration guide](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app)
describes the GitHub settings screens. Configure only the disposable repository at first.

The API and a worker must be running. GitHub needs an HTTPS address it can reach; use a
deployed endpoint or a deliberately configured tunnel. Before exposing it, switch Sentinel
to token authentication as described in the App guide. Its default local mode is for your
own machine. Do not share the private key, user token or webhook secret.

Acceptance means observing all of these, with the reviewed commit recorded:

- A signed delivery appears in the App's Recent deliveries with a successful response.
- A queued review progresses to completion in Sentinel's UI.
- Its summary and valid inline comments appear on the PR as the App.
- Redelivering the same event does not create duplicate work/comments.
- Pushing another commit reviews the new revision and updates the summary.
- Another Sentinel user cannot read this user's repository results.

The automated tests cover these contracts with HTTP fixtures, but only this live run
confirms the real App configuration. Finally, push Sentinel's implementation to a separate
repository when ready and run its Actions workflow to verify hosted CI. The source destination is now
[krish-121/Ai-code-reviewer](https://github.com/krish-121/Ai-code-reviewer). The private test App has now completed real signed delivery, Gemini analysis, bot
comments, repeat delivery, second push and user-isolation acceptance. See
[GITHUB_LIVE_TEST.md](GITHUB_LIVE_TEST.md) for the result and source explanation;
[GITHUB_UPLOAD.md](GITHUB_UPLOAD.md) covers the source upload.

## What to report if a step fails

Share the step number, which terminal you used, and the error text with secrets removed.
For Ollama, include whether PowerShell and Ubuntu can each read `/api/tags`, the model name
and whether the AI stage failed or timed out. For GitHub, include the delivery status and
review ID. This distinguishes installation, connectivity, configuration and code problems.


## Latest connection state — 19 October 2026

The follow-up [real PR recovery test](GITHUB_CONNECTION_RECOVERY.md) passed, and its
temporary Smee relay was disconnected afterward as requested. App installation and
saved AI keys remain; new automatic reviews are currently disconnected. Cloudflare
names failed authoritative DNS in that session. The local helper now checks public
readiness before changing GitHub's address and still requires a signed ping. It does
not silently enable Smee. Start local-only mode for learning without public webhooks;
connecting a future reachable endpoint remains a separate deliberate step.
