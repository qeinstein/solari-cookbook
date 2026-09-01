# TimeCapsule

Find the futures where your AI agent fails before your users do.

This example treats the future as a fuzzing surface. It explores possible
payment/webhook/wakeup timelines, checks a deterministic safety invariant,
minimizes a failing timeline, and replays the same future against a patched
agent.

Solari is part of the execution model: every future runs in its own sandbox,
the sandbox serves an isolated collections app through a preview URL, and a
separate Solari cloud browser drives the agent-facing UI. Futures can run in
parallel without sharing world state.

## Run the local proof

No API key is needed for the deterministic local proof:

```bash
python3 main.py run --futures 25
python3 -m unittest discover -s tests -v
```

This finds a delayed-payment failure, reduces it to the payment → wakeup →
webhook sequence, compares the original and patched agent, and writes a trace
under `runs/`.

The same local CLI is available as a package command from this example
directory:

```bash
python3 -m timecapsule run --futures 25
```

## Run with Solari

```bash
pip install -r requirements.txt
export SOLARI_API_KEY=slr_live_...  # https://console.getsolari.com
python3 main.py solari --futures 3
```

Each future creates and destroys its own sandbox and browser session. The
browser session is created with recording enabled; after release, TimeCapsule
polls Solari for the rrweb DOM replay (not a video) and saves available
recordings under `runs/replays/`. The output also includes the session IDs and
preview URLs needed to inspect a run. Failing futures are then replayed in
fresh isolated pairs with the fixed agent, and the complete result is written
to `runs/solari-latest.json` (use a higher `--futures` value only within your
account's concurrency limit).

## Dashboard

The dashboard is a Next.js App Router frontend backed by the small Python API.
Run both processes after a local run:

```bash
python3 dashboard/server.py --run runs/latest.json --port 8766

cd dashboard
npm install
npm run dev
```

Open `http://127.0.0.1:3000` to inspect the future tree, failure invariant,
event sequence, replay comparison, and minimization result. The Next.js app
proxies `/api/*` to the Python service, so the browser does not need a CORS
exception. Set `TIMECAPSULE_API_ORIGIN` when the API is not on
`http://127.0.0.1:8766`; see `dashboard/.env.example`.

For a production build of the frontend:

```bash
cd dashboard
npm run lint
npm run typecheck
npm run build
npm run start
```

The API also exposes `GET /health` for a process-level health check. Select a
failure and use **Save regression** to promote its reproducible event sequence
into `regressions/<future-id>.json`.

The same workflow is available from the command line:

```bash
python3 main.py replay regressions/delayed-payment-webhook.json
python3 main.py minimize regressions/delayed-payment-webhook.json
python3 main.py compare regressions/delayed-payment-webhook-minimal.json
python3 main.py regress
```

## The failure

The vulnerable agent trusts the CRM. A customer payment changes the payment
system immediately, but a delayed webhook leaves the CRM showing `OVERDUE`.
If the agent wakes during that stale window it sends an incorrect collection
message. The patched agent verifies the payment system before contacting the
customer.
