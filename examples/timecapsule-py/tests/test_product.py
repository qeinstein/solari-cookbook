import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.request import Request, urlopen

from dashboard.server import make_handler
from main import future_coverage, local_run, timestamp_observed_trace
from timecapsule.core import (
    comparison,
    execute,
    future_fingerprint,
    generate_future,
    invariant_holds,
    invariant_violations,
    minimize,
    minimize_for_violation,
    observed_invariant_holds,
    observed_violation,
    temporal_windows,
)
from timecapsule.evidence import counterfactual_proof
from timecapsule.execution import execute_future
from timecapsule.search import Scenario, coverage_guided_search, find_failure_boundaries
from http.server import ThreadingHTTPServer


class ProductLoopTests(unittest.TestCase):
    def test_temporal_failure_minimizes_and_patch_replays(self):
        events = generate_future(0)
        self.assertFalse(invariant_holds(execute(events)))
        minimal = minimize(events)
        self.assertEqual(len(minimal), 3)
        self.assertEqual(comparison(minimal), {"original": "FAIL", "patched": "PASS"})

    def test_world_assets_are_browser_drivable(self):
        html = Path(__file__).parents[1] / "world/index.html"
        text = html.read_text()
        self.assertIn('data-action="pay"', text)
        self.assertIn('data-action="agent/original"', text)
        self.assertIn('data-action="agent/fixed"', text)
        self.assertIn('data-action="dispute"', text)
        self.assertIn('data-action="dispute-webhook"', text)
        self.assertIn('id="dispute"', text)
        self.assertIn('id="crm-dispute"', text)
        self.assertIn('id="sync-status"', text)
        self.assertIn('id="trace"', text)

    def test_generator_explores_multiple_temporal_shapes(self):
        futures = [generate_future(seed) for seed in range(250)]
        shapes = {tuple(event.kind for event in events) for events in futures}
        statuses = {invariant_holds(execute(events)) for events in futures}
        windows = set().union(*(temporal_windows(events) for events in futures))

        self.assertGreaterEqual(len(shapes), 10)
        self.assertEqual({len(events) for events in futures}, {4, 5, 6})
        self.assertEqual(statuses, {False, True})
        self.assertEqual(windows, {"before_payment", "stale_window", "after_webhook"})

    def test_future_coverage_reports_temporal_windows(self):
        search = coverage_guided_search(25)
        coverage = future_coverage([future.events for future in search.futures])
        self.assertEqual(coverage["covered"], 6)
        self.assertEqual(coverage["possible"], 6)
        self.assertEqual(
            {pattern["id"] for pattern in coverage["patterns"]},
            {
                "payment-window:before",
                "payment-window:stale",
                "payment-window:after",
                "dispute-window:before",
                "dispute-window:active",
                "dispute-window:after",
            },
        )

    def test_coverage_guided_search_is_deterministic_and_mutates_parents(self):
        left = coverage_guided_search(25, seed_start=7)
        right = coverage_guided_search(25, seed_start=7)
        self.assertEqual(
            [future_fingerprint(future.events) for future in left.futures],
            [future_fingerprint(future.events) for future in right.futures],
        )
        self.assertEqual(left.candidates_evaluated, right.candidates_evaluated)
        self.assertGreater(left.accepted_mutations, 0)
        self.assertTrue(any(future.parent_future_id for future in left.futures))
        self.assertTrue(any(future.shared_prefix_events > 1 for future in left.futures))
        self.assertEqual(
            [future_fingerprint(future.events) for future in coverage_guided_search(10, 7).futures],
            [future_fingerprint(future.events) for future in left.futures[:10]],
        )

    def test_search_finds_both_collections_failure_modes(self):
        search = coverage_guided_search(25)
        signatures = {
            tuple(sorted({item["type"] for item in invariant_violations(execute(future.events))}))
            for future in search.futures
        }
        self.assertIn(("stale_payment_contact",), signatures)
        self.assertIn(("active_dispute_contact",), signatures)
        self.assertIn(("active_dispute_contact", "stale_payment_contact"), signatures)
        self.assertGreaterEqual(len(search.features_discovered), 40)

    def test_failure_boundary_is_binary_searched_to_one_minute(self):
        payment = Scenario(1, 720, (540,)).events()
        dispute = Scenario(1, 0, (-180,), -360, 1440).events()
        payment_boundary = find_failure_boundaries(payment)[0]
        dispute_boundary = find_failure_boundaries(dispute)[0]
        self.assertEqual(
            (payment_boundary["last_passing_minutes"], payment_boundary["first_failing_minutes"]),
            (540, 541),
        )
        self.assertEqual(
            (dispute_boundary["last_passing_minutes"], dispute_boundary["first_failing_minutes"]),
            (180, 181),
        )
        self.assertEqual(payment_boundary["resolution_minutes"], 1)
        self.assertEqual(dispute_boundary["resolution_minutes"], 1)

    def test_fixed_agent_suppresses_active_dispute_contact(self):
        events = Scenario(1, 0, (-180,), -360, 1440).events()
        self.assertFalse(invariant_holds(execute(events)))
        self.assertTrue(invariant_holds(execute(events, fixed=True)))
        self.assertEqual(comparison(events), {"original": "FAIL", "patched": "PASS"})

    def test_minimizer_preserves_the_selected_failure_class(self):
        events = Scenario(1, 0, (-180,), -360, 1440).events()
        self.assertEqual(
            {item["type"] for item in invariant_violations(execute(events))},
            {"active_dispute_contact"},
        )
        minimal = minimize_for_violation(events, "active_dispute_contact")
        self.assertEqual(
            {item["type"] for item in invariant_violations(execute(minimal))},
            {"active_dispute_contact"},
        )
        self.assertTrue(any(event.kind == "dispute_opened" for event in minimal))

    def test_counterfactual_proof_changes_only_agent_policy(self):
        proof = counterfactual_proof(Scenario(1, 720, (540,)).events())
        self.assertTrue(proof["verified"])
        self.assertEqual(proof["differing_fields"], ["agent_policy"])
        self.assertEqual(proof["original"]["event_hash"], proof["patched"]["event_hash"])
        self.assertEqual(
            proof["original"]["world_asset_hash"],
            proof["patched"]["world_asset_hash"],
        )

    def test_observed_invariant_uses_trace_not_agent_name(self):
        fixed_agent_bug = [
            {"action": "pay", "payment": "paid", "crm": "overdue"},
            {"action": "agent/fixed", "sent": True, "payment": "paid", "crm": "overdue"},
            {"action": "webhook", "payment": "paid", "crm": "paid"},
        ]

        self.assertFalse(observed_invariant_holds(fixed_agent_bug))
        self.assertEqual(observed_violation(fixed_agent_bug)["mirror_value"], "OVERDUE")

    def test_browser_trace_is_bound_to_virtual_event_time(self):
        events = generate_future(0)
        trace = [
            {"action": "agent/original", "sent": True},
            {"action": "pay"},
            {"action": "agent/original", "sent": True, "payment": "paid", "crm": "overdue"},
            {"action": "agent/original", "sent": True, "payment": "paid", "crm": "overdue"},
            {"action": "webhook"},
        ]

        timestamped = timestamp_observed_trace(trace, events)

        self.assertEqual(timestamped[2]["at"], events[3].at.isoformat())
        self.assertEqual(observed_violation(timestamped)["at"], events[3].at.isoformat())

    def test_dashboard_surfaces_agent_belief_and_documentation_link(self):
        page = Path(__file__).parents[1] / "dashboard/app/page.tsx"
        inspector = Path(__file__).parents[1] / "dashboard/components/Inspector.tsx"
        tree = Path(__file__).parents[1] / "dashboard/components/FutureTree.tsx"
        self.assertIn("Agent belief", inspector.read_text())
        self.assertIn("Same future manifest", inspector.read_text())
        self.assertIn("parent_future_id", tree.read_text())
        self.assertIn('className="docs-link"', page.read_text())

    def test_local_run_persists_patch_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "latest.json"
            local_run(25, 0, output)
            data = json.loads(output.read_text())
            failures = [future for future in data["futures"] if future["status"] == "FAIL"]
            self.assertGreater(len(failures), 0)
            self.assertTrue(all(future["comparison"] == {"original": "FAIL", "patched": "PASS"} for future in failures))
            self.assertTrue(all(future["counterfactual_proof"]["verified"] for future in data["futures"]))
            self.assertTrue(all(future["input_hash"] == future["counterfactual_proof"]["original"]["event_hash"] for future in data["futures"]))
            self.assertEqual(data["summary"]["coverage"]["covered"], 6)
            self.assertEqual(data["summary"]["patched_replays"], len(failures))
            self.assertEqual(set(data["summary"]["failure_modes"]), {"stale_payment_contact", "active_dispute_contact"})
            self.assertEqual(data["summary"]["search"]["strategy"], "coverage_guided_mutation")
            self.assertGreater(data["summary"]["search"]["candidates_evaluated"], 25)
            self.assertGreaterEqual(data["summary"]["wall_clock_seconds"], 0)

    def test_structured_execution_record_matches_core_outcome(self):
        execution = execute_future("future-0", generate_future(0), seed=0)
        self.assertEqual(execution.status, "FAIL")
        self.assertEqual(execution.as_dict()["future_id"], "future-0")
        self.assertEqual(execution.as_dict()["events"][0]["kind"], "invoice_created")


