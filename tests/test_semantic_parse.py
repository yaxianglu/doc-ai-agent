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

    def test_from_payload_keeps_semantic_slots_stable(self):
        result = SemanticParseResult.from_dict(
            {
                "normalized_query": "过去5个月徐州市虫情趋势如何",
                "intent": "data_query",
                "domain": "pest",
                "task_type": "trend",
                "region_name": "徐州市",
                "region_level": "city",
                "historical_window": {"window_type": "months", "window_value": 5},
                "future_window": {"window_type": "weeks", "window_value": 2, "horizon_days": 14},
                "followup_type": "none",
                "needs_clarification": False,
                "trace": ["normalize", "slots"],
            }
        )

        self.assertEqual(result.domain, "pest")
        self.assertEqual(result.task_type, "trend")
        self.assertEqual(result.region_name, "徐州市")
        self.assertEqual(result.region_level, "city")
        self.assertEqual(result.historical_window, {"window_type": "months", "window_value": 5})
        self.assertEqual(result.future_window, {"window_type": "weeks", "window_value": 2, "horizon_days": 14})
        self.assertEqual(result.followup_type, "none")
        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.to_dict()["domain"], "pest")

    def test_from_empty_payload_sets_semantic_slot_defaults(self):
        result = SemanticParseResult.from_dict(None)

        self.assertEqual(result.domain, "")
        self.assertEqual(result.task_type, "unknown")
        self.assertEqual(result.region_name, "")
        self.assertEqual(result.region_level, "")
        self.assertEqual(result.historical_window, {"window_type": "all", "window_value": None})
        self.assertIsNone(result.future_window)
        self.assertEqual(result.followup_type, "none")
        self.assertFalse(result.needs_clarification)


if __name__ == "__main__":
    unittest.main()
