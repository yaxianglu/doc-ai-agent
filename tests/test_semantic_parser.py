import unittest

from doc_ai_agent.semantic_parser import SemanticParser


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
        self.assertEqual(result.followup_type, "contextual")
        self.assertFalse(result.needs_clarification)


if __name__ == "__main__":
    unittest.main()
