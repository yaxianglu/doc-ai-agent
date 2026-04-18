import unittest

from doc_ai_agent.query_plan import build_query_plan, route_from_canonical_understanding


class QueryPlanTests(unittest.TestCase):
    def test_build_query_plan_uses_semantic_metric_override(self):
        plan = build_query_plan(
            plan_intent="data_query",
            route={
                "query_type": "alerts_trend",
                "since": "2026-01-01 00:00:00",
                "window": {"window_type": "year_since", "window_value": 2026},
            },
            domain="alerts",
            region_name="",
            historical_window={"window_type": "year_since", "window_value": 2026},
            future_window=None,
            answer_mode="trend",
            needs_clarification=False,
            is_greeting=False,
            needs_explanation=False,
            needs_forecast=False,
            needs_advice=False,
            semantic_metric={
                "metric": "alert_count",
                "aggregation": "trend",
                "time_scope_mode": "year_since",
                "geo_scope_mode": "all_regions",
            },
        )

        self.assertEqual(plan["slots"]["metric"], "alert_count")
        self.assertEqual(plan["slots"]["aggregation"], "trend")
        self.assertEqual(plan["slots"]["semantic_metric"]["geo_scope_mode"], "all_regions")

    def test_route_from_canonical_understanding_keeps_overview_county_parent_city(self):
        route = route_from_canonical_understanding(
            {
                "canonical_understanding": {
                    "intent": "data_query",
                    "domain": "pest",
                    "task_type": "region_overview",
                    "region_name": "常州市",
                    "region_level": "county",
                    "historical_window": {"window_type": "days", "window_value": 30},
                    "future_window": None,
                    "followup_type": "none",
                    "needs_clarification": False,
                }
            },
            {
                "query_type": "pest_overview",
                "since": "2026-03-01 00:00:00",
                "city": "常州市",
                "county": None,
                "region_level": "county",
                "window": {"window_type": "days", "window_value": 30},
            },
        )

        self.assertEqual(route["query_type"], "pest_overview")
        self.assertEqual(route["region_level"], "county")
        self.assertEqual(route["city"], "常州市")
        self.assertIsNone(route["county"])


if __name__ == "__main__":
    unittest.main()
