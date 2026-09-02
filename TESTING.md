# TimeCapsule complete testing guide

This is the end-to-end checklist for testing every shipped TimeCapsule path:
the deterministic engine, coverage-guided search, benchmark, replay,
minimization, failure boundaries, counterfactual comparison, regressions,
dashboard, API, Solari isolation, recordings, resource limits, fail-soft error
semantics, and the optional OpenRouter model agent.

The implementation lives in `examples/timecapsule-py`. Unless a section says
otherwise, run commands from that directory.

## 1. Fresh-clone setup

Requirements:

- Python 3.10 or newer;
- Node.js 20.9 or newer;
- a Solari API key only for cloud tests;
- an OpenRouter API key only for model-agent tests.

```bash
git clone https://github.com/qeinstein/solari-cookbook.git
cd solari-cookbook/examples/timecapsule-py

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm ci --prefix dashboard
```

Do not commit credentials. Export them only for the cloud sections:

```bash
export TIMECAPSULE_CLOUD_KEY=your_solari_key
export OPENROUTER_API_KEY=your_openrouter_key
```

`SOLARI_API_KEY` is also accepted in place of `TIMECAPSULE_CLOUD_KEY`. In an
interactive terminal, missing Solari and OpenRouter keys are requested with a
hidden prompt and are not written to disk.

## 2. One-command product walkthrough, no keys required

The frozen canonical run is the quickest way to inspect the complete product
without provisioning anything:

```bash
python3 dashboard/dev.py --run demo/solari-canonical.json
```

Open <http://127.0.0.1:3000>. Confirm all of the following:

1. **Replay Theatre** shows `Execution path` on the left and recorded browser
   evidence on the right.
2. The agent card says `DETERMINISTIC`, the run says `Solari run`, and the
   selected failing future says `Invariant violated`.
3. Select `future-0`. Its row becomes selected and the inspector changes to
   `No unsafe contact observed` with a PASS result.
4. Select `future-1`. The inspector shows the payment-staleness failure.
5. Select `future-2`. Both payment and dispute failure classes are visible in
   the tree, and the inspector shows the selected failure class.
6. Click **Replay exact input**. The result must report original FAIL, patched
   PASS, the same input fingerprint, and a verified same-future manifest.
7. Click **Minimize**. The inspector must show fewer events while preserving
   the selected failure class, and the patched result must remain PASS.
8. Inspect **Failure boundary**. It must show the last passing delay, first
   failing delay, and one-minute resolution.
9. Inspect **Original -> Minimize -> Patched** and **Same future manifest**.
   Environment, event input, and world asset hashes must match; only the
   candidate policy changes.
10. Open the original and patched recording links. Each available link must
    return an NDJSON replay rather than a dashboard HTML page.
11. Scroll to **Run summary** and confirm explored futures, novel coverage,
    failure rate, minimization ratio, experiment status, and all six temporal
    coverage windows are present.
12. Resize to a narrow/mobile window. There must be no horizontal overflow,
    clipped heading, hidden action button, or unreadable future row.

Press `Ctrl-C` once to stop both the Python API and Next.js process.

The walkthrough's `future-2` minimization creates an untracked demo artifact.
Inspect it, then remove only that generated file before the final clean-tree
check:

```bash
git status --short demo/
rm -f demo/future-2-minimal.json
```

> **Artifact note:** `Minimize` writes a `*-minimal.json` file beside the run
> file. `Save regression` creates or updates a checked-in file under
> `regressions/`; use that button only when deliberately testing a state-changing
> regression promotion. The automated suite tests it safely in a temporary
> directory.

## 3. CI-equivalent automated verification

Run the backend trust and product suite:

```bash
source .venv/bin/activate
python3 -m unittest discover -s tests -v
python3 -m py_compile main.py dashboard/server.py world/server.py timecapsule/*.py
```

Expected result: all tests pass. The suite currently covers:

- deterministic search across processes and Python hash seeds;
- temporal diversity, genealogy, and shared-prefix accounting;
- payment-staleness and active-dispute failure classes;
- equal-timestamp ordering and timestamp semantics;
- failure-class-preserving minimization;
- one-minute failure-boundary correctness;
- canonical future and environment fingerprints;
- original/patched isolation and counterfactual integrity;
- regression serialization and round trips;
- browser/simulator state, message, action, and violation agreement;
- malformed or reordered browser traces;
- Solari cleanup after partial setup failure;
- fail-soft futures and patched replay `ERROR` semantics;
- environment-budget validation before provisioning;
- OpenRouter structured evidence, model picker, catalogue guard, and
  rate-limit fallback;
