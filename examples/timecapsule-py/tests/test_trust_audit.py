import asyncio
import json
import os
from http.server import ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread
import types
import unittest
from urllib.request import Request, urlopen
from unittest.mock import patch

from timecapsule.benchmark import run_benchmark
from timecapsule.core import (
    execute,
    future_fingerprint,
    invariant_holds,
    invariant_violations,
    load_future,
    observed_invariant_holds,
    save_future,
)
from timecapsule.evidence import counterfactual_proof
from timecapsule.evidence import environment_manifest
from timecapsule.runner import local_future_entry
from timecapsule.search import Scenario, coverage_guided_search, find_failure_boundaries, _with_webhook_delay
from timecapsule.search import SearchResult
from timecapsule.solari_runner import EVENT_ACTIONS, browser_simulator_parity, solari_future, solari_run, timestamp_observed_trace
import world.server as browser_world


EXAMPLE_ROOT = Path(__file__).parents[1]


class CoreTrustAuditTests(unittest.TestCase):
    def test_search_is_deterministic_across_python_hash_seeds(self):
        script = (
            "import json; "
            "from timecapsule.search import coverage_guided_search; "
            "from timecapsule.core import future_fingerprint; "
            "print(json.dumps([future_fingerprint(f.events) for f in coverage_guided_search(20, 4).futures]))"
        )
        outputs = []
        for hash_seed in ("1", "997"):
            environment = os.environ.copy()
            environment["PYTHONHASHSEED"] = hash_seed
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=EXAMPLE_ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            outputs.append(json.loads(result.stdout))
        self.assertEqual(outputs[0], outputs[1])

    def test_mutation_genealogy_has_valid_parent_prefixes(self):
        search = coverage_guided_search(50)
        positions = {future.future_id: index for index, future in enumerate(search.futures)}
        by_id = {future.future_id: future for future in search.futures}
        for future in search.futures:
            if future.parent_future_id is None:
                continue
            self.assertLess(positions[future.parent_future_id], positions[future.future_id])
            parent = by_id[future.parent_future_id]
            shared = 0
            for left, right in zip(future.events, parent.events):
                if left.as_dict() != right.as_dict():
                    break
                shared += 1
            self.assertEqual(future.shared_prefix_events, shared)

    def test_boundary_reports_a_true_cut_for_every_generated_failure(self):
        search = coverage_guided_search(20)
        for future in search.futures:
            for boundary in find_failure_boundaries(future.events):
                passing = _with_webhook_delay(
                    future.events,
                    boundary["failure_type"],
                    boundary["last_passing_minutes"],
                )
                failing = _with_webhook_delay(
                    future.events,
                    boundary["failure_type"],
                    boundary["first_failing_minutes"],
                )
                self.assertFalse(any(item["type"] == boundary["failure_type"] for item in invariant_violations(execute(passing))))
                self.assertTrue(any(item["type"] == boundary["failure_type"] for item in invariant_violations(execute(failing))))

    def test_regression_round_trip_preserves_events_and_outcome(self):
        regression_dir = EXAMPLE_ROOT / "regressions"
        with tempfile.TemporaryDirectory() as directory:
            for source in sorted(regression_dir.glob("*.json")):
                events = load_future(source)
                output = Path(directory) / source.name
                with self.subTest(source=source.name):
                    save_future(output, events)
                    self.assertEqual(
                        [event.as_dict() for event in load_future(output)],
                        [event.as_dict() for event in events],
                    )
                    self.assertEqual(json.loads(output.read_text())["result"], {
                        "original": "FAIL",
                        "patched": "PASS",
                    })

    def test_regression_serialization_rejects_a_false_supplied_result(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "does not match"):
                save_future(
                    Path(directory) / "tampered.json",
                    Scenario(1, 720, (540,)).events(),
                    {"original": "PASS", "patched": "FAIL"},
                )

    def test_benchmark_is_paired_and_uses_exact_unique_budget(self):
        first = run_benchmark(trials=8, budget=24, seed_start=9)
        second = run_benchmark(trials=8, budget=24, seed_start=9)
        self.assertEqual(first, second)
        for strategy in ("random", "coverage_guided"):
            self.assertTrue(all(
                trial["futures_evaluated"] == 24
                for trial in first[strategy]["trials"]
            ))
        self.assertTrue(first["config"]["paired_trial_seeds"])

    def test_counterfactual_proof_does_not_equate_event_hash_with_world_identity(self):
        events = Scenario(1, 720, (540,)).events()
        proof = counterfactual_proof(events)
        self.assertEqual(proof["original"]["event_hash"], proof["patched"]["event_hash"])
        self.assertIn("world_asset_hash", proof["identical_fields"])
        self.assertIn("initial_state_hash", proof["identical_fields"])
        self.assertIn("fixture_hash", proof["identical_fields"])
        original = environment_manifest(events, "original")
        with patch("timecapsule.evidence.world_asset_hash", return_value="tampered-world"):
            altered_world = environment_manifest(events, "original")
        self.assertEqual(original["event_hash"], altered_world["event_hash"])
        self.assertNotEqual(original["world_asset_hash"], altered_world["world_asset_hash"])
        self.assertNotEqual(original["environment_hash"], altered_world["environment_hash"])

    def test_timestamp_adapter_rejects_reordered_or_missing_browser_actions(self):
        events = Scenario(1, 0, (0,)).events()
        with self.assertRaises(RuntimeError):
            timestamp_observed_trace(
                [{"action": "webhook"}],
                events,
            )
        complete_actions = []
        for event in events:
            if event.kind == "invoice_created":
                continue
            complete_actions.append({"action": EVENT_ACTIONS.get(event.kind, "agent/original")})
        with self.assertRaisesRegex(RuntimeError, "missing state evidence"):
            timestamp_observed_trace(complete_actions, events)

    def test_fingerprint_is_independent_of_serialized_event_order(self):
        events = Scenario(1, 720, (540,), 120, 1440).events()
        self.assertEqual(future_fingerprint(events), future_fingerprint(list(reversed(events))))

    def test_boundary_search_rejects_ambiguous_duplicate_sync_inputs(self):
        events = Scenario(1, 720, (540,)).events()
        events.append(next(event for event in events if event.kind == "payment_webhook"))
        with self.assertRaisesRegex(ValueError, "exactly one payment_webhook"):
            find_failure_boundaries(events)


