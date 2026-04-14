import unittest

from doc_ai_agent.semantic_parse import SemanticParseResult


class SemanticParseResultTests(unittest.TestCase):
    def test_from_minimal_payload_sets_defaults(self):
        result = SemanticParseResult.from_dict(
            {
                "normalized_query": "浙江天气",
                "intent": "advice",
                "is_out_of_scope": True,
            }
        )

        self.assertEqual(result.normalized_query, "浙江天气")
        self.assertEqual(result.intent, "advice")
        self.assertTrue(result.is_out_of_scope)
        self.assertEqual(result.trace, [])


if __name__ == "__main__":
    unittest.main()
