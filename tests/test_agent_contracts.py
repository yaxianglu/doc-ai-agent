import unittest

from doc_ai_agent.agent_contracts import (
    AnalysisResponseEnvelope,
    AnalysisSynthesisPayload,
    FinalResponseEvidence,
    ForecastExecutionContext,
    PlanPayload,
    RequestUnderstandingPayload,
)
from doc_ai_agent.query_dsl import QueryDSL
from doc_ai_agent.response_builder import ResponseBuilder


class AgentContractsTests(unittest.TestCase):
    def test_query_dsl_round_trips_contract_shape(self):
        payload = QueryDSL.from_dict(
            {
                "domain": "pest",
                "intent": ["data_query", "forecast"],
                "task_type": "ranking",
                "region": {"name": "常州市", "level": "county"},
                "historical_window": {"kind": "history", "window_type": "months", "window_value": 3},
                "future_window": {"kind": "future", "window_type": "weeks", "window_value": 2, "horizon_days": 14},
                "capabilities": ["data_query", "forecast"],
            }
        )

        self.assertEqual(payload.to_dict()["region"]["level"], "county")
        self.assertEqual(payload.to_dict()["capabilities"], ["data_query", "forecast"])

    def test_request_understanding_payload_round_trips_core_fields(self):
        payload = RequestUnderstandingPayload.from_dict(
            {
                "original_question": "为什么徐州虫情高",
                "resolved_question": "为什么徐州虫情高",
                "normalized_question": "徐州市 虫情 为什么",
                "historical_query_text": "过去5个月徐州市虫情整体情况",
                "task_type": "region_overview",
                "domain": "pest",
                "window": {"window_type": "months", "window_value": 5},
                "future_window": None,
                "region_name": "徐州市",
                "region_level": "city",
                "needs_historical": True,
                "needs_forecast": False,
                "needs_explanation": True,
                "needs_advice": False,
                "used_context": False,
                "reuse_region_from_context": False,
                "execution_plan": ["understand_request", "historical_query", "knowledge_retrieval", "answer_synthesis"],
            }
        )

        self.assertEqual(payload.domain, "pest")
        self.assertEqual(payload.region_name, "徐州市")
        self.assertTrue(payload.needs_explanation)
        self.assertEqual(payload.to_dict()["task_type"], "region_overview")
        self.assertFalse(payload.to_dict()["reuse_region_from_context"])

    def test_plan_payload_round_trips_route_and_reason(self):
        payload = PlanPayload.from_dict(
            {
                "intent": "data_query",
                "confidence": 0.88,
                "route": {"query_type": "pest_overview", "city": "徐州市"},
                "query_plan": {"execution": {"route": {"query_type": "pest_overview"}}},
                "task_graph": {"execution_plan": ["historical_query", "answer_synthesis"]},
                "needs_clarification": False,
                "clarification": None,
                "reason": "heuristic_overview",
                "context_trace": ["heuristic matched pest overview"],
                "domain": "pest",
            }
        )

        self.assertEqual(payload.intent, "data_query")
        self.assertEqual(payload.reason, "heuristic_overview")
        self.assertEqual(payload.route["query_type"], "pest_overview")
        self.assertEqual(payload.to_dict()["task_graph"]["execution_plan"][0], "historical_query")
        self.assertEqual(payload.to_dict()["domain"], "pest")

    def test_final_response_evidence_merges_runtime_defaults(self):
        evidence = FinalResponseEvidence(
            base_evidence={"analysis_context": {"domain": "pest"}},
            historical_query={"query_type": "pest_overview"},
            task_graph={"execution_plan": ["historical_query", "answer_synthesis"]},
            memory_state={"memory_version": 2},
            request_understanding={"domain": "pest"},
            context_trace=["reused previous context"],
            response_meta={"confidence": 0.82, "source_types": ["db"], "fallback_reason": ""},
        ).to_dict()

        self.assertEqual(evidence["analysis_context"]["domain"], "pest")
        self.assertEqual(evidence["historical_query"]["query_type"], "pest_overview")
        self.assertEqual(evidence["memory_state"]["memory_version"], 2)
        self.assertEqual(evidence["response_meta"]["confidence"], 0.82)

    def test_forecast_execution_context_marks_enabled_when_route_exists(self):
        context = ForecastExecutionContext(
            route={"query_type": "pest_forecast", "forecast_mode": "region"},
            runtime_context={"domain": "pest"},
        )

        self.assertTrue(context.enabled)
        self.assertEqual(context.route["query_type"], "pest_forecast")

    def test_analysis_response_envelope_builds_stable_response_shape(self):
        payload = AnalysisSynthesisPayload(
            execution_plan=["understand_request", "historical_query", "answer_synthesis"],
            request_understanding={"domain": "pest"},
            analysis_context={"domain": "pest", "region_name": "徐州市"},
            historical_query={"query_type": "pest_overview", "region_name": "徐州市"},
            forecast={"horizon_days": 14},
            knowledge=[{"title": "虫情监测与绿色防控技术"}],
            knowledge_sources=[{"title": "虫情监测与绿色防控技术"}],
            generation_mode="analysis_synthesis",
            context_trace=["reused thread context domain=pest"],
        )

        response = AnalysisResponseEnvelope(
            answer="结论：徐州市虫情偏高。",
            historical_data=[{"region_name": "徐州市", "severity_score": 86}],
            forecast_data=[{"risk_level": "high"}],
            payload=payload,
        ).to_response()

        self.assertEqual(response["response"]["mode"], "analysis")
        self.assertEqual(response["response"]["evidence"]["generation_mode"], "analysis_synthesis")
        self.assertEqual(response["response"]["evidence"]["analysis_context"]["region_name"], "徐州市")
        self.assertEqual(response["response"]["data"]["historical"][0]["severity_score"], 86)

    def test_response_builder_outputs_structured_answer(self):
        structured = ResponseBuilder().build(
            question="过去5个月徐州市虫情怎么样？",
            answer="结论：徐州市虫情偏高。",
            response_mode="analysis",
            answer_form="trend",
            analysis_context={"domain": "pest", "region_name": "徐州市", "query_type": "pest_overview"},
            historical_data=[{"region_name": "徐州市", "severity_score": 86}],
            forecast_data=[{"risk_level": "high"}],
            evidence_items=["历史排行结果", "预测服务输出"],
        )

        self.assertEqual(structured["summary"], "结论：徐州市虫情偏高。")
        self.assertEqual(structured["answer_form"], "trend")
        self.assertEqual(structured["question"], "过去5个月徐州市虫情怎么样？")
        self.assertEqual(structured["analysis_context"]["domain"], "pest")
        self.assertEqual(structured["historical_data"][0]["severity_score"], 86)
        self.assertEqual(structured["evidence"], ["历史排行结果", "预测服务输出"])
        self.assertEqual(structured["sections"]["conclusion"], "徐州市虫情偏高。")


if __name__ == "__main__":
    unittest.main()
