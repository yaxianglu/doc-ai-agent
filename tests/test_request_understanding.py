import unittest

from doc_ai_agent.entity_extraction import EntityExtractionService
from doc_ai_agent.request_understanding import RequestUnderstanding


class RequestUnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.understanding = RequestUnderstanding()

    def test_filters_meta_talk_and_builds_execution_plan(self):
        result = self.understanding.analyze(
            "我其实不太确定怎么表达，但你先帮我看看过去5个月虫情最严重的地方是哪里，"
            "然后再判断未来两周会不会更糟，最后给我解释一下原因和处置建议"
        )

        self.assertEqual(result["normalized_question"], "过去5个月虫情最严重的地方是哪里 未来两周 原因 处置建议")
        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["window"]["window_type"], "months")
        self.assertEqual(result["window"]["window_value"], 5)
        self.assertTrue(result["needs_historical"])
        self.assertTrue(result["needs_forecast"])
        self.assertTrue(result["needs_explanation"])
        self.assertTrue(result["needs_advice"])
        self.assertEqual(
            result["execution_plan"],
            ["understand_request", "historical_query", "forecast", "knowledge_retrieval", "answer_synthesis"],
        )
        self.assertIn("我其实不太确定怎么表达", result["ignored_phrases"])

    def test_preserves_core_intent_for_soil_question(self):
        result = self.understanding.analyze("如果方便的话，帮我看看近3个星期墒情异常最严重的地方")

        self.assertEqual(result["domain"], "soil")
        self.assertEqual(result["window"]["window_type"], "weeks")
        self.assertEqual(result["window"]["window_value"], 3)
        self.assertTrue(result["needs_historical"])
        self.assertFalse(result["needs_forecast"])
        self.assertFalse(result["needs_advice"])

    def test_resolves_short_domain_follow_up_with_context(self):
        result = self.understanding.analyze(
            "虫情",
            context={
                "pending_user_question": "过去5个月灾害最严重的地方是哪里",
                "pending_clarification": "agri_domain",
                "domain": "",
            },
        )

        self.assertTrue(result["used_context"])
        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["resolved_question"], "过去5个月虫情最严重的地方是哪里")
        self.assertEqual(result["normalized_question"], "过去5个月虫情最严重的地方是哪里")
        self.assertTrue(result["needs_historical"])

    def test_full_question_does_not_inherit_previous_domain_context(self):
        result = self.understanding.analyze(
            "过去5个月灾害最严重的地方是哪里",
            context={
                "domain": "soil",
                "region_name": "徐州市",
                "last_question": "过去5个月墒情最严重的地方是哪里，未来两周会怎样，为什么，给建议",
            },
        )

        self.assertFalse(result["used_context"])
        self.assertEqual(result["domain"], "")
        self.assertEqual(result["region_name"], "")

    def test_preserves_region_trend_question_in_historical_query_text(self):
        result = self.understanding.analyze("徐州市最近60天虫情趋势如何？")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "徐州市")
        self.assertEqual(result["window"]["window_type"], "days")
        self.assertEqual(result["window"]["window_value"], 60)
        self.assertEqual(result["historical_query_text"], "徐州市最近60天虫情趋势如何")
        self.assertEqual(result["normalized_question"], "徐州市最近60天虫情趋势如何")

    def test_preserves_joint_risk_question_with_mixed_domains(self):
        result = self.understanding.analyze("过去90天，哪些地区同时出现高虫情和低墒情？")

        self.assertEqual(result["window"]["window_type"], "days")
        self.assertEqual(result["window"]["window_value"], 90)
        self.assertEqual(result["historical_query_text"], "过去90天 哪些地区同时出现高虫情和低墒情")
        self.assertEqual(result["normalized_question"], "过去90天 哪些地区同时出现高虫情和低墒情")

    def test_region_name_unknown_area_does_not_trigger_historical_ranking(self):
        result = self.understanding.analyze(
            "为什么",
            context={
                "domain": "soil",
                "region_name": "未知地区",
            },
        )

        self.assertFalse(result["needs_historical"])
        self.assertEqual(result["normalized_question"], "未知地区 墒情 为什么 原因")

    def test_short_city_follow_up_replaces_previous_region(self):
        result = self.understanding.analyze(
            "南京呢",
            context={
                "domain": "pest",
                "region_name": "徐州市",
            },
        )

        self.assertTrue(result["used_context"])
        self.assertEqual(result["region_name"], "南京市")
        self.assertEqual(result["resolved_question"], "虫情 南京市呢")
        self.assertEqual(result["normalized_question"], "虫情 南京市呢")

    def test_generic_future_advice_follow_up_keeps_domain_without_sticky_region(self):
        result = self.understanding.analyze(
            "未来虫害怎么养",
            context={
                "domain": "pest",
                "region_name": "常州市",
            },
        )

        self.assertTrue(result["used_context"])
        self.assertEqual(result["resolved_question"], "虫情 未来虫害怎么养")
        self.assertEqual(result["region_name"], "")
        self.assertTrue(result["needs_advice"])
        self.assertFalse(result["needs_forecast"])

    def test_preserves_trend_semantics_for_zoushi_wording(self):
        result = self.understanding.analyze("南京近三周虫害走势怎么样？")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "南京市")
        self.assertEqual(result["window"]["window_type"], "weeks")
        self.assertEqual(result["window"]["window_value"], 3)
        self.assertEqual(result["historical_query_text"], "南京市近三周虫害走势怎么样")
        self.assertEqual(result["normalized_question"], "南京市近三周虫害走势怎么样")

    def test_preserves_joint_risk_semantics_for_shortage_wording(self):
        result = self.understanding.analyze("近两个月哪些地方虫情高而且缺水更明显？")

        self.assertEqual(result["domain"], "mixed")
        self.assertEqual(result["window"]["window_type"], "months")
        self.assertEqual(result["window"]["window_value"], 2)
        self.assertEqual(result["historical_query_text"], "近两个月哪些地方虫情高而且缺水更明显")
        self.assertEqual(result["normalized_question"], "近两个月哪些地方虫情高而且缺水更明显")

    def test_preserves_region_overview_semantics_for_pest_summary_question(self):
        result = self.understanding.analyze("给我过去五个月徐州的虫害情况")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "徐州市")
        self.assertEqual(result["task_type"], "region_overview")
        self.assertEqual(result["window"]["window_type"], "months")
        self.assertEqual(result["window"]["window_value"], 5)
        self.assertEqual(result["historical_query_text"], "给我过去五个月徐州市的虫害情况")
        self.assertEqual(result["normalized_question"], "给我过去五个月徐州市的虫害情况")
        self.assertNotIn("最严重的地方", result["normalized_question"])

    def test_entity_extractor_fallback_keeps_region_and_domain_from_noisy_prompt(self):
        extractor = EntityExtractionService()

        result = extractor.extract("麻烦你帮我看一下，过去五个月徐州这边的虫害整体情况怎么样")

        self.assertEqual(result["engine"], "fallback")
        self.assertEqual(result["region_name"], "徐州市")
        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["historical_window"]["window_type"], "months")
        self.assertEqual(result["historical_window"]["window_value"], 5)

    def test_understanding_prefers_entity_extraction_before_rule_fallback(self):
        understanding = RequestUnderstanding()

        result = understanding.analyze("麻烦你帮我看一下，过去五个月徐州这边的虫害整体情况怎么样")

        self.assertEqual(result["region_name"], "徐州市")
        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["task_type"], "region_overview")
        self.assertEqual(result["historical_query_text"], "麻烦你帮我看一下 过去五个月徐州市这边的虫害整体情况怎么样")


if __name__ == "__main__":
    unittest.main()