- dashboard compare, minimize, regression, and recording APIs;
- claim-scope and canonical-demo integrity.

Run focused suites when diagnosing one area:

```bash
python3 -m unittest discover -s tests -p 'test_product.py' -v
python3 -m unittest discover -s tests -p 'test_trust_audit.py' -v
python3 -m unittest discover -s tests -p 'test_model_agent.py' -v
```

Run the frontend gates:

```bash
npm --prefix dashboard run lint
npm --prefix dashboard run typecheck
npm --prefix dashboard run build
```

To inspect the production server rather than the development server, keep the
Python API running in one terminal and start the built frontend in another:

```bash
# Terminal 1, from examples/timecapsule-py
python3 dashboard/server.py --run runs/latest.json --port 8766

# Terminal 2, from examples/timecapsule-py
npm --prefix dashboard run start
```

## 4. Deterministic local search

Generate a new coverage-guided run:

```bash
python3 main.py run --futures 25 --seed 0 --output runs/latest.json
python3 -m json.tool runs/latest.json >/dev/null
```

The CLI must print:

- futures explored and candidates evaluated;
- coverage features discovered;
- failures and failure classes found;
- the first failing future;
- a minimized event count;
- `original=FAIL, patched=PASS` for the counterfactual comparison;
- the paths of the persisted run and minimized future.

Open that exact run in the dashboard:

```bash
python3 dashboard/dev.py --run runs/latest.json
```

The UI must display the same statuses, event sequences, fingerprints,
boundaries, and comparison outcomes as `runs/latest.json`.

### Determinism check

```bash
python3 main.py run --futures 25 --seed 17 --output runs/determinism-a.json
python3 main.py run --futures 25 --seed 17 --output runs/determinism-b.json

python3 - <<'PY'
import json
from pathlib import Path

a = json.loads(Path("runs/determinism-a.json").read_text())
b = json.loads(Path("runs/determinism-b.json").read_text())
assert a["futures"] == b["futures"]
print("PASS: identical seed produced identical futures")
PY
```

Wall-clock telemetry may differ; the futures and their evidence must not.

## 5. Replay, minimize, compare, and regress

Use `/tmp` for minimization so this test does not add a fixture to the repo:

```bash
cp regressions/delayed-payment-webhook.json /tmp/timecapsule-replay.json

python3 main.py replay /tmp/timecapsule-replay.json
python3 main.py minimize /tmp/timecapsule-replay.json
python3 main.py compare /tmp/timecapsule-replay-minimal.json
python3 main.py regress
```

Expected behavior:

- `replay` returns success only when the original policy reproduces FAIL;
- `minimize` writes `/tmp/timecapsule-replay-minimal.json` and reduces or
  preserves the event count while keeping the same failure class;
- `compare` reports original FAIL and patched PASS;
- `regress` reports every checked-in regression as passing.

Run both checked-in failure classes directly:

```bash
python3 main.py compare regressions/delayed-payment-webhook.json
python3 main.py compare regressions/active-dispute-contact.json
```

Both must report original FAIL and patched PASS.

## 6. Coverage-guided search versus random search

Quick report-generation smoke test:

```bash
python3 main.py benchmark --trials 20 --budget 64 --seed 0 --output runs/search-benchmark-smoke.json
python3 -m json.tool runs/search-benchmark-smoke.json >/dev/null
```

Submission-grade matched benchmark:

```bash
python3 main.py benchmark --trials 200 --budget 128 --seed 0 --output runs/search-benchmark.json
```

Confirm the report contains paired trials with equal unique-evaluation budgets,
per-strategy distributions, medians, failure classes, and evaluations to first
rare failure. Do not infer superiority from one favorable seed. The preserved
reference report is `benchmarks/timecapsule-search-comparison.md` at the
repository root.

## 7. Dashboard API

Start the combined dashboard against a generated run:

```bash
python3 dashboard/dev.py --run runs/latest.json
```