class DashboardApiTests(unittest.TestCase):
    def serve_run(self, root):
        run_path = root / "runs" / "latest.json"
        run_path.parent.mkdir()
        events = generate_future(0)
        run_path.write_text(json.dumps({"futures": [{
            "future_id": "future-0",
            "events": [event.as_dict() for event in events],
        }]}))
        regression_dir = root / "regressions"
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(run_path, regression_dir))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, events, regression_dir

    def test_recording_route_serves_only_run_replay_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            replay_dir = root / "runs" / "replays"
            replay_dir.mkdir(parents=True)
            recording = replay_dir / "future-0-original.ndjson"
            recording.write_text('{"action":"pay"}\n')
            run_path = root / "runs" / "latest.json"
            events = generate_future(0)
            run_path.write_text(json.dumps({"futures": [{
                "future_id": "future-0",
                "recording_path": str(recording),
                "events": [event.as_dict() for event in events],
            }]}))
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(run_path, root / "regressions"))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/api/futures/future-0/recording/original") as response:
                    self.assertEqual(response.read(), b'{"action":"pay"}\n')
                    self.assertEqual(response.headers["Content-Type"], "application/x-ndjson; charset=utf-8")
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_minimize_returns_before_and_after_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            server, thread, events, _ = self.serve_run(Path(directory))
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/api/futures/future-0/minimize",
                    method="POST",
                )
                with urlopen(request) as response:
                    payload = json.load(response)

                self.assertEqual(payload["before_events"], 6)
                self.assertEqual(payload["events"], 3)
                self.assertEqual(payload["removed_events"], 3)
                self.assertEqual(len(payload["original_events"]), 6)
                self.assertEqual(len(payload["minimal_events"]), 3)
                self.assertEqual(payload["input_hash"], future_fingerprint(events))
                self.assertEqual(payload["minimal_violation"]["at"], payload["minimal_events"][1]["at"])
                self.assertEqual(payload["comparison"], {"original": "FAIL", "patched": "PASS"})
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_can_promote_future_to_regression(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server, thread, events, regression_dir = self.serve_run(root)
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/health") as response:
                    health = json.load(response)
                    self.assertEqual(health, {"status": "ok", "run_exists": True})
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/api/futures/future-0/regress",
                    method="POST",
                )
                with urlopen(request) as response:
                    payload = json.load(response)
                saved = Path(payload["regression"])
                self.assertEqual(payload["events"], 3)
                self.assertTrue(saved.exists())
                self.assertEqual(json.loads(saved.read_text())["result"], comparison(events))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
