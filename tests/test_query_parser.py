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
            "answer_form": "boolean",
            "followup_type": "none",
            "needs_clarification": False,
            "needs_forecast": True,
            "needs_explanation": False,
            "needs_advice": False,
            "confidence": 0.92,
        }


class StubUnderstandingEngineWithParsedQuery:
    def analyze(self, question: str, history=None, context=None):
        del history, context
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
            "answer_form": "boolean",
            "followup_type": "none",
            "needs_clarification": False,
            "needs_forecast": True,
            "needs_explanation": False,
            "needs_advice": False,
            "confidence": 0.92,
            "parsed_query": {
                "domain": "soil",
                "intent": ["data_query"],
                "task_type": "trend",
                "answer_form": "trend",
                "region": {"name": "南京市", "level": "city"},
                "historical_window": {"kind": "history", "window_type": "weeks", "window_value": 6},
                "follow_up": True,
                "followup_type": "contextual",
                "needs_clarification": False,
                "capabilities": ["data_query"],
                "confidence": 0.41,
                "original_question": question,
                "resolved_question": "南京市近6周墒情走势如何",
            },
        }


class QueryParserTests(unittest.TestCase):
    def test_parser_emits_query_dsl(self):
        parser = QueryParser(understanding_engine=StubUnderstandingEngine())

        result = parser.parse("过去3个月常州哪个县虫情最重，未来两周会不会继续升高？")

        self.assertEqual(result.domain, "pest")
        self.assertEqual(result.task_type, "ranking")
        self.assertEqual(result.region.level, "county")
        self.assertEqual(result.answer_form, "boolean")
        self.assertEqual(result.capabilities, ("data_query", "forecast"))

    def test_parser_prefers_precomputed_parsed_query(self):
        parser = QueryParser(understanding_engine=StubUnderstandingEngineWithParsedQuery())

        result = parser.parse("这个问题只用于验证 parser 优先读取 parsed_query")

        self.assertEqual(result.domain, "soil")
        self.assertEqual(result.task_type, "trend")
        self.assertEqual(result.region.name, "南京市")
        self.assertEqual(result.region.level, "city")
        self.assertEqual(result.confidence, 0.41)
        self.assertEqual(result.followup_type, "contextual")


if __name__ == "__main__":
    unittest.main()
