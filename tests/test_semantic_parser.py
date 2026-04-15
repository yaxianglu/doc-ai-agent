import unittest

from doc_ai_agent.semantic_parser import SemanticParser


class FakeSemanticBackend:
    def __init__(self, domain: str = "", fallback_reason: str = ""):
        self.domain = domain
        self.fallback_reason = fallback_reason

    def extract(self, _question: str, context: dict | None = None):
        del context
        payload = {}
        if self.domain:
            payload["domain"] = self.domain
        if self.fallback_reason:
            payload["fallback_reason"] = self.fallback_reason
        return payload


class SemanticParserTests(unittest.TestCase):
    def test_weather_question_is_marked_out_of_scope(self):
        parser = SemanticParser()

        result = parser.parse("浙江天气")

        self.assertTrue(result.is_out_of_scope)
        self.assertEqual(result.intent, "advice")
        self.assertIn("ood", result.trace)
        self.assertTrue(result.needs_clarification)

    def test_parse_populates_core_semantic_slots_for_data_question(self):
        parser = SemanticParser()

        result = parser.parse("过去5个月徐州市虫情趋势如何")

        self.assertEqual(result.domain, "pest")
        self.assertEqual(result.task_type, "trend")
        self.assertEqual(result.region_name, "徐州市")
        self.assertEqual(result.region_level, "city")
        self.assertEqual(result.historical_window, {"window_type": "months", "window_value": 5})
        self.assertIsNone(result.future_window)
        self.assertEqual(result.followup_type, "none")
        self.assertFalse(result.needs_clarification)

    def test_parse_marks_contextual_follow_up_slots(self):
        parser = SemanticParser()

        result = parser.parse(
            "未来两周呢",
            context={
                "domain": "pest",
                "region_name": "徐州市",
            },
        )

        self.assertEqual(result.domain, "pest")
        self.assertEqual(result.region_name, "徐州市")
        self.assertEqual(result.future_window, {"window_type": "weeks", "window_value": 2, "horizon_days": 14})
        self.assertEqual(result.followup_type, "forecast_follow_up")
        self.assertFalse(result.needs_clarification)

    def test_confidence_increases_when_rule_and_backend_agree(self):
        agree_parser = SemanticParser(backend=FakeSemanticBackend(domain="pest"))
        disagree_parser = SemanticParser(backend=FakeSemanticBackend(domain="soil"))

        agree_result = agree_parser.parse("过去5个月徐州市虫情趋势如何")
        disagree_result = disagree_parser.parse("过去5个月徐州市虫情趋势如何")

        self.assertGreater(agree_result.confidence, disagree_result.confidence)
        self.assertGreaterEqual(agree_result.confidence, 0.75)
        self.assertLess(disagree_result.confidence, 0.7)

    def test_ambiguous_follow_up_keeps_low_confidence(self):
        parser = SemanticParser()

        result = parser.parse(
            "那过去半年呢",
            context={
                "region_name": "徐州市",
            },
        )

        self.assertEqual(result.followup_type, "time_follow_up")
        self.assertTrue(result.needs_clarification)
        self.assertLess(result.confidence, 0.3)

    def test_clear_ood_has_high_confidence(self):
        parser = SemanticParser(backend=FakeSemanticBackend(fallback_reason="out_of_scope_weather"))

        result = parser.parse("浙江天气")

        self.assertTrue(result.is_out_of_scope)
        self.assertGreaterEqual(result.confidence, 0.95)

    def test_invalid_input_does_not_become_follow_up(self):
        parser = SemanticParser()
        result = parser.parse(
            "h d k j h sa d k l j",
            context={"domain": "soil", "region_name": "徐州市"},
        )

        self.assertTrue(result.needs_clarification)
        self.assertEqual(result.fallback_reason, "invalid_gibberish")
        self.assertEqual(result.followup_type, "none")


if __name__ == "__main__":
    unittest.main()