In another terminal:

```bash
curl -fsS http://127.0.0.1:8766/health
curl -fsS http://127.0.0.1:8766/api/run | python3 -m json.tool >/dev/null
curl -fsS -X POST http://127.0.0.1:8766/api/futures/future-1/compare | python3 -m json.tool
curl -fsS -X POST http://127.0.0.1:8766/api/futures/future-1/minimize | python3 -m json.tool
```

Expected results:

- `/health` returns `status: ok` and `run_exists: true`;
- `/api/run` returns the selected persisted run;
- `/compare` returns `same_input: true`, original FAIL, patched PASS, and a
  counterfactual proof;
- `/minimize` returns before/after event counts, the minimal violation,
  boundaries, fingerprints, and saved path.

The state-changing regression endpoint is:

```text
POST /api/futures/:id/regress
```

It is covered using a temporary directory by the automated suite. Calling it
manually writes `regressions/:id.json`.

Test canonical replay serving while the canonical dashboard is running:

```bash
curl -fsS http://127.0.0.1:8766/api/futures/future-2/recording/original | head
curl -fsS http://127.0.0.1:8766/api/futures/future-2/recording/fixed | head
```

Both responses must be NDJSON replay events. Unknown futures and paths outside
the run's allowed replay directory must return an error rather than arbitrary
filesystem content.

## 8. Real Solari cloud execution: policy mode

This section provisions real remote environments. Start with one future and a
maximum of two environments:

```bash
export TIMECAPSULE_CLOUD_KEY=your_solari_key

python3 main.py cloud \
  --agent policy \
  --futures 1 \
  --seed 5 \
  --concurrency 1 \
  --max-environments 2 \
  --output runs/cloud-policy-smoke.json
```

Validate the persisted contract:

```bash
python3 - <<'PY'
import json
from pathlib import Path

run = json.loads(Path("runs/cloud-policy-smoke.json").read_text())
assert run["execution_mode"] == "solari"
assert run["agent_config"]["mode"] == "policy"
assert run["agent_config"]["stochastic"] is False
for future in run["futures"]:
    assert future["status"] in {"PASS", "FAIL", "ERROR"}
    assert future["comparison"]["patched"] in {"PASS", "FAIL", "ERROR", "NOT_RUN"}
    if future["status"] != "ERROR":
        assert future["sandbox_id"]
        assert future["browser_session_id"]
        assert future["observed"]["trace"]
        assert future["browser_simulator_parity"]["verified"] is True
print("PASS: Solari policy evidence contract is valid")
PY
```

Open the cloud output:

```bash
python3 dashboard/dev.py --run runs/cloud-policy-smoke.json
```

Completed futures must show fresh runtime IDs, observed browser actions,
browser/simulator parity, and recording metadata when replay download was
available. Any interrupted future must be `ERROR`, never a false PASS.

### Resource-ceiling guard

This command must fail before search or provisioning because three futures can
require up to six environments:

```bash
python3 main.py cloud --futures 3 --max-environments 5
```

Expected error: the requested futures can provision up to six environments.

### Fail-soft and partial-failure semantics

Remote failures are intentionally simulated in the trust suite rather than by
destroying a live environment:

```bash
python3 -m unittest discover -s tests -p 'test_trust_audit.py' -v
```

The assertions prove that one failed future does not discard successful
evidence, and that an original FAIL followed by a patched environment failure
persists the original evidence while reporting patched `ERROR`—not PASS or
FAIL.

## 9. OpenRouter model-agent execution

Model mode still uses a real Solari browser and sandbox; only the action policy
is selected through OpenRouter. Keep the deterministic canonical dataset
unchanged.

### Interactive model picker

```bash
export TIMECAPSULE_CLOUD_KEY=your_solari_key
export OPENROUTER_API_KEY=your_openrouter_key
python3 main.py cloud --agent model --futures 1 --max-environments 2
```

The terminal must show three `FREE` models first and two `PAID` models after
them. Select a number to continue.

### Fully non-interactive model run

```bash
python3 main.py cloud \
  --agent model \
  --model minimax/minimax-m3:free \
  --temperature 0.2 \
  --futures 1 \
  --seed 5 \
  --concurrency 1 \
  --max-environments 2 \
  --output runs/cloud-model-smoke.json
```

