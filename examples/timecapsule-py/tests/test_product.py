import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.request import Request, urlopen

from dashboard.server import make_handler
from main import future_coverage, local_run
from timecapsule.core import (
    comparison,
    execute,
    future_fingerprint,
    generate_future,
    invariant_holds,
    minimize,
    observed_invariant_holds,
    observed_violation,
    temporal_windows,
)
from timecapsule.execution import execute_future
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
        coverage = future_coverage([generate_future(seed) for seed in range(25)])
        self.assertEqual(coverage["covered"], 3)
        self.assertEqual(coverage["possible"], 3)
        self.assertEqual(
            {pattern["id"] for pattern in coverage["patterns"]},
            {"before_payment", "stale_window", "after_webhook"},
        )

    def test_observed_invariant_uses_trace_not_agent_name(self):
        fixed_agent_bug = [
            {"action": "pay", "payment": "paid", "crm": "overdue"},
            {"action": "agent/fixed", "sent": True, "payment": "paid", "crm": "overdue"},
            {"action": "webhook", "payment": "paid", "crm": "paid"},
        ]

        self.assertFalse(observed_invariant_holds(fixed_agent_bug))
        self.assertEqual(observed_violation(fixed_agent_bug)["crm_status"], "OVERDUE")

    def test_dashboard_surfaces_agent_belief_and_documentation_link(self):
        page = Path(__file__).parents[1] / "dashboard/app/page.tsx"
        text = page.read_text()
        self.assertIn("Agent belief", text)
        self.assertIn('className="docs-link"', text)

    def test_local_run_persists_patch_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "latest.json"
            local_run(1, 0, output)
            data = json.loads(output.read_text())
            self.assertEqual(data["futures"][0]["comparison"], {"original": "FAIL", "patched": "PASS"})
            self.assertEqual(data["futures"][0]["input_hash"], future_fingerprint(generate_future(0)))
            self.assertIsNotNone(data["futures"][0]["violation"])
            self.assertEqual(data["summary"]["coverage"]["covered"], 2)
            self.assertEqual(data["summary"]["patched_replays"], 1)

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
