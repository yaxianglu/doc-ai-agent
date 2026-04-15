import unittest

from doc_ai_agent.agent_execution_nodes import build_query_result_payload, build_clarification_response
from doc_ai_agent.capabilities.data_query import DataQueryCapability
from doc_ai_agent.capabilities.forecast import ForecastCapability
from doc_ai_agent.query_engine import QueryResult


class AgentExecutionNodesTests(unittest.TestCase):
    def test_data_query_capability_wraps_query_engine_result(self):
        class StubQueryEngine:
            def answer(self, question, plan=None):
                return QueryResult(
                    answer="ok",
                    data=[{"region_name": "徐州市"}],
                    evidence={"query_type": "pest_top", "confidence": 0.8},
                )

        _, capability = DataQueryCapability(StubQueryEngine()).execute("过去3个月虫情最高的是哪", {"query_type": "pest_top"})

        self.assertEqual(capability.type, "pest_top")
        self.assertEqual(capability.confidence, 0.8)

    def test_forecast_capability_wraps_forecast_service_result(self):
        class StubForecastService:
            def forecast_region(self, route, context=None):
                return {
                    "answer": "未来两周风险偏高",
                    "data": [{"region_name": "徐州市"}],
                    "forecast": {"confidence": 0.77, "risk_level": "高"},
                    "analysis_context": {"region_name": "徐州市"},
                }

        capability = ForecastCapability(StubForecastService()).execute(
            {"query_type": "pest_forecast", "forecast_mode": "region", "forecast_window": {"horizon_days": 14}},
            {"domain": "pest"},
        )

        self.assertEqual(capability.type, "forecast")
        self.assertEqual(capability.confidence, 0.77)
        self.assertEqual(capability.meta["analysis_context"]["region_name"], "徐州市")

    def test_build_query_result_payload_backfills_route_evidence(self):
        class Result:
            answer = "ok"
            data = [{"region_name": "徐州市"}]
            evidence = {"sql": "select 1"}

        payload = build_query_result_payload(
            Result(),
            {"query_type": "pest_overview", "city": "徐州市", "county": None, "window": {"window_type": "months", "window_value": 5}},
        )

        self.assertEqual(payload["mode"], "data_query")
        self.assertEqual(payload["evidence"]["query_type"], "pest_overview")
        self.assertEqual(payload["evidence"]["city"], "徐州市")

    def test_build_clarification_response_keeps_confidence(self):
        payload = build_clarification_response({"clarification": "请先说明是虫情还是墒情", "confidence": 0.62})

        self.assertEqual(payload["response"]["mode"], "advice")
        self.assertEqual(payload["response"]["evidence"]["generation_mode"], "clarification")
        self.assertEqual(payload["response"]["evidence"]["confidence"], 0.62)


if __name__ == "__main__":
    unittest.main()
