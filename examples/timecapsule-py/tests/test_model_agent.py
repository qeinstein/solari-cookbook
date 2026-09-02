import os
import unittest
from unittest.mock import patch

from timecapsule.agents import OpenRouterAgent
from timecapsule.models import FREE_MODEL_IDS, model_options, openrouter_api_key, select_model
from timecapsule.openrouter import Completion, OpenRouterRateLimit, OpenRouterRouter


class ModelAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_decision_persists_structured_evidence_hashes(self):
        class FakeRouter:
            requested_model = "google/gemma-4-31b-it:free"
            active_model = requested_model
            temperature = 0.2

            async def complete(self, _messages):
                return Completion(
                    model=self.active_model,
                    response={"action": "suppress", "rationale": "Authoritative payment state is paid."},
                    request_id="req-test",
                )

        decision = await OpenRouterAgent(FakeRouter()).decide(
            {
                "at": "2026-09-04T18:00:00",
                "payment": "paid",
                "crm": "overdue",
                "dispute": "none",
                "crm_dispute": "none",
                "messages": "No messages sent.",
            },
            "future-hash",
            "environment-hash",
        )
        self.assertEqual(decision["action"], "suppress")
        self.assertEqual(decision["route"], "suppress")
        self.assertEqual(decision["model_response"]["action"], "suppress")
        self.assertEqual(decision["future_fingerprint"], "future-hash")
        self.assertEqual(decision["environment_fingerprint"], "environment-hash")
        self.assertEqual(len(decision["prompt_hash"]), 64)
        self.assertEqual(len(decision["observation_hash"]), 64)
        self.assertTrue(decision["stochastic"])

    async def test_rate_limited_model_falls_through_to_next_free_model(self):
        router = OpenRouterRouter("test-key", FREE_MODEL_IDS[0])
        fallback = Completion(
            model=FREE_MODEL_IDS[1],
            response={"action": "suppress", "rationale": "test"},
            request_id="req-fallback",
        )
        with patch(
            "timecapsule.openrouter._complete_sync",
            side_effect=[OpenRouterRateLimit("busy", 429), fallback],
        ):
            result = await router.complete([{"role": "user", "content": "test"}])
        self.assertEqual(result.model, FREE_MODEL_IDS[1])
        self.assertEqual(result.fallback_from, FREE_MODEL_IDS[0])
        self.assertEqual(router.active_model, FREE_MODEL_IDS[1])
        self.assertEqual(router.fallbacks, [{"from": FREE_MODEL_IDS[0], "to": FREE_MODEL_IDS[1]}])


class ModelCatalogTests(unittest.TestCase):
    def test_catalog_is_three_free_then_two_paid(self):
        options = model_options()
        self.assertEqual(len(options), 5)
        self.assertEqual([option.free for option in options], [True, True, True, False, False])
        self.assertEqual([option.model_id for option in options[:3]], list(FREE_MODEL_IDS))
        self.assertEqual(len({option.model_id for option in options}), len(options))

    def test_untested_models_require_explicit_escape_hatch(self):
        with self.assertRaisesRegex(SystemExit, "allow-untested-model"):
            select_model("example/untested-model")
        self.assertEqual(
            select_model("example/untested-model", allow_untested=True).model_id,
            "example/untested-model",
        )

    def test_terminal_picker_can_select_paid_model(self):
        with patch("timecapsule.models.sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value="5"
        ):
            self.assertEqual(select_model().model_id, "anthropic/claude-haiku-4.5")

    def test_missing_key_fails_cleanly_without_a_terminal(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "timecapsule.models.sys.stdin.isatty", return_value=False
        ):
            with self.assertRaisesRegex(SystemExit, "OPENROUTER_API_KEY not detected"):
                openrouter_api_key()


if __name__ == "__main__":
    unittest.main()
