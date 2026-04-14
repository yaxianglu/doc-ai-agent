import unittest

from doc_ai_agent.intent_router import IntentRouter


class FakeLLMClient:
    def complete_json(self, model, system_prompt, user_prompt):
        return {
            "intent": "data_query",
            "query_type": "count",
            "field": "city",
            "top_n": None,
            "since": None,
        }


class IntentRouterTests(unittest.TestCase):
    def test_null_values_fallback(self):
        router = IntentRouter(FakeLLMClient(), "gpt-4.1-mini")
        route = router.route("2026年以来多少条")
        self.assertEqual(route["intent"], "data_query")
        self.assertEqual(route["top_n"], 5)
        self.assertEqual(route["since"], "1970-01-01 00:00:00")

    def test_agri_query_type_is_preserved(self):
        class AgriLLMClient:
            def complete_json(self, model, system_prompt, user_prompt):
                return {
                    "intent": "data_query",
                    "query_type": "pest_top",
                    "field": "city",
                    "top_n": 5,
                    "since": "1970-01-01 00:00:00",
                }

        router = IntentRouter(AgriLLMClient(), "gpt-4.1-mini")
        route = router.route("最近虫情最严重的城市有哪些？")
        self.assertEqual(route["intent"], "data_query")
        self.assertEqual(route["query_type"], "pest_top")

    def test_latest_device_query_type_is_preserved(self):
        class DeviceLLMClient:
            def complete_json(self, model, system_prompt, user_prompt):
                return {
                    "intent": "data_query",
                    "query_type": "latest_device",
                    "device_code": "SNS00204659",
                    "since": "1970-01-01 00:00:00",
                }

        router = IntentRouter(DeviceLLMClient(), "gpt-4.1-mini")
        route = router.route("设备SNS00204659最近一次预警时间是什么？")
        self.assertEqual(route["query_type"], "latest_device")
        self.assertEqual(route["device_code"], "SNS00204659")

    def test_region_disposal_query_type_is_preserved(self):
        class RegionDisposalLLMClient:
            def complete_json(self, model, system_prompt, user_prompt):
                return {
                    "intent": "data_query",
                    "query_type": "region_disposal",
                    "city": "徐州市",
                    "county": "铜山区",
                    "since": "1970-01-01 00:00:00",
                }

        router = IntentRouter(RegionDisposalLLMClient(), "gpt-4.1-mini")
        route = router.route("徐州市铜山区柳新镇最近一条处置建议是什么？")
        self.assertEqual(route["query_type"], "region_disposal")
        self.assertEqual(route["city"], "徐州市")

    def test_threshold_summary_query_type_is_preserved(self):
        class ThresholdLLMClient:
            def complete_json(self, model, system_prompt, user_prompt):
                return {
                    "intent": "data_query",
                    "query_type": "threshold_summary",
                    "threshold": 150,
                    "since": "2026-04-09 00:00:00",
                    "until": "2026-04-10 00:00:00",
                }

        router = IntentRouter(ThresholdLLMClient(), "gpt-4.1-mini")
        route = router.route("2026年4月9日告警值超过150的预警主要在哪些城市？")
        self.assertEqual(route["query_type"], "threshold_summary")
        self.assertEqual(route["threshold"], 150)
        self.assertEqual(route["until"], "2026-04-10 00:00:00")

    def test_router_emits_unified_semantic_fields(self):
        class UnifiedSchemaLLMClient:
            def complete_json(self, model, system_prompt, user_prompt):
                return {
                    "intent": "data_query",
                    "domain": "pest",
                    "task_type": "ranking",
                    "region_name": "苏州市",
                    "region_level": "city",
                    "historical_window": {"window_type": "months", "window_value": 3},
                    "future_window": {"window_type": "weeks", "window_value": 2, "horizon_days": 14},
                    "query_type": "pest_top",
                    "field": "city",
                    "top_n": 3,
                    "since": "2026-01-01 00:00:00",
                }

        router = IntentRouter(UnifiedSchemaLLMClient(), "gpt-4.1-mini")
        route = router.route("最近3个月苏州虫情最严重的城市有哪些？")

        self.assertEqual(route["intent"], "data_query")
        self.assertEqual(route.get("domain"), "pest")
        self.assertEqual(route.get("task_type"), "ranking")
        self.assertEqual(route.get("region_name"), "苏州市")
        self.assertEqual(route.get("region_level"), "city")
        self.assertEqual(route.get("historical_window"), {"window_type": "months", "window_value": 3})
        self.assertEqual(route.get("future_window"), {"window_type": "weeks", "window_value": 2, "horizon_days": 14})


if __name__ == "__main__":
    unittest.main()
