import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.request import Request, urlopen

from dashboard.server import make_handler
from timecapsule.core import comparison, generate_future, invariant_holds, minimize, execute
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


class DashboardApiTests(unittest.TestCase):
    def test_can_promote_future_to_regression(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
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
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/api/futures/future-0/regress",
                    method="POST",
                )
                with urlopen(request) as response:
                    payload = json.load(response)
                saved = Path(payload["regression"])
                self.assertEqual(payload["events"], 4)
                self.assertTrue(saved.exists())
                self.assertEqual(json.loads(saved.read_text())["result"], comparison(events))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