class BrowserParityAuditTests(unittest.TestCase):
    def setUp(self):
        browser_world.reset()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), browser_world.Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, method="GET"):
        request = Request(
            f"http://127.0.0.1:{self.server.server_port}{path}",
            method=method,
        )
        with urlopen(request) as response:
            return json.load(response)

    def run_browser_future(self, events, fixed):
        self.request("/reset", "POST")
        for event in events:
            if event.kind == "invoice_created":
                continue
            action = (
                f"agent/{'fixed' if fixed else 'original'}"
                if event.kind == "agent_wakeup"
                else EVENT_ACTIONS[event.kind]
            )
            self.request(f"/{action}", "POST")
        state = self.request("/state")
        trace = timestamp_observed_trace(state["trace"], events, fixed=fixed)
        return state, trace

    def test_browser_world_matches_simulator_for_original_and_fixed_agents(self):
        events = Scenario(1, 720, (540,), 120, 1440).events()
        for fixed in (False, True):
            with self.subTest(fixed=fixed):
                state, trace = self.run_browser_future(events, fixed)
                simulated = execute(events, fixed=fixed)
                self.assertEqual(
                    (state["payment"], state["crm"], state["dispute"], state["crm_dispute"]),
                    (
                        simulated.payment_status,
                        simulated.invoice_status,
                        simulated.dispute_status,
                        simulated.crm_dispute_status,
                    ),
                )
                self.assertEqual(len(state["messages"]), len(simulated.messages))
                self.assertEqual(
                    observed_invariant_holds(trace),
                    invariant_holds(simulated),
                )
                parity = browser_simulator_parity(
                    {
                        "payment": state["payment"],
                        "crm": state["crm"],
                        "dispute": state["dispute"],
                        "crm_dispute": state["crm_dispute"],
                        "messages": "\n".join(state["messages"]) if state["messages"] else "No messages sent.",
                    },
                    trace,
                    events,
                    fixed=fixed,
                )
                self.assertTrue(parity["verified"])
                self.assertTrue(parity["trace_state_match"])

                tampered_trace = [dict(item) for item in trace]
                tampered_trace[0]["crm"] = "paid"
                with self.assertRaisesRegex(RuntimeError, "trace mismatch"):
                    browser_simulator_parity(
                        {
                            "payment": state["payment"],
                            "crm": state["crm"],
                            "dispute": state["dispute"],
                            "crm_dispute": state["crm_dispute"],
                            "messages": "\n".join(state["messages"]) if state["messages"] else "No messages sent.",
                        },
                        tampered_trace,
                        events,
                        fixed=fixed,
                    )


class SolariCleanupAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_sandbox_is_killed_when_remote_setup_fails(self):
        tracker = {"created": None, "killed": False}

        class FailingCommands:
            async def run(self, *_args, **_kwargs):
                raise RuntimeError("simulated remote setup failure")

        class FakeSandbox:
            sandboxId = "audit-sandbox"
            commands = FailingCommands()

            async def connect(self):
                return None

            async def kill(self):
                tracker["killed"] = True

        class FakeClient:
            def __init__(self, **_kwargs):
                tracker["created"] = True

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def create(self, **_kwargs):
                return FakeSandbox()

        fake_browser = types.ModuleType("solari_browser")
        fake_browser.Solari = object
        fake_errors = types.ModuleType("solari_browser.errors")
        fake_errors.SolariError = RuntimeError
        fake_sandbox = types.ModuleType("solari_sandbox")
        fake_sandbox.SandboxClient = FakeClient
        future = coverage_guided_search(1).futures[0]
        environment = {"SOLARI_API_KEY": "test-only"}
        with patch.dict(sys.modules, {
            "solari_browser": fake_browser,
            "solari_browser.errors": fake_errors,
            "solari_sandbox": fake_sandbox,
        }), patch.dict(os.environ, environment, clear=False):
            with self.assertRaisesRegex(RuntimeError, "simulated remote setup failure"):
                await solari_future(future)
        self.assertTrue(tracker["created"])
        self.assertTrue(tracker["killed"])


