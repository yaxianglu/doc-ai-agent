import unittest

from doc_ai_agent.query_parser import QueryParser


class StubUnderstandingEngine:
    def analyze(self, question: str, history=None, context=None):
        return {
            "original_question": question,
            "resolved_question": "过去3个月常州市哪个县虫情最重，未来两周会不会继续升高？",
            "intent": "data_query",
            "task_type": "ranking",
            "domain": "pest",
            "window": {"window_type": "months", "window_value": 3},
            "future_window": {"window_type": "weeks", "window_value": 2, "horizon_days": 14},
            "region_name": "常州市",
            "region_level": "county",
            "followup_type": "none",
            "needs_clarification": False,
            "needs_forecast": True,
            "needs_explanation": False,
            "needs_advice": False,
            "confidence": 0.92,
        }


class QueryParserTests(unittest.TestCase):
    def test_parser_emits_query_dsl(self):
        parser = QueryParser(understanding_engine=StubUnderstandingEngine())

        result = parser.parse("过去3个月常州哪个县虫情最重，未来两周会不会继续升高？")

        self.assertEqual(result.domain, "pest")
        self.assertEqual(result.task_type, "ranking")
        self.assertEqual(result.region.level, "county")
        self.assertEqual(result.capabilities, ("data_query", "forecast"))


if __name__ == "__main__":
    unittest.main()
