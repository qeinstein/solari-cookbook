# TimeCapsule

[![Solari](https://img.shields.io/badge/Powered%20by-Solari-687158?style=flat-square)](https://getsolari.com) [![Frontend](https://img.shields.io/badge/Frontend-Next.js%20App%20Router-111111?style=flat-square&logo=nextdotjs&logoColor=white)](https://nextjs.org/docs/app) [![Backend](https://img.shields.io/badge/Backend-Python%20API-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/) [![Checks](https://img.shields.io/github/actions/workflow/status/qeinstein/solari-cookbook/timecapsule.yml?branch=main&style=flat-square&label=checks)](https://github.com/qeinstein/solari-cookbook/actions/workflows/timecapsule.yml)

> Find the futures where your AI agent fails before your users do.

TimeCapsule treats the future as a fuzzing surface. It explores possible
payment, webhook, and wakeup timelines, checks a safety invariant, minimizes a
failing timeline, and replays the same future against a patched agent.

This is a real Solari use case, not a decorative integration: cloud sandboxes
hold isolated worlds, Solari browsers drive the agent-facing UI, and recorded
sessions preserve the evidence of each run.

## The 90-second demo

```bash
cd examples/timecapsule-py
source .venv/bin/activate
python3 main.py run --futures 25
python3 dashboard/dev.py
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000), then:

1. Open the first red branch and point out the recorded contradiction:
   payment `PAID`, CRM `OVERDUE`, agent belief `OVERDUE`.
2. Click **Minimize**. The candidate visibly collapses from six events to the
   three-event counterexample: payment → unsafe wakeup → webhook.
3. Click **Replay exact input**. The fingerprint stays fixed while the result
   changes from original `FAIL` to patched `PASS`.
4. Select a green branch to show that safe futures are inspectable too.

That is the product loop: **FAIL → MINIMIZE → PATCHED PASS**, with the input and
causal state visible rather than implied.

## How it works

```mermaid
flowchart LR
  G[Deterministic future generator] --> O[TimeCapsule orchestrator]
  O --> S1[Solari sandbox A]
  O --> S2[Solari sandbox B]
  S1 --> B1[Recorded Solari browser]
  S2 --> B2[Recorded Solari browser]
  B1 --> T[Observed action trace]
  B2 --> T
  T --> I{Invariant holds?}
  I -- no --> M[Delta-debug minimizer]
  M --> R[Replay exact input with patched agent]
  R --> X[Regression artifact]
```

The deterministic generator varies payment timing, webhook delay, and one to
three agent wakeups across three meaningful windows: before payment, during the
paid-but-stale interval, and after webhook delivery. A SHA-256 fingerprint over
the ordered event input binds the original and counterfactual runs.

### Why Solari is essential

- A fresh **Solari sandbox** hosts each future's world state, preventing one
  branch from contaminating another.
- A fresh **Solari browser** drives the real world UI instead of calling an
  in-process mock and records the observed action trace.
- **Session recording** preserves replayable browser evidence when the Solari
  replay is available.
- Failing seeds are run again in new isolated environments with the same event
  fingerprint, so a patch cannot pass by silently changing its test input.

## What you get

- **Deterministic local proof** — fast, repeatable exploration with no API key.
- **Isolated cloud execution** — one Solari sandbox and browser session per
  future, with bounded concurrency for predictable account usage.
- **Temporal evidence** — ordered world actions prove whether contact happened
  before the payment webhook, even after the final CRM state changes.
- **Counterfactual replay** — the same failing future runs against the fixed
  agent and must pass.
- **Regression promotion** — save a minimized future as a checked-in JSON case.
- **Premium dashboard** — a typed Next.js frontend with responsive states,
  accessible controls, restrained motion, and a Python API behind a same-origin
  rewrite.

## The scenario

The vulnerable collections agent trusts a stale CRM record. A customer payment
updates the payment system immediately, but the webhook arrives later. If the
agent wakes during that window, it sends an incorrect overdue reminder.

The patched agent verifies the payment source before contacting the customer.
TimeCapsule makes that race explicit and checks the invariant:

```text
no_contact_during_stale_payment_window
```

## Quick start: local proof

Requirements: Python 3.10+ and Node.js 20.9+ for the dashboard.

```bash
cd examples/timecapsule-py
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python3 main.py run --futures 25
python3 -m unittest discover -s tests -v
```

The local run writes `runs/latest.json`, minimizes the first failure, and
prints the original-versus-patched result. The generated futures are
deterministic for a given seed, so the checked-in regressions are reproducible:

```bash
python3 main.py regress
```

## Open the dashboard

The UI and API are intentionally separate processes. This keeps the Next.js
frontend deployable as a normal Node.js server while the Python service owns
future execution and filesystem artifacts.

For the smoothest local experience, start both with one command:

```bash
cd examples/timecapsule-py
source .venv/bin/activate
python3 dashboard/dev.py
```

Then open [http://127.0.0.1:3000](http://127.0.0.1:3000). Press `Ctrl-C` to
stop both processes cleanly.

Terminal 1 — API:

```bash
cd examples/timecapsule-py
source .venv/bin/activate
python3 dashboard/server.py --run runs/latest.json --port 8766
```

Terminal 2 — Next.js frontend:

```bash
cd examples/timecapsule-py/dashboard
npm ci
npm run dev
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). The app proxies `/api/*`
to `http://127.0.0.1:8766`, avoiding browser CORS configuration. If the API is
elsewhere, copy `dashboard/.env.example` to `.env.local` and set:

```bash
TIMECAPSULE_API_ORIGIN=https://your-api.example.com
```

The Python API exposes `GET /health` for a process-level health check and these
dashboard actions:

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/run` | Load the latest persisted exploration |
| `POST` | `/api/futures/:id/compare` | Replay original and patched agents |
| `POST` | `/api/futures/:id/minimize` | Save the smallest failing future |
| `POST` | `/api/futures/:id/regress` | Promote the future into `regressions/` |

## Run with Solari

Set the key in your shell or a secret manager. Never expose it to the browser
or commit it to the repository.

```bash
cd examples/timecapsule-py
source .venv/bin/activate
export SOLARI_API_KEY=slr_live_...
python3 main.py solari --futures 3 --concurrency 1
```

`--concurrency 1` is the safe default for a new or low-limit account. Increase
it only when the account allows more simultaneous sandbox/browser pairs:

```bash
python3 main.py solari --futures 10 --concurrency 2
```

Each future creates and destroys its own sandbox and browser pair. The browser
session is created with recording enabled; after release, TimeCapsule polls
Solari for the rrweb DOM replay and saves available recordings under
`runs/replays/`. The JSON output includes the input fingerprint, violation
snapshot, sandbox ID, browser session ID, preview URL, observed action trace,
recording status, and original/patched evidence. To inspect that cloud run:

```bash
python3 dashboard/dev.py --run runs/solari-latest.json
```

## Verification

Run the same gates used by CI before sharing a change:

```bash
cd examples/timecapsule-py
source .venv/bin/activate
python3 -m unittest discover -s tests -v

cd dashboard
npm ci
npm run lint
npm run typecheck
npm run build
npm run start
```

The suite checks temporal diversity, both safe and unsafe futures, the shared
observed-trace invariant, counterexample minimization, exact input fingerprints,
regression promotion, and API evidence payloads. The Next.js app uses strict
TypeScript, a tracked lockfile, same-origin rewrites, explicit loading and error
states, reduced-motion support, and responsive layouts.

## Honest boundary

This is a verified technical submission and single-operator demo, not a
multi-tenant hosted service. Before putting untrusted users behind it, add:

- durable run and replay storage instead of local `runs/` files;
- authentication, authorization, request quotas, and per-user isolation;
- a background job queue for long Solari explorations and retry policies for
  transient provider errors;
- structured logs, metrics, alerting, and retention policies for recordings;
- a deployment secret manager for `SOLARI_API_KEY`, plus separate staging and
  production accounts;
- browser end-to-end tests and a credentialed Solari smoke job in CI;
- provider-limit awareness for sandbox/browser budgets and cleanup on worker
  termination.

The local proof intentionally works without a Solari key for fast iteration.
It does not count as cloud evidence; the `solari` command is the path that
proves browser, sandbox, isolation, and recording are materially connected.

## Submission provenance

TimeCapsule lives directly inside the public
[`qeinstein/solari-cookbook`](https://github.com/qeinstein/solari-cookbook)
fork of [`solari-sdk/solari-cookbook`](https://github.com/solari-sdk/solari-cookbook).
It is not a nested or standalone repository.

## Command-line replay workflow

```bash
python3 main.py replay regressions/delayed-payment-webhook.json
python3 main.py minimize regressions/delayed-payment-webhook.json
python3 main.py compare regressions/delayed-payment-webhook-minimal.json
python3 main.py regress
```

## Repository layout

```text
timecapsule-py/
├── dashboard/              # Next.js App Router frontend + Python API
├── regressions/            # minimized, checked-in failure futures
├── timecapsule/            # deterministic world and package CLI
├── world/                  # browser-drivable Solari sandbox world
├── main.py                 # local and cloud execution entrypoint
└── tests/                  # product-loop and API checks
```

## Links

- [Solari Cookbook](https://github.com/solari-sdk/solari-cookbook)
- [Solari documentation](https://docs.getsolari.com)
- [Solari console](https://console.getsolari.com)
- [Next.js App Router](https://nextjs.org/docs/app)

MIT licensed.
