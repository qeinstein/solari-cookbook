import json
from pathlib import Path
import unittest

from timecapsule.core import comparison, generate_future, invariant_holds, minimize, execute


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
        self.assertIn('button data-action="pay"', text)
        self.assertIn('button data-action="agent/original"', text)
        self.assertIn('button data-action="agent/fixed"', text)


if __name__ == "__main__":
    unittest.main()