Validate model evidence:

```bash
python3 - <<'PY'
import json
from pathlib import Path

run = json.loads(Path("runs/cloud-model-smoke.json").read_text())
config = run["agent_config"]
assert config["mode"] == "model"
assert config["provider"] == "openrouter"
assert config["stochastic"] is True
assert "requested_model" in config and "active_model" in config
for future in run["futures"]:
    if future["status"] == "ERROR":
        continue
    evidence = future["agent_evidence"]
    assert evidence["stochastic"] is True
    for decision in evidence["decisions"]:
        assert decision["action"] in {"send_reminder", "suppress"}
        for field in (
            "model", "temperature", "prompt_hash", "observation_hash",
            "model_response", "future_fingerprint", "environment_fingerprint",
        ):
            assert field in decision
    assert future["exact_behavior_reproducible"] is False
print("PASS: model evidence contract is valid")
PY
```

Open it in the dashboard:

```bash
python3 dashboard/dev.py --run runs/cloud-model-smoke.json
```

The execution card must show `MODEL: <model id>`, temperature, prompt hash, and
`stochastic`. The UI must not claim that identical future fingerprints imply
identical model behavior.

### Missing-key prompt

To exercise the secure prompt, keep the Solari key exported and remove only the
OpenRouter key for one interactive run:

```bash
unset OPENROUTER_API_KEY
python3 main.py cloud --agent model --model minimax/minimax-m3:free --futures 1 --max-environments 2
```

The terminal must say that the OpenRouter key was not detected and accept it
without echoing or persisting it.

### Untested-model guard

With keys configured, this must stop before provisioning:

```bash
python3 main.py cloud --agent model --model example/untested-model --futures 1 --max-environments 2
```

Expected result: a message requiring `--allow-untested-model`. The override is
deliberate and should only be used with a real OpenRouter model ID.

### Rate-limit fallback

Do not try to manufacture a real provider rate limit. Run the deterministic
adapter test instead:

```bash
python3 -m unittest discover -s tests -p 'test_model_agent.py' -v
```

It injects an OpenRouter 429 response, verifies routing to the next free model,
and confirms that the active model and fallback genealogy are persisted.

## 10. Final repository and submission verification

From the repository root:

```bash
cd ../..
git status --short
git remote -v
git log -5 --oneline
```

Success criteria:

- `git status --short` is empty after intentional test artifacts are removed;
- `origin` points to `https://github.com/qeinstein/solari-cookbook.git`;
- the GitHub repository is public and visibly marked as forked from
  `solari-sdk/solari-cookbook`;
- `examples/timecapsule-py/demo/solari-canonical.json` and its replay assets are
  still tracked and unchanged;
- the latest **TimeCapsule checks** GitHub Actions run passes both Python
  versions and the Next.js production build.

If GitHub CLI is authenticated, verify the fork metadata directly:

```bash
gh api repos/qeinstein/solari-cookbook \
  --jq '{full_name,visibility,fork,parent:.parent.full_name,source:.source.full_name}'
```

Expected values: public visibility, `fork: true`, and parent/source
`solari-sdk/solari-cookbook`.

## Functionality matrix

| Functionality | Primary test |
| --- | --- |
| Coverage-guided future generation | Section 4 + `test_product.py` |
| Random versus guided benchmark | Section 6 + `test_trust_audit.py` |
| Both temporal failure classes | Sections 2 and 5 |
| Failure-class minimization | Sections 2 and 5 |
| One-minute failure boundary | Sections 2 and 3 |
| Same-future counterfactual | Sections 2, 5, and 7 |
| Regression serialization | Section 5 + automated API test |
| Browser/simulator agreement | Sections 3 and 8 |
| Solari isolation and cleanup | Sections 3 and 8 |
| Recordings | Sections 2, 7, and 8 |
| Fail-soft partial errors | Section 8 trust suite |
| Resource ceiling | Section 8 guard |
| Deterministic policy agent | Sections 4 and 8 |
| OpenRouter model agent | Section 9 |
| Model picker and key prompt | Section 9 |
| Free-model rate-limit fallback | Section 9 adapter test |
| Next.js dashboard and responsive UI | Sections 2 and 3 |
| Public-fork submission compliance | Section 10 |
