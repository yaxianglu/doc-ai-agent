import unittest

from doc_ai_agent.agent_execution_nodes import build_query_result_payload, build_clarification_response


class AgentExecutionNodesTests(unittest.TestCase):
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
