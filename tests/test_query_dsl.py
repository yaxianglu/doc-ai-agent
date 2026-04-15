import unittest

from doc_ai_agent.query_dsl import QueryDSL, capabilities_from_semantics, query_dsl_from_understanding


class QueryDSLTests(unittest.TestCase):
    def test_query_dsl_from_understanding_maps_core_fields(self):
        payload = query_dsl_from_understanding(
            {
                "original_question": "过去3个月常州哪个县虫情最重，未来两周会不会继续升高？",
                "resolved_question": "过去3个月常州市哪个县虫情最重，未来两周会不会继续升高？",
                "intent": "data_query",
                "task_type": "ranking",
                "domain": "pest",
                "window": {"window_type": "months", "window_value": 3},
                "future_window": {"window_type": "weeks", "window_value": 2, "horizon_days": 14},
                "region_name": "常州市",
                "region_level": "county",
                "followup_type": "none",
                "needs_forecast": True,
                "needs_explanation": False,
                "needs_advice": False,
                "confidence": 0.92,
            }
        )

        self.assertEqual(payload.domain, "pest")
        self.assertEqual(payload.region.name, "常州市")
        self.assertEqual(payload.region.level, "county")
        self.assertEqual(payload.historical_window.window_value, 3)
        self.assertEqual(payload.future_window.horizon_days, 14)
        self.assertEqual(payload.capabilities, ("data_query", "forecast"))

    def test_query_dsl_round_trip(self):
        payload = QueryDSL.from_dict(
            {
                "domain": "soil",
                "intent": ["data_query", "reasoning"],
                "task_type": "joint_risk",
                "region": {"name": "江苏省", "level": "city"},
                "historical_window": {"kind": "history", "window_type": "weeks", "window_value": 8},
                "follow_up": True,
                "followup_type": "short_followup",
                "needs_clarification": False,
                "capabilities": ["data_query", "reasoning", "advice"],
                "confidence": 0.8,
            }
        )

        serialized = payload.to_dict()
        self.assertEqual(serialized["domain"], "soil")
        self.assertEqual(serialized["region"]["name"], "江苏省")
        self.assertEqual(serialized["capabilities"], ["data_query", "reasoning", "advice"])

    def test_capabilities_from_semantics_prefers_reasoning_for_explanation(self):
        capabilities = capabilities_from_semantics(
            intent="data_query",
            task_type="region_overview",
            needs_forecast=False,
            needs_explanation=True,
            needs_advice=True,
        )

        self.assertEqual(capabilities, ("data_query", "reasoning", "advice"))


if __name__ == "__main__":
    unittest.main()
