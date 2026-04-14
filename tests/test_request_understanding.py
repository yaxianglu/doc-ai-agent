import unittest

from doc_ai_agent.entity_extraction import EntityExtractionService
from doc_ai_agent.request_understanding import RequestUnderstanding


class FakeBackend:
    def extract(self, _question: str, context: dict | None = None) -> dict:
        return {
            "engine": "instructor",
            "domain": "pest",
            "task_type": "data_detail",
            "region_name": "苏州市",
            "historical_window": {"window_type": "months", "window_value": 5},
        }


class FutureWindowBackend:
    def extract(self, _question: str, context: dict | None = None) -> dict:
        return {
            "engine": "instructor",
            "domain": "pest",
            "task_type": "trend",
            "region_name": "南京市",
            "future_window": {"window_type": "weeks", "window_value": 2},
        }


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

    def test_reason_follow_up_reuses_domain_and_region_from_context(self):
        result = self.understanding.analyze(
            "原因呢",
            context={
                "domain": "pest",
                "region_name": "徐州市",
            },
        )

        self.assertTrue(result["used_context"])
        self.assertEqual(result["resolved_question"], "徐州市 虫情 原因呢")
        self.assertIn("expanded_short_follow_up_from_memory", result["context_resolution"])
        self.assertIn("reused_region_from_memory", result["context_resolution"])

    def test_pending_agri_clarification_rewrites_original_question_for_soil(self):
        result = self.understanding.analyze(
            "墒情",
            context={
                "pending_user_question": "过去5个月灾害最严重的地方是哪里",
                "pending_clarification": "agri_domain",
                "domain": "",
            },
        )

        self.assertTrue(result["used_context"])
        self.assertEqual(result["resolved_question"], "过去5个月墒情最严重的地方是哪里")
        self.assertEqual(result["normalized_question"], "过去5个月墒情最严重的地方是哪里")

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

    def test_domain_switch_follow_up_does_not_get_polluted_by_previous_domain(self):
        result = self.understanding.analyze(
            "换成墒情",
            context={
                "domain": "pest",
                "region_name": "徐州市",
            },
        )

        self.assertFalse(result["used_context"])
        self.assertEqual(result["resolved_question"], "换成墒情")
        self.assertEqual(result["domain"], "soil")
        self.assertEqual(result["region_name"], "")

    def test_window_follow_up_does_not_get_polluted_by_previous_domain(self):
        result = self.understanding.analyze(
            "那过去半年呢",
            context={
                "domain": "pest",
                "region_name": "徐州市",
            },
        )

        self.assertFalse(result["used_context"])
        self.assertEqual(result["resolved_question"], "那过去半年呢")
        self.assertEqual(result["window"]["window_type"], "months")
        self.assertEqual(result["window"]["window_value"], 6)

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

    def test_generic_county_ranking_preserves_county_scope(self):
        result = self.understanding.analyze("过去5个月虫情最严重的是哪些县")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["task_type"], "ranking")
        self.assertEqual(result["region_name"], "")
        self.assertEqual(result["region_level"], "county")
        self.assertEqual(result["historical_query_text"], "过去5个月虫情最严重的是哪些县")
        self.assertEqual(result["normalized_question"], "过去5个月虫情最严重的是哪些县")

    def test_highest_county_ranking_preserves_county_scope(self):
        result = self.understanding.analyze("近3个月虫情最高的县有哪些")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["task_type"], "ranking")
        self.assertEqual(result["region_name"], "")
        self.assertEqual(result["region_level"], "county")
        self.assertEqual(result["window"]["window_type"], "months")
        self.assertEqual(result["window"]["window_value"], 3)
        self.assertEqual(result["historical_query_text"], "近3个月虫情最高的县有哪些")
        self.assertEqual(result["normalized_question"], "近3个月虫情最高的县有哪些")

    def test_highest_county_follow_up_phrase_is_not_extracted_as_region(self):
        result = self.understanding.analyze("最高的县有哪些？")

        self.assertEqual(result["region_name"], "")
        self.assertEqual(result["region_level"], "county")
        self.assertEqual(result["task_type"], "ranking")

    def test_future_county_risk_question_does_not_extract_fake_region_name(self):
        result = self.understanding.analyze("未来10天哪些县风险最高？")

        self.assertEqual(result["region_name"], "")
        self.assertEqual(result["region_level"], "county")

    def test_this_year_since_is_preserved_as_window(self):
        result = self.understanding.analyze("今年以来徐州虫情变化怎么样？")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "徐州市")
        self.assertEqual(result["window"]["window_type"], "year_since")
        self.assertEqual(result["window"]["window_value"], 2026)

    def test_city_then_county_refinement_does_not_treat_suffix_as_region(self):
        result = self.understanding.analyze("江苏范围内，虫情最高的是哪些市？再细到县。")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "")
        self.assertEqual(result["task_type"], "ranking")
        self.assertEqual(result["region_level"], "county")

    def test_city_scoped_county_ranking_preserves_county_region_level(self):
        result = self.understanding.analyze("常州市下面虫情最严重的县有哪些？")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "常州市")
        self.assertEqual(result["task_type"], "ranking")
        self.assertEqual(result["region_level"], "county")

    def test_reasoning_follow_up_wording_keeps_overview_task_type(self):
        result = self.understanding.analyze("给我过去五个月徐州虫情整体情况，再说说原因")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "徐州市")
        self.assertEqual(result["task_type"], "region_overview")
        self.assertTrue(result["needs_explanation"])
        self.assertTrue(result["needs_historical"])

    def test_colloquial_why_variant_is_recognized_as_explanation(self):
        result = self.understanding.analyze("过去5个月徐州虫情为啥这么高")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "徐州市")
        self.assertEqual(result["task_type"], "region_overview")
        self.assertTrue(result["needs_explanation"])
        self.assertTrue(result["needs_historical"])

    def test_colloquial_advice_variant_is_recognized(self):
        result = self.understanding.analyze("过去5个月徐州虫情这么高，咋处理")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "徐州市")
        self.assertTrue(result["needs_advice"])
        self.assertTrue(result["needs_historical"])

    def test_colloquial_how_to_handle_variant_is_recognized(self):
        result = self.understanding.analyze("过去5个月徐州虫情这么高，该咋办")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "徐州市")
        self.assertTrue(result["needs_advice"])

    def test_continue_to_worsen_variant_is_recognized_as_forecast(self):
        result = self.understanding.analyze("过去5个月徐州虫情这么高，未来会不会继续变严重")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "徐州市")
        self.assertTrue(result["needs_forecast"])

    def test_scope_correction_sentence_does_not_become_fake_region_name(self):
        result = self.understanding.analyze(
            "我问的是县，不是市",
            context={
                "domain": "pest",
                "region_name": "徐州市",
                "route": {"region_level": "city"},
            },
        )

        self.assertEqual(result["region_name"], "")
        self.assertEqual(result["region_level"], "county")
        self.assertFalse(result["needs_historical"])

    def test_prominent_county_ranking_variant_preserves_county_scope(self):
        result = self.understanding.analyze("近3个月虫情最突出的县有哪些")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["task_type"], "ranking")
        self.assertEqual(result["region_level"], "county")
        self.assertEqual(result["window"]["window_type"], "months")
        self.assertEqual(result["window"]["window_value"], 3)

    def test_front_ranked_county_variant_preserves_county_scope(self):
        result = self.understanding.analyze("近3个月虫情排前面的县有哪些")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["task_type"], "ranking")
        self.assertEqual(result["region_level"], "county")

    def test_specific_county_question_marks_county_region_level(self):
        result = self.understanding.analyze("铜山区过去5个月虫情具体数据")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["task_type"], "data_detail")
        self.assertEqual(result["region_name"], "铜山区")
        self.assertEqual(result["region_level"], "county")

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

    def test_normalizes_common_jin_typo_for_relative_window(self):
        result = self.understanding.analyze("苏州进5个月的虫害数据")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "苏州市")
        self.assertEqual(result["task_type"], "data_detail")
        self.assertEqual(result["window"]["window_type"], "months")
        self.assertEqual(result["window"]["window_value"], 5)
        self.assertEqual(result["resolved_question"], "苏州市近5个月的虫害数据")
        self.assertEqual(result["normalized_question"], "苏州市近5个月的虫害数据")

    def test_entity_extractor_fallback_keeps_region_and_domain_from_noisy_prompt(self):
        extractor = EntityExtractionService()

        result = extractor.extract("麻烦你帮我看一下，过去五个月徐州这边的虫害整体情况怎么样")

        self.assertEqual(result["engine"], "fallback")
        self.assertEqual(result["region_name"], "徐州市")
        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["historical_window"]["window_type"], "months")
        self.assertEqual(result["historical_window"]["window_value"], 5)

    def test_colloquial_vocative_noise_does_not_override_region(self):
        result = self.understanding.analyze("苏州啊哥，过去5个月虫情具体数据")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "苏州市")
        self.assertEqual(result["task_type"], "data_detail")
        self.assertNotIn("啊哥", result["normalized_question"])

    def test_future_window_without_horizon_days_does_not_crash(self):
        understanding = RequestUnderstanding(backend=FutureWindowBackend())

        result = understanding.analyze("下个月南京虫情趋势怎么样")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "南京市")
        self.assertEqual(result["future_window"]["window_type"], "months")
        self.assertEqual(result["future_window"]["window_value"], 1)
        self.assertEqual(result["normalized_question"], "下个月南京市虫情趋势怎么样 未来1个月")

    def test_half_month_future_worsen_question_extracts_forecast_window(self):
        result = self.understanding.analyze("徐州未来半个月虫情会不会更严重")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "徐州市")
        self.assertTrue(result["needs_forecast"])
        self.assertEqual(result["future_window"]["window_type"], "days")
        self.assertEqual(result["future_window"]["window_value"], 15)
        self.assertEqual(result["future_window"]["horizon_days"], 15)

    def test_negated_advice_does_not_enable_advice_mode(self):
        result = self.understanding.analyze("不要建议，先给我数据，徐州过去3个月墒情")

        self.assertEqual(result["domain"], "soil")
        self.assertEqual(result["region_name"], "徐州市")
        self.assertEqual(result["task_type"], "data_detail")
        self.assertFalse(result["needs_advice"])
        self.assertTrue(result["needs_historical"])
        self.assertIn("徐州市过去3个月墒情", result["normalized_question"])
        self.assertNotIn("处置建议", result["normalized_question"])

    def test_compare_question_uses_compare_task_type(self):
        result = self.understanding.analyze("对比过去5个月徐州和苏州的虫情")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["task_type"], "compare")
        self.assertEqual(result["window"]["window_type"], "months")
        self.assertEqual(result["window"]["window_value"], 5)

    def test_cross_domain_compare_question_uses_cross_domain_compare_task_type(self):
        result = self.understanding.analyze("过去3个月苏州虫情和墒情哪个问题更突出")

        self.assertEqual(result["domain"], "mixed")
        self.assertEqual(result["task_type"], "cross_domain_compare")
        self.assertEqual(result["region_name"], "苏州市")

    def test_understanding_prefers_entity_extraction_before_rule_fallback(self):
        understanding = RequestUnderstanding()

        result = understanding.analyze("麻烦你帮我看一下，过去五个月徐州这边的虫害整体情况怎么样")

        self.assertEqual(result["region_name"], "徐州市")
        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["task_type"], "region_overview")
        self.assertEqual(result["historical_query_text"], "麻烦你帮我看一下 过去五个月徐州市这边的虫害整体情况怎么样")

    def test_understanding_accepts_backend_data_detail_task_type(self):
        understanding = RequestUnderstanding(backend=FakeBackend())

        result = understanding.analyze("苏州进5个月的虫害数据")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_name"], "苏州市")
        self.assertEqual(result["task_type"], "data_detail")
        self.assertEqual(result["historical_query_text"], "苏州市近5个月的虫害数据")

    def test_greeting_does_not_reuse_agri_context(self):
        result = self.understanding.analyze(
            "你好",
            context={
                "domain": "pest",
                "region_name": "常州市",
                "pending_user_question": "过去5个月虫情最严重的地方是哪里",
            },
        )

        self.assertFalse(result["used_context"])
        self.assertEqual(result["resolved_question"], "你好")
        self.assertEqual(result["normalized_question"], "你好")
        self.assertEqual(result["domain"], "")
        self.assertEqual(result["region_name"], "")
        self.assertFalse(result["needs_historical"])
        self.assertEqual(result["task_type"], "unknown")

    def test_global_up_down_question_is_recognized_as_trend(self):
        result = self.understanding.analyze("过去5个月虫情总体是上升还是下降？")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["task_type"], "trend")
        self.assertEqual(result["region_name"], "")
        self.assertTrue(result["needs_historical"])

    def test_relief_question_is_recognized_as_soil_trend(self):
        result = self.understanding.analyze("近两个月墒情有没有缓解？")

        self.assertEqual(result["domain"], "soil")
        self.assertEqual(result["task_type"], "trend")
        self.assertEqual(result["region_name"], "")
        self.assertTrue(result["needs_historical"])

    def test_county_advice_question_preserves_county_scope(self):
        result = self.understanding.analyze("对当前虫情最严重的县有什么建议？")

        self.assertEqual(result["domain"], "pest")
        self.assertEqual(result["region_level"], "county")
        self.assertTrue(result["needs_advice"])
        self.assertTrue(result["needs_historical"])


if __name__ == "__main__":
    unittest.main()
