# Real GitHub notification recovery test

Verified 19 October 2026. **The test passed; Smee is now disconnected.**

## 1. Why notifications had stopped

GitHub needs an internet address where it can deliver a notification when a pull
request changes. Sentinel runs on this computer, so a temporary connection supplies
that address. Starting its program does not prove the address works.

The Cloudflare program reported a connection, but its generated names did not exist
in public DNS. DNS is the internet's address book. Both public resolvers and an
authoritative nameserver reported that failure. Changing GitHub permissions or
replacing AI keys would not fix it.

The local connection helper now checks the public address before changing GitHub's
setting. The notification gateway must hide `/api/reviews` with HTTP 404 and reject
an unsigned notification with HTTP 401. Probes carry no saved authentication,
cookies or query keys and do not follow redirects. A subsequent real signed GitHub
ping must still succeed before the helper announces a working connection.

The reusable check lives in `src/sentinel/integrations/github/dev_readiness.py`;
14 offline tests cover unavailable addresses, timeouts, redirects, exposed routes,
invalid addresses and accidental credential forwarding. The computer-specific
launcher in this outputs folder calls it. Failed public checks leave GitHub's old
address unchanged and preserve an existing recognised local dashboard.

## 2. Why Smee was used for this test

With your explicit permission, Smee temporarily forwarded only notifications about
the invented private test repository. It is an intermediary: GitHub sends an event
to Smee, and a small local relay passes it to Sentinel. Smee could see those event
contents; this was not a promise of zero data sharing.

Docker supplied a separate environment for the official `smee-client@5.0.0`
program. No AI model was downloaded for this relay. Its container had no mounted
project folders, Docker socket, Gemini key, GitHub App private key or user token.
It received only the temporary channel address and the local notification target.
Its memory, CPU and processes were limited, its main filesystem was read-only,
and it exposed no listening port on this computer.

The notification gateway forwarded only the webhook route and required GitHub
headers. Sentinel still checked GitHub's original signature. An invented unsigned
event was rejected; a correctly signed one was accepted. No signature check was
disabled to make the test work.

## 3. What passed on a real pull request

We created [test PR #2](https://github.com/krish-121/sentinel-integration-demo/pull/2)
with a deliberately unsafe SQL query in `lookup.py:8`. The old two tests still
passed in Docker, illustrating why passing existing tests alone does not prove
security. The PR is open and unmerged; the base branch was not changed.

| Check | Observed result |
| --- | --- |
| Real signed GitHub setup ping | GitHub and Sentinel both returned HTTP 200; the same delivery identifier was recorded locally. |
| Real PR-opened notification | GitHub reported HTTP 200 from the relay. Sentinel's durable delivery record links that event to one review. |
| Complete Sentinel review | All eight stages finished, with no recorded errors. |
| Actual AI provider | Gemini, model `gemini-3.8-flash`; fallback was not needed. |
| Deliberate defect | SQL injection through string interpolation, `lookup.py:8`, marked supported. Built-in analysis, Ruff S608 and Bandit B608 corroborated it. |
| Published result | Exactly one bot summary and one inline comment on the reviewed change. |
| Reviewed version | `30d0d11e4de9f9d2e1c8f58f5c27100779b5bddd` |
| Saved review | `R-f6cd5d62f1`, completed, with no errors. |

Read the [bot summary](https://github.com/krish-121/sentinel-integration-demo/pull/2#issuecomment-6266516561)
and [inline warning](https://github.com/krish-121/sentinel-integration-demo/pull/2#discussion_r4313453863).
These links require access to the private test repository.

The PR event's GitHub delivery identifier is
`e5c97b40-cbb2-11f1-9343-666e734ee2a9`. GitHub returning 200 proves the relay accepted
it; that status alone would not prove Sentinel completed a review. The matching
database reservation, completed stages and published comments provide that evidence.
The live local PR receipt was observed as HTTP 202, but its temporary container log
was lost when Docker stopped during the interruption. The completed review and GitHub
comments survived and were checked again afterward. The signed ping's local receipt
was saved separately before the interruption.

This was a notification/review/publication test. It did not generate, validate or
apply a new fix, merge a PR, test concurrent pushes, or establish general AI accuracy.
In particular, a correct SQL-injection finding does not independently prove every
possible exploitation claim in an AI explanation. Earlier fix and repeat-delivery
experiments retain their separate evidence.

## 4. What was removed afterward

Cleanup completed and was checked:

- GitHub's webhook setting no longer points to Smee. Its previous Cloudflare
  setting was restored; that old address is inactive.
- The temporary `sentinel-github-relay` container and
  `sentinel-webhook-relay:smee-5.0.0` image were removed.
- The temporary local notification gateway was stopped.
- The saved private Smee channel address, gateway PID record and private restoration
  file were deleted. The channel address was checked against the text deliverables
  before deletion and was absent.
- The existing GitHub App installation remains restricted to the test repository.
  Saved AI credentials and completed reviews were preserved.

Smee has no continuing notification route into this computer from this setup.
Disconnecting prevents further events from being sent through that channel. We
cannot claim deletion of data already received by an external service or revocation
of every copy of its channel URL. No account, payment method or reusable Smee access
credential was created.

**New automatic GitHub reviews are currently disconnected, as requested.** The
GitHub App remains installed, but installation alone does not provide a working
notification connection. A future test needs a reachable approved endpoint. The
existing Cloudflare launcher does not silently switch to Smee. A durable HTTPS
deployment remains future work.

## 5. Automated checks and remaining work

After the readiness repair, the required local checks passed: **647 tests passed,
27 PostgreSQL variants skipped**, and all **36 Docker tests executed**. Overall
coverage was **93.55%**, core coverage **97%**. Ruff lint/format, application typing
(155 source files), strict bridge typing and the strict evaluation-helper typing
check passed. The normal sandbox image was rebuilt. No frontend code changed.

The live test supplies evidence for one real event and one reviewed commit. Larger
quality evaluations, simultaneous pushes, outage recovery, sustained load, deployed
browser acceptance and durable hosting remain separate tasks. Normal offline CI
does not call a paid AI provider or need live credentials.

Further reading: [GitHub's local webhook testing guide](https://docs.github.com/en/webhooks/testing-and-troubleshooting-webhooks/testing-webhooks),
[official Smee client](https://github.com/probot/smee-client),
[Cloudflare Quick Tunnel limitations](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).
