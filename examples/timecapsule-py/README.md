# TimeCapsule

[![Solari](https://img.shields.io/badge/Powered%20by-Solari-687158?style=flat-square)](https://getsolari.com) [![Frontend](https://img.shields.io/badge/Frontend-Next.js%20App%20Router-111111?style=flat-square&logo=nextdotjs&logoColor=white)](https://nextjs.org/docs/app) [![Backend](https://img.shields.io/badge/Backend-Python%20API-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/) [![Checks](https://img.shields.io/github/actions/workflow/status/qeinstein/solari-cookbook/timecapsule.yml?branch=main&style=flat-square&label=checks)](https://github.com/qeinstein/solari-cookbook/actions/workflows/timecapsule.yml)

> Find the futures where your AI agent fails before your users do.

TimeCapsule treats the future as a fuzzing surface. It explores possible
payment, webhook, and wakeup timelines, checks a safety invariant, minimizes a
failing timeline, and replays the same future against a patched agent.

This is a real Solari use case, not a decorative integration: cloud sandboxes
hold isolated worlds, Solari browsers drive the agent-facing UI, and recorded
sessions preserve the evidence of each run.

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
`runs/replays/`. The JSON output includes the sandbox ID, browser session ID,
preview URL, observed action trace, and original/patched statuses.

## Production-shaped checks

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

The Next.js app uses the App Router, strict TypeScript, a tracked npm lockfile,
same-origin API rewrites, explicit loading/empty/error states, reduced-motion
support, and responsive layouts. The Python API adds health checks, no-store
responses, safe future-ID validation, malformed-run handling, and bounded cloud
concurrency.

## Production boundary

This example is production-shaped for a public technical submission and a
single-operator demo. It is not yet a multi-tenant hosted service. Before
putting untrusted users behind it, add:

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

Those are service-operating requirements, not reasons to obscure the current
demo’s boundaries. The local proof remains useful without Solari; the cloud
path is the evidence that the browser, sandbox, isolation, and replay pieces
are materially connected.

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