class SolariFailureSemanticsTests(unittest.IsolatedAsyncioTestCase):
    def remote_result(self, future, status, fixed=False):
        result = local_future_entry(future)
        result.update({
            "agent": "fixed" if fixed else "original",
            "status": status,
            "sandbox_id": f"{'fixed' if fixed else 'original'}-{future.future_id}",
            "browser_session_id": f"{'fixed' if fixed else 'original'}-{future.future_id}",
            "recording_status": "not_ready_after_30s",
        })
        if status == "PASS":
            result["violation"] = None
            result["violations"] = []
            result["failure_modes"] = []
        return result

    def search_result(self, futures):
        return SearchResult(
            futures=futures,
            candidates_evaluated=len(futures),
            features_discovered=set(),
            accepted_mutations=0,
        )

    async def test_original_environment_error_does_not_discard_other_futures(self):
        futures = coverage_guided_search(3).futures
        calls = []

        async def fake_future(future, fixed=False, recording_dir=None):
            calls.append((future.future_id, fixed))
            if not fixed and future.future_id == futures[2].future_id:
                raise RuntimeError("browser initialization timeout")
            if fixed:
                return self.remote_result(future, "PASS", fixed=True)
            return self.remote_result(future, "FAIL" if future.future_id == futures[1].future_id else "PASS")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "cloud.json"
            with patch("timecapsule.solari_runner.cloud_api_key", return_value="test-only"), \
                    patch("timecapsule.solari_runner.coverage_guided_search", return_value=self.search_result(futures)), \
                    patch("timecapsule.solari_runner.solari_future", side_effect=fake_future):
                payload = await solari_run(3, 0, output, concurrency=2, max_environments=6)

            entries = payload["futures"]
            self.assertEqual([entry["status"] for entry in entries], ["PASS", "FAIL", "ERROR"])
            self.assertEqual(entries[1]["comparison"], {"original": "FAIL", "patched": "PASS"})
            self.assertEqual(entries[2]["comparison"], {"original": "ERROR", "patched": "NOT_RUN"})
            self.assertEqual(entries[2]["error"]["phase"], "original")
            self.assertTrue(output.exists())
            self.assertEqual(json.loads(output.read_text())["futures"][2]["status"], "ERROR")
            self.assertEqual(payload["summary"]["completion_status"], "COMPLETE_WITH_ERRORS")
            self.assertEqual(payload["summary"]["errors"], 1)
            self.assertNotIn((futures[2].future_id, True), calls)

    async def test_patched_error_preserves_original_failure_without_verdict(self):
        future = coverage_guided_search(1).futures[0]

        async def fake_future(candidate, fixed=False, recording_dir=None):
            if fixed:
                raise RuntimeError("patched environment died")
            return self.remote_result(candidate, "FAIL")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "patched-error.json"
            original_hash = future_fingerprint(future.events)
            with patch("timecapsule.solari_runner.cloud_api_key", return_value="test-only"), \
                    patch("timecapsule.solari_runner.coverage_guided_search", return_value=self.search_result([future])), \
                    patch("timecapsule.solari_runner.solari_future", side_effect=fake_future):
                payload = await solari_run(1, 0, output, max_environments=2)

            entry = payload["futures"][0]
            self.assertEqual(entry["status"], "FAIL")
            self.assertEqual(entry["comparison"], {"original": "FAIL", "patched": "ERROR"})
            self.assertEqual(entry["patched_run"]["status"], "ERROR")
            self.assertEqual(entry["patched_run"]["error"]["phase"], "patched")
            self.assertEqual(entry["input_hash"], original_hash)
            self.assertEqual(entry["patched_run"]["input_hash"], original_hash)
            self.assertFalse(entry["counterfactual_proof"]["runtime"]["verified"])
            self.assertEqual(entry["counterfactual_proof"]["runtime"]["status"], "ERROR")
            self.assertEqual(payload["summary"]["completion_status"], "COMPLETE_WITH_ERRORS")
            self.assertEqual(payload["summary"]["errors"], 1)
            self.assertTrue(output.exists())

    async def test_environment_budget_rejects_before_search_or_provisioning(self):
        with patch("timecapsule.solari_runner.cloud_api_key") as key, \
                patch("timecapsule.solari_runner.coverage_guided_search") as search:
            with self.assertRaisesRegex(SystemExit, "can provision up to 6 environments"):
                await solari_run(3, 0, Path("runs/should-not-exist.json"), max_environments=5)
        key.assert_not_called()
        search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
