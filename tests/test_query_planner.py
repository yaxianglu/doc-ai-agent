import unittest

from doc_ai_agent.query_planner import QueryPlanner


class FakeRouter:
    def __init__(self, payload):
        self.payload = payload

    def route(self, _question: str):
        return self.payload


class ExplodingRouter:
    def route(self, _question: str):
        raise RuntimeError("router temporarily unavailable")


class FakePlaybookRouter:
    def __init__(self, payload):
        self.payload = payload

    def route(self, _question: str, context: dict | None = None):
        return self.payload


class QueryPlannerTests(unittest.TestCase):
    def test_query_plan_is_emitted_for_ranking_request(self):
        planner = QueryPlanner(None)

        plan = planner.plan("近3个星期虫情最严重的地方是哪里？")

        self.assertEqual(
            plan["query_plan"],
            {
                "version": "v1",
                "goal": "agri_analysis",
                "intent": "analysis",
                "slots": {
                    "domain": "pest",
                    "metric": "pest_severity",
                    "time_range": {"mode": "relative", "value": "3_weeks"},
                    "region_scope": {"level": "city", "value": "all"},
                    "aggregation": "top_k",
                    "k": 1,
                    "need_explanation": False,
                    "need_forecast": False,
                    "need_advice": False,
                },
                "constraints": {
                    "must_use_structured_data": True,
                    "allow_clarification": True,
                },
            },
        )

    def test_query_plan_is_emitted_for_detail_request(self):
        planner = QueryPlanner(None)

        plan = planner.plan("苏州市近5个月的虫害数据")

        self.assertEqual(plan["query_plan"]["goal"], "agri_analysis")
        self.assertEqual(plan["query_plan"]["intent"], "analysis")
        self.assertEqual(plan["query_plan"]["slots"]["domain"], "pest")
        self.assertEqual(plan["query_plan"]["slots"]["metric"], "pest_severity")
        self.assertEqual(plan["query_plan"]["slots"]["time_range"], {"mode": "relative", "value": "5_months"})
        self.assertEqual(plan["query_plan"]["slots"]["region_scope"], {"level": "city", "value": "苏州市"})
        self.assertEqual(plan["query_plan"]["slots"]["aggregation"], "detail")

    def test_query_plan_marks_mixed_analysis_needs(self):
        planner = QueryPlanner(None)

        plan = planner.plan("过去5个月虫情最严重的地方是哪里，未来两周会怎样，为什么，给建议")

        self.assertEqual(plan["query_plan"]["goal"], "agri_analysis")
        self.assertEqual(plan["query_plan"]["intent"], "analysis")
        self.assertEqual(plan["query_plan"]["slots"]["domain"], "pest")
        self.assertEqual(plan["query_plan"]["slots"]["time_range"], {"mode": "relative", "value": "5_months"})
        self.assertTrue(plan["query_plan"]["slots"]["need_explanation"])
        self.assertTrue(plan["query_plan"]["slots"]["need_forecast"])
        self.assertTrue(plan["query_plan"]["slots"]["need_advice"])

    def test_greeting_produces_non_execution_query_plan(self):
        planner = QueryPlanner(None)

        plan = planner.plan("你好")

        self.assertEqual(
            plan["query_plan"],
            {
                "version": "v1",
                "goal": "conversation",
                "intent": "greeting",
                "slots": {
                    "domain": "",
                    "metric": "",
                    "time_range": {"mode": "none", "value": None},
                    "region_scope": {"level": "none", "value": ""},
                    "aggregation": "none",
                    "k": None,
                    "need_explanation": False,
                    "need_forecast": False,
                    "need_advice": False,
                },
                "constraints": {
                    "must_use_structured_data": False,
                    "allow_clarification": False,
                },
            },
        )

    def test_use_router_when_available(self):
        planner = QueryPlanner(FakeRouter({"intent": "data_query", "query_type": "count", "since": "2026-01-01 00:00:00"}))
        plan = planner.plan("2026年以来多少条")
        self.assertEqual(plan["intent"], "data_query")
        self.assertGreaterEqual(plan["confidence"], 0.9)
        self.assertEqual(plan["route"]["query_type"], "count")

    def test_upgrade_legacy_router_top_for_agri_question(self):
        planner = QueryPlanner(FakeRouter({"intent": "data_query", "query_type": "top", "field": "city", "top_n": 5, "since": "1970-01-01 00:00:00"}))
        plan = planner.plan("最近虫情最严重的城市有哪些？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "pest_top")

    def test_heuristic_data_query(self):
        planner = QueryPlanner(None)
        plan = planner.plan("2025年12月24日徐州市发生了多少条预警？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertGreaterEqual(plan["confidence"], 0.6)
        self.assertEqual(plan["route"]["query_type"], "count")
        self.assertEqual(plan["route"]["city"], "徐州市")
        self.assertEqual(plan["route"]["since"], "2025-12-24 00:00:00")
        self.assertEqual(plan["route"]["until"], "2025-12-25 00:00:00")

    def test_heuristic_advice_query(self):
        planner = QueryPlanner(None)
        plan = planner.plan("针对涝渍预警，给我24小时处置清单")
        self.assertEqual(plan["intent"], "advice")
        self.assertGreaterEqual(plan["confidence"], 0.6)

    def test_support_weeks_window_for_pest_top(self):
        planner = QueryPlanner(None)
        plan = planner.plan("近3个星期虫情最严重的地方是哪里？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "pest_top")
        self.assertEqual(plan["route"]["window"]["window_type"], "weeks")
        self.assertEqual(plan["route"]["window"]["window_value"], 3)

    def test_region_overview_question_uses_overview_query_type(self):
        planner = QueryPlanner(None)
        plan = planner.plan("给我过去五个月徐州市的虫害情况")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "pest_overview")
        self.assertEqual(plan["route"]["city"], "徐州市")
        self.assertEqual(plan["route"]["window"]["window_type"], "months")
        self.assertEqual(plan["route"]["window"]["window_value"], 5)
        self.assertEqual(plan["domain"], "pest")
        self.assertEqual(plan["region_name"], "徐州市")
        self.assertEqual(plan["historical_window"]["window_type"], "months")
        self.assertEqual(plan["answer_mode"], "overview")

    def test_router_failure_falls_back_to_heuristics(self):
        planner = QueryPlanner(ExplodingRouter())
        plan = planner.plan("近3个星期虫情最严重的地方是哪里？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "pest_top")
        self.assertEqual(plan["route"]["window"]["window_type"], "weeks")
        self.assertEqual(plan["route"]["window"]["window_value"], 3)

    def test_router_defaults_do_not_override_heuristic_weeks_window(self):
        planner = QueryPlanner(
            FakeRouter(
                {
                    "intent": "data_query",
                    "query_type": "top",
                    "field": "region_level",
                    "top_n": 1,
                    "min_days": 21,
                    "since": "1970-01-01 00:00:00",
                }
            )
        )
        plan = planner.plan("近3个星期虫情最严重的地方是哪里？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "pest_top")
        self.assertEqual(plan["route"]["window"]["window_type"], "weeks")
        self.assertEqual(plan["route"]["window"]["window_value"], 3)
        self.assertNotEqual(plan["route"]["since"], "1970-01-01 00:00:00")

    def test_router_arbitrary_since_does_not_override_explicit_relative_window(self):
        planner = QueryPlanner(
            FakeRouter(
                {
                    "intent": "data_query",
                    "query_type": "soil_top",
                    "field": "city",
                    "top_n": 1,
                    "since": "2023-01-01 00:00:00",
                    "until": "2023-06-01 00:00:00",
                }
            )
        )
        plan = planner.plan("过去5个月墒情最严重的地方是哪里？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "soil_top")
        self.assertEqual(plan["route"]["window"]["window_type"], "months")
        self.assertEqual(plan["route"]["window"]["window_value"], 5)
        self.assertNotEqual(plan["route"]["since"], "2023-01-01 00:00:00")
        self.assertIsNone(plan["route"]["until"])

    def test_generic_severity_question_needs_domain_clarification_without_router(self):
        planner = QueryPlanner(None)
        plan = planner.plan("近3个星期，受灾最严重的地方是哪里")
        self.assertTrue(plan["needs_clarification"])
        self.assertIn("虫情", plan["clarification"])
        self.assertIn("墒情", plan["clarification"])

    def test_generic_severity_question_needs_domain_clarification_with_router(self):
        planner = QueryPlanner(
            FakeRouter(
                {
                    "intent": "data_query",
                    "query_type": "top",
                    "field": "region_level",
                    "top_n": 1,
                    "min_days": 21,
                    "since": "1970-01-01 00:00:00",
                }
            )
        )
        plan = planner.plan("近3个星期，受灾最严重的地方是哪里")
        self.assertTrue(plan["needs_clarification"])
        self.assertIn("虫情", plan["clarification"])
        self.assertIn("墒情", plan["clarification"])

    def test_agri_dataset_question_asks_domain_clarification_not_generic_intent(self):
        planner = QueryPlanner(None)
        plan = planner.plan("苏州市近5个月的灾害数据")

        self.assertTrue(plan["needs_clarification"])
        self.assertEqual(plan["reason"], "agri_domain_ambiguous")
        self.assertIn("虫情", plan["clarification"])
        self.assertIn("墒情", plan["clarification"])
        self.assertNotIn("数据统计", plan["clarification"])
        self.assertEqual(plan["route"]["city"], "苏州市")
        self.assertEqual(plan["route"]["window"]["window_type"], "months")
        self.assertEqual(plan["route"]["window"]["window_value"], 5)

    def test_short_follow_up_inherits_previous_question_context(self):
        planner = QueryPlanner(None)
        plan = planner.plan(
            "虫情",
            history=[
                {"role": "user", "content": "过去5个月灾害最严重的地方是哪里"},
                {"role": "assistant", "content": "你想看虫情还是墒情？"},
            ],
        )
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "pest_top")
        self.assertEqual(plan["route"]["window"]["window_type"], "months")

    def test_compare_question_emits_compare_answer_mode(self):
        planner = QueryPlanner(None)

        plan = planner.plan(
            "对比过去5个月徐州和苏州的虫情",
            understanding={
                "domain": "pest",
                "task_type": "compare",
                "window": {"window_type": "months", "window_value": 5},
                "region_name": "徐州市",
                "needs_explanation": False,
                "needs_advice": False,
                "needs_forecast": False,
            },
        )

        self.assertEqual(plan["answer_mode"], "compare")
        self.assertEqual(plan["query_plan"]["slots"]["aggregation"], "compare")

    def test_cross_domain_compare_question_emits_compare_task_graph(self):
        planner = QueryPlanner(None)

        plan = planner.plan(
            "过去3个月苏州虫情和墒情哪个问题更突出",
            understanding={
                "domain": "mixed",
                "task_type": "cross_domain_compare",
                "window": {"window_type": "months", "window_value": 3},
                "region_name": "苏州市",
                "needs_explanation": False,
                "needs_advice": False,
                "needs_forecast": False,
            },
        )

        self.assertEqual(plan["answer_mode"], "compare")
        self.assertEqual(plan["query_plan"]["slots"]["aggregation"], "compare")

    def test_ambiguous_question_needs_clarification(self):
        planner = QueryPlanner(None)
        plan = planner.plan("这个情况怎么办")
        self.assertTrue(plan["needs_clarification"])
        self.assertIn("统计", plan["clarification"])

    def test_extract_device_slot(self):
        planner = QueryPlanner(None)
        plan = planner.plan("设备SNS00204659最近一次预警时间是什么？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "latest_device")
        self.assertEqual(plan["route"]["device_code"], "SNS00204659")

    def test_router_count_does_not_override_heuristic_latest_device(self):
        planner = QueryPlanner(
            FakeRouter(
                {
                    "intent": "data_query",
                    "query_type": "count",
                    "field": "city",
                    "since": "1970-01-01 00:00:00",
                }
            )
        )
        plan = planner.plan("设备SNS00204659最近一次预警时间是什么？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "latest_device")
        self.assertEqual(plan["route"]["device_code"], "SNS00204659")

    def test_router_count_does_not_override_heuristic_region_disposal(self):
        planner = QueryPlanner(
            FakeRouter(
                {
                    "intent": "data_query",
                    "query_type": "count",
                    "field": "city",
                    "since": "1970-01-01 00:00:00",
                }
            )
        )
        plan = planner.plan("徐州市柳新镇最近一条处置建议是什么？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "region_disposal")
        self.assertEqual(plan["route"]["city"], "徐州市")

    def test_router_count_does_not_override_heuristic_threshold_summary(self):
        planner = QueryPlanner(
            FakeRouter(
                {
                    "intent": "data_query",
                    "query_type": "count",
                    "field": "city",
                    "since": "1970-01-01 00:00:00",
                }
            )
        )
        plan = planner.plan("2026年4月9日告警值超过150的预警主要在哪些城市？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "threshold_summary")
        self.assertEqual(plan["route"]["since"], "2026-04-09 00:00:00")
        self.assertEqual(plan["route"]["until"], "2026-04-10 00:00:00")

    def test_parses_top_n_from_front_number_for_agri_ranking(self):
        planner = QueryPlanner(None)

        plan = planner.plan("最近30天虫情最严重的前10个地区")

        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "pest_top")
        self.assertEqual(plan["route"]["top_n"], 10)

    def test_time_window_prefix_is_not_treated_as_top_n(self):
        planner = QueryPlanner(None)

        plan = planner.plan("近3个星期虫情最严重的地方是哪里？")

        self.assertEqual(plan["route"]["query_type"], "pest_top")
        self.assertEqual(plan["route"]["top_n"], 1)

    def test_plural_ranking_defaults_to_top_five(self):
        planner = QueryPlanner(None)

        plan = planner.plan("过去5个月虫情最严重的是哪些地区？")

        self.assertEqual(plan["route"]["query_type"], "pest_top")
        self.assertEqual(plan["route"]["top_n"], 5)

    def test_low_signal_question_needs_clarification_without_router(self):
        planner = QueryPlanner(None)
        plan = planner.plan("123456")
        self.assertTrue(plan["needs_clarification"])
        self.assertEqual(plan["reason"], "low_signal")

    def test_low_signal_question_needs_clarification_with_router(self):
        planner = QueryPlanner(FakeRouter({"intent": "advice"}))
        plan = planner.plan("123456")
        self.assertTrue(plan["needs_clarification"])
        self.assertEqual(plan["reason"], "low_signal")

    def test_greeting_routes_to_intro_instead_of_clarification(self):
        planner = QueryPlanner(None)
        plan = planner.plan("你好")

        self.assertEqual(plan["intent"], "advice")
        self.assertFalse(plan["needs_clarification"])
        self.assertEqual(plan["reason"], "greeting_intro")

    def test_context_explanation_follow_up_bypasses_router_guess(self):
        planner = QueryPlanner(
            FakeRouter(
                {
                    "intent": "data_query",
                    "query_type": "pest_top",
                    "field": "city",
                    "since": "1970-01-01 00:00:00",
                }
            )
        )
        plan = planner.plan(
            "为什么",
            context={
                "domain": "soil",
                "region_name": "徐州市",
                "query_type": "soil_top",
                "route": {
                    "query_type": "soil_top",
                    "since": "2025-11-11 00:00:00",
                    "until": None,
                    "city": "徐州市",
                    "county": None,
                    "region_level": "city",
                    "window": {"window_type": "months", "window_value": 5},
                },
            },
        )
        self.assertEqual(plan["intent"], "advice")
        self.assertFalse(plan["needs_clarification"])
        self.assertEqual(plan["reason"], "context_explanation_follow_up")
        self.assertEqual(plan["route"]["query_type"], "soil_top")

    def test_identity_question_returns_direct_advice(self):
        planner = QueryPlanner(None)
        plan = planner.plan("你是谁？")
        self.assertEqual(plan["intent"], "advice")
        self.assertFalse(plan["needs_clarification"])
        self.assertEqual(plan["reason"], "identity_self_intro")

    def test_short_city_follow_up_preserves_forecast_intent(self):
        planner = QueryPlanner(None)
        plan = planner.plan(
            "南京呢",
            context={
                "domain": "pest",
                "region_name": "徐州市",
                "query_type": "pest_forecast",
                "forecast": {"horizon_days": 14},
                "route": {
                    "query_type": "pest_forecast",
                    "since": "2026-03-20 00:00:00",
                    "until": None,
                    "city": "徐州市",
                    "county": None,
                    "region_level": "city",
                    "window": {"window_type": "weeks", "window_value": 3},
                    "forecast_window": {"window_type": "weeks", "window_value": 2, "horizon_days": 14},
                },
            },
        )
        self.assertEqual(plan["intent"], "data_query")
        self.assertFalse(plan["needs_clarification"])
        self.assertEqual(plan["reason"], "context_region_forecast_follow_up")
        self.assertEqual(plan["route"]["query_type"], "pest_forecast")
        self.assertEqual(plan["route"]["city"], "南京市")

    def test_short_city_follow_up_preserves_overview_intent(self):
        planner = QueryPlanner(None)
        plan = planner.plan(
            "苏州呢",
            context={
                "domain": "pest",
                "region_name": "徐州市",
                "query_type": "pest_overview",
                "route": {
                    "query_type": "pest_overview",
                    "since": "2025-11-11 00:00:00",
                    "until": None,
                    "city": "徐州市",
                    "county": None,
                    "region_level": "city",
                    "window": {"window_type": "months", "window_value": 5},
                },
            },
        )
        self.assertEqual(plan["intent"], "data_query")
        self.assertFalse(plan["needs_clarification"])
        self.assertEqual(plan["route"]["query_type"], "pest_overview")
        self.assertEqual(plan["route"]["city"], "苏州市")
        self.assertEqual(plan["route"]["window"]["window_type"], "months")
        self.assertEqual(plan["route"]["window"]["window_value"], 5)

    def test_domain_switch_follow_up_preserves_scope(self):
        planner = QueryPlanner(None)
        plan = planner.plan(
            "换成墒情",
            context={
                "domain": "pest",
                "region_name": "徐州市",
                "query_type": "pest_overview",
                "route": {
                    "query_type": "pest_overview",
                    "since": "2025-11-11 00:00:00",
                    "until": None,
                    "city": "徐州市",
                    "county": None,
                    "region_level": "city",
                    "window": {"window_type": "months", "window_value": 5},
                },
            },
        )
        self.assertEqual(plan["intent"], "data_query")
        self.assertFalse(plan["needs_clarification"])
        self.assertEqual(plan["route"]["query_type"], "soil_overview")
        self.assertEqual(plan["route"]["city"], "徐州市")
        self.assertEqual(plan["route"]["window"]["window_type"], "months")
        self.assertEqual(plan["route"]["window"]["window_value"], 5)

    def test_historical_window_follow_up_preserves_scope(self):
        planner = QueryPlanner(None)
        plan = planner.plan(
            "那过去半年呢",
            context={
                "domain": "soil",
                "region_name": "徐州市",
                "query_type": "soil_overview",
                "route": {
                    "query_type": "soil_overview",
                    "since": "2025-11-11 00:00:00",
                    "until": None,
                    "city": "徐州市",
                    "county": None,
                    "region_level": "city",
                    "window": {"window_type": "months", "window_value": 5},
                },
            },
        )
        self.assertEqual(plan["intent"], "data_query")
        self.assertFalse(plan["needs_clarification"])
        self.assertEqual(plan["route"]["query_type"], "soil_overview")
        self.assertEqual(plan["route"]["city"], "徐州市")
        self.assertEqual(plan["route"]["window"]["window_type"], "months")
        self.assertEqual(plan["route"]["window"]["window_value"], 6)

    def test_region_data_question_uses_detail_query_type(self):
        planner = QueryPlanner(None)
        plan = planner.plan("给我过去五个月苏州市的虫害数据")

        self.assertEqual(plan["intent"], "data_query")
        self.assertFalse(plan["needs_clarification"])
        self.assertEqual(plan["route"]["query_type"], "pest_detail")
        self.assertEqual(plan["route"]["city"], "苏州市")
        self.assertEqual(plan["answer_mode"], "detail")

    def test_router_does_not_downgrade_explicit_detail_query_type(self):
        planner = QueryPlanner(
            FakeRouter(
                {
                    "intent": "data_query",
                    "query_type": "pest_trend",
                    "since": "1970-01-01 00:00:00",
                }
            )
        )
        plan = planner.plan("给我过去五个月苏州市的虫害数据")

        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "pest_detail")
        self.assertEqual(plan["route"]["city"], "苏州市")
        self.assertEqual(plan["answer_mode"], "detail")

    def test_generic_county_scope_question_uses_county_region_level(self):
        planner = QueryPlanner(None)

        plan = planner.plan("过去一年墒情最严重的是哪个县")

        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "soil_top")
        self.assertEqual(plan["route"]["county"], None)
        self.assertEqual(plan["route"]["region_level"], "county")
        self.assertEqual(plan["query_plan"]["slots"]["region_scope"], {"level": "county", "value": "all"})
        self.assertEqual(plan["answer_mode"], "ranking")

    def test_plural_county_scope_question_uses_county_region_level(self):
        planner = QueryPlanner(None)

        plan = planner.plan("过去5个月虫情最严重的是哪些县")

        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "pest_top")
        self.assertEqual(plan["route"]["county"], None)
        self.assertEqual(plan["route"]["region_level"], "county")
        self.assertEqual(plan["query_plan"]["slots"]["region_scope"], {"level": "county", "value": "all"})
        self.assertEqual(plan["route"]["window"]["window_type"], "months")
        self.assertEqual(plan["route"]["window"]["window_value"], 5)

    def test_router_cannot_downgrade_generic_county_scope_to_city(self):
        planner = QueryPlanner(
            FakeRouter(
                {
                    "intent": "data_query",
                    "query_type": "pest_top",
                    "region_level": "city",
                    "since": "1970-01-01 00:00:00",
                }
            )
        )

        plan = planner.plan("过去5个月虫情最严重的是哪些县")

        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "pest_top")
        self.assertEqual(plan["route"]["region_level"], "county")
        self.assertEqual(plan["query_plan"]["slots"]["region_scope"], {"level": "county", "value": "all"})

    def test_detail_follow_up_preserves_previous_scope(self):
        planner = QueryPlanner(None)
        plan = planner.plan(
            "我说的是虫情的具体数据",
            context={
                "domain": "pest",
                "region_name": "苏州市",
                "query_type": "pest_overview",
                "route": {
                    "query_type": "pest_overview",
                    "since": "2025-11-11 00:00:00",
                    "until": None,
                    "city": "苏州市",
                    "county": None,
                    "region_level": "city",
                    "window": {"window_type": "months", "window_value": 5},
                },
            },
        )
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["reason"], "context_detail_follow_up")
        self.assertEqual(plan["route"]["query_type"], "pest_detail")
        self.assertEqual(plan["route"]["city"], "苏州市")
        self.assertEqual(plan["answer_mode"], "detail")

    def test_mingxi_wording_uses_detail_query_type(self):
        planner = QueryPlanner(None)

        plan = planner.plan("给我最近两周南京虫情明细")

        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "pest_detail")
        self.assertEqual(plan["route"]["city"], "南京市")
        self.assertEqual(plan["route"]["window"]["window_type"], "weeks")
        self.assertEqual(plan["route"]["window"]["window_value"], 2)
        self.assertEqual(plan["answer_mode"], "detail")

    def test_future_worsen_follow_up_reuses_scope_as_forecast(self):
        planner = QueryPlanner(None)

        plan = planner.plan(
            "未来会更糟吗",
            context={
                "domain": "pest",
                "region_name": "常州市",
                "query_type": "pest_top",
                "forecast": {},
                "route": {
                    "query_type": "pest_top",
                    "since": "2026-03-21 00:00:00",
                    "until": None,
                    "city": None,
                    "county": None,
                    "region_level": "city",
                    "window": {"window_type": "weeks", "window_value": 3},
                },
            },
        )

        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "pest_forecast")
        self.assertEqual(plan["route"]["city"], "常州市")
        self.assertEqual(plan["route"]["forecast_window"]["horizon_days"], 14)
        self.assertEqual(plan["answer_mode"], "forecast")

    def test_playbook_router_upgrades_semantic_joint_risk_question(self):
        planner = QueryPlanner(
            None,
            playbook_router=FakePlaybookRouter(
                {
                    "intent": "data_query",
                    "query_type": "joint_risk",
                    "reason": "semantic joint risk",
                    "retrieval_engine": "llamaindex",
                }
            ),
        )
        plan = planner.plan("近两个月哪些地方虫情高而且缺水更明显？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "joint_risk")
        self.assertEqual(plan["reason"], "playbook_data_query")
        self.assertIn("semantic joint risk", plan["context_trace"])

    def test_playbook_router_upgrades_semantic_pest_trend_question(self):
        planner = QueryPlanner(
            None,
            playbook_router=FakePlaybookRouter(
                {
                    "intent": "data_query",
                    "query_type": "pest_trend",
                    "reason": "semantic pest trend",
                    "retrieval_engine": "llamaindex",
                }
            ),
        )
        plan = planner.plan("南京近三周虫害走势怎么样？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "pest_trend")
        self.assertEqual(plan["route"]["city"], "南京市")

    def test_playbook_router_upgrades_semantic_soil_top_question(self):
        planner = QueryPlanner(
            None,
            playbook_router=FakePlaybookRouter(
                {
                    "intent": "data_query",
                    "query_type": "soil_top",
                    "reason": "semantic soil top",
                    "retrieval_engine": "llamaindex",
                }
            ),
        )
        plan = planner.plan("过去5个月缺水最厉害的地方是哪里？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "soil_top")
        self.assertEqual(plan["route"]["window"]["window_type"], "months")
        self.assertEqual(plan["route"]["window"]["window_value"], 5)

    def test_deterministic_rule_beats_playbook_router_guess(self):
        planner = QueryPlanner(
            None,
            playbook_router=FakePlaybookRouter(
                {
                    "intent": "data_query",
                    "query_type": "pest_top",
                    "reason": "wrong semantic guess",
                    "retrieval_engine": "llamaindex",
                }
            ),
        )
        plan = planner.plan("设备SNS00204659最近一次预警时间是什么？")
        self.assertEqual(plan["intent"], "data_query")
        self.assertEqual(plan["route"]["query_type"], "latest_device")
        self.assertEqual(plan["reason"], "heuristic_data_query")

    def test_generic_top_question_does_not_extract_fake_county(self):
        planner = QueryPlanner(None)

        plan = planner.plan("给我前3个预警最多的地区，从2026年开始")

        self.assertIsNone(plan["route"]["county"])


if __name__ == "__main__":
    unittest.main()
