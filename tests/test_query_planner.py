import unittest

from doc_ai_agent.query_planner import QueryPlanner


class FakeRouter:
    def __init__(self, payload):
        self.payload = payload

    def route(self, _question: str):
        return self.payload


class QueryPlannerTests(unittest.TestCase):
    def test_use_router_when_available(self):
        planner = QueryPlanner(FakeRouter({"intent": "data_query", "query_type": "count", "since": "2026-01-01 00:00:00"}))
        plan = planner.plan("2026年以来多少条")
        self.assertEqual(plan["intent"], "data_query")
        self.assertGreaterEqual(plan["confidence"], 0.9)
        self.assertEqual(plan["route"]["query_type"], "count")

    def test_heuristic_data_query(self):
        planner = QueryPlanner(None)
        plan = planner.plan("2025年12月24日徐州市发生了多少条预警？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertGreaterEqual(plan["confidence"], 0.6)
        self.assertEqual(plan["route"]["query_type"], "count")
        self.assertEqual(plan["route"]["city"], "徐州市")
        self.assertEqual(plan["route"]["since"], "2025-12-24 00:00:00")
        self.assertEqual(plan["route"]["until"], "2025-12-25 00:00:00")

    def test_heuristic_advice_query(self):
        planner = QueryPlanner(None)
        plan = planner.plan("针对涝渍预警，给我24小时处置清单")
        self.assertEqual(plan["intent"], "advice")
        self.assertGreaterEqual(plan["confidence"], 0.6)

    def test_ambiguous_question_needs_clarification(self):
        planner = QueryPlanner(None)
        plan = planner.plan("这个情况怎么办")
        self.assertTrue(plan["needs_clarification"])
        self.assertIn("统计", plan["clarification"])

    def test_extract_device_slot(self):
        planner = QueryPlanner(None)
        plan = planner.plan("设备SNS00204659最近一次预警时间是什么？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "latest_device")
        self.assertEqual(plan["route"]["device_code"], "SNS00204659")

    def test_low_signal_question_needs_clarification_without_router(self):
        planner = QueryPlanner(None)
        plan = planner.plan("123456")
        self.assertTrue(plan["needs_clarification"])
        self.assertEqual(plan["reason"], "low_signal")

    def test_low_signal_question_needs_clarification_with_router(self):
        planner = QueryPlanner(FakeRouter({"intent": "advice"}))
        plan = planner.plan("123456")
        self.assertTrue(plan["needs_clarification"])
        self.assertEqual(plan["reason"], "low_signal")


if __name__ == "__main__":
    unittest.main()
