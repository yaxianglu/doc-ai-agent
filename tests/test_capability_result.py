import unittest

from doc_ai_agent.advice_engine import AdviceResult
from doc_ai_agent.capability_result import CapabilityResult
from doc_ai_agent.query_engine import QueryResult


class CapabilityResultTests(unittest.TestCase):
    def test_from_query_result_uses_evidence_confidence(self):
        result = QueryResult(
            answer="结论：常州虫情偏高。",
            data=[{"region_name": "常州市", "severity_score": 12}],
            evidence={"query_type": "pest_top", "confidence": 0.83},
        )

        capability = CapabilityResult.from_query_result(result)

        self.assertEqual(capability.type, "pest_top")
        self.assertEqual(capability.confidence, 0.83)
        self.assertEqual(capability.meta["answer"], "结论：常州虫情偏高。")

    def test_from_advice_result_adapts_sources_and_model(self):
        result = AdviceResult(
            answer="建议：先巡查重点县。",
            sources=[{"title": "规则库"}],
            generation_mode="rule",
            model="",
        )

        capability = CapabilityResult.from_advice_result(result)

        self.assertEqual(capability.type, "advice")
        self.assertEqual(capability.evidence["generation_mode"], "rule")
        self.assertEqual(capability.data["sources"][0]["title"], "规则库")


if __name__ == "__main__":
    unittest.main()
