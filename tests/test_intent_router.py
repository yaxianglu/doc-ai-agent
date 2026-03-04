import unittest

from doc_ai_agent.intent_router import IntentRouter


class FakeLLMClient:
    def complete_json(self, model, system_prompt, user_prompt):
        return {
            "intent": "data_query",
            "query_type": "count",
            "field": "city",
            "top_n": None,
            "since": None,
        }


class IntentRouterTests(unittest.TestCase):
    def test_null_values_fallback(self):
        router = IntentRouter(FakeLLMClient(), "gpt-4.1-mini")
        route = router.route("2026年以来多少条")
        self.assertEqual(route["intent"], "data_query")
        self.assertEqual(route["top_n"], 5)
        self.assertEqual(route["since"], "1970-01-01 00:00:00")


if __name__ == "__main__":
    unittest.main()
