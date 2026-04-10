import os
import tempfile
import unittest

from doc_ai_agent.agent import DocAIAgent
from doc_ai_agent.advice_engine import AdviceResult
from doc_ai_agent.repository import AlertRepository


class FakeLLMClient:
    def complete_json(self, model, system_prompt, user_prompt):
        if "意图路由" in system_prompt:
            if "前3" in user_prompt:
                return {
                    "intent": "data_query",
                    "query_type": "top",
                    "field": "city",
                    "top_n": 3,
                    "since": "2026-01-01 00:00:00",
                }
            return {"intent": "advice"}
        raise AssertionError("unexpected prompt")

    def complete_text(self, model, system_prompt, user_prompt):
        return "模型建议：优先排水、补施叶面肥、加强病害巡查。"


class FakeSourceProvider:
    def search(self, question, limit=3):
        return [
            {
                "title": "农业农村部防灾指导",
                "url": "https://example.gov/agri-typhoon",
                "published_at": "2026-03-01",
                "snippet": "台风过后小麦应及时排水、扶苗、追肥。",
            }
        ]


class RichFakeSourceProvider:
    def search(self, question, limit=3, context=None):
        domain = (context or {}).get("domain")
        items = [
            {
                "title": "虫情监测与绿色防控技术",
                "url": "https://example.gov/pest",
                "published_at": "2026-02-14",
                "snippet": "针对迁飞性害虫应加强监测预警，按阈值采取分区防控措施。",
                "domain": "pest",
                "tags": ["虫情", "防控", "阈值"],
                "retrieval_engine": "qdrant",
                "retrieval_backend": "qdrant",
                "retrieval_strategy": "semantic-vector",
            },
            {
                "title": "墒情调度与灌排要点",
                "url": "https://example.gov/soil",
                "published_at": "2026-02-15",
                "snippet": "低墒优先补灌，高墒优先排水，并复核未来天气。",
                "domain": "soil",
                "tags": ["墒情", "排水", "补灌"],
                "retrieval_engine": "qdrant",
                "retrieval_backend": "qdrant",
                "retrieval_strategy": "semantic-vector",
            },
        ]
        if domain:
            items = [item for item in items if item["domain"] == domain] or items
        return items[:limit]


class FakeStructuredRepo:
    def top_pest_regions(self, since, until, region_level="city", top_n=5):
        return [
            {
                "region_name": "徐州市",
                "severity_score": 92,
                "record_count": 18,
                "active_days": 9,
            },
            {
                "region_name": "淮安市",
                "severity_score": 75,
                "record_count": 13,
                "active_days": 7,
            },
        ][:top_n]

    def sample_pest_records(self, since, until, limit=3):
        return [
            {
                "city_name": "徐州市",
                "county_name": "铜山区",
                "normalized_pest_count": 24,
                "monitor_time": "2026-04-01 08:00:00",
            }
        ][:limit]

    def pest_trend(self, since, until, region_name, region_level="city"):
        return [
            {"date": "2026-03-28", "severity_score": 58},
            {"date": "2026-03-29", "severity_score": 64},
            {"date": "2026-03-30", "severity_score": 70},
            {"date": "2026-03-31", "severity_score": 78},
            {"date": "2026-04-01", "severity_score": 86},
        ]

    def top_soil_regions(self, since, until, region_level="city", top_n=5, anomaly_direction=None):
        return [
            {
                "region_name": "宿迁市",
                "anomaly_score": 88,
                "abnormal_count": 16,
                "low_count": 11,
                "high_count": 0,
            },
            {
                "region_name": "盐城市",
                "anomaly_score": 73,
                "abnormal_count": 12,
                "low_count": 8,
                "high_count": 1,
            },
        ][:top_n]

    def sample_soil_records(self, since, until, limit=3):
        return [
            {
                "city_name": "宿迁市",
                "county_name": "泗阳县",
                "soil_anomaly_score": 18,
                "sample_time": "2026-04-01 08:00:00",
            }
        ][:limit]

    def soil_trend(self, since, until, region_name, region_level="city"):
        return [
            {"date": "2026-03-28", "avg_anomaly_score": 45},
            {"date": "2026-03-29", "avg_anomaly_score": 56},
            {"date": "2026-03-30", "avg_anomaly_score": 70},
            {"date": "2026-03-31", "avg_anomaly_score": 81},
        ]

    def joint_risk_regions(self, since, until, region_level="city", top_n=5):
        return [
            {"region_name": "徐州市", "joint_score": 156, "pest_score": 92, "low_soil_score": 64},
            {"region_name": "淮安市", "joint_score": 128, "pest_score": 75, "low_soil_score": 53},
        ][:top_n]


class EmptyStructuredRepo:
    def top_pest_regions(self, since, until, region_level="city", top_n=5):
        return []

    def sample_pest_records(self, since, until, limit=3):
        return []

    def available_pest_time_range(self):
        return {
            "min_time": "2026-01-05 00:00:00",
            "max_time": "2026-04-08 00:00:00",
        }

    def pest_trend(self, since, until, region_name, region_level="city"):
        return []

    def top_soil_regions(self, since, until, region_level="city", top_n=5, anomaly_direction=None):
        return []

    def sample_soil_records(self, since, until, limit=3):
        return []

    def available_soil_time_range(self, anomaly_direction=None):
        return {
            "min_time": "2026-01-07 00:00:00",
            "max_time": "2026-04-09 00:00:00",
        }

    def soil_trend(self, since, until, region_name, region_level="city"):
        return []

    def joint_risk_regions(self, since, until, region_level="city", top_n=5):
        return []


class SpyAdviceEngine:
    def __init__(self):
        self.calls = []

    def answer(self, question: str, context=None) -> AdviceResult:
        self.calls.append({"question": question, "context": context})
        domain = (context or {}).get("domain") or "unknown"
        region = (context or {}).get("region_name") or "未指定地区"
        return AdviceResult(
            answer=f"针对{region}{domain}风险，建议先监测再处置。",
            sources=[{"title": "规则建议", "url": "", "published_at": "", "snippet": ""}],
            generation_mode="rule",
            model="",
        )


class AggressiveRouterLLM(FakeLLMClient):
    def complete_json(self, model, system_prompt, user_prompt):
        if "意图路由" in system_prompt and "为什么" in user_prompt:
            return {
                "intent": "data_query",
                "query_type": "pest_top",
                "field": "city",
                "top_n": 5,
                "since": "1970-01-01 00:00:00",
            }
        return super().complete_json(model, system_prompt, user_prompt)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.td.name, "alerts.db")
        repo = AlertRepository(self.db)
        repo.init_schema()
        repo.insert_alerts(
            [
                {
                    "alert_content": "a",
                    "alert_type": "墒情预警",
                    "alert_subtype": "土壤",
                    "alert_time": "2026-01-02 00:00:00",
                    "alert_level": "重旱",
                    "region_code": "1",
                    "region_name": "x",
                    "alert_value": "10",
                    "device_code": "d1",
                    "device_name": "n1",
                    "longitude": "1",
                    "latitude": "2",
                    "city": "淮安市",
                    "county": "A",
                    "sms_content": "",
                    "disposal_suggestion": "建议1",
                    "source_file": "f.xlsx",
                    "source_sheet": "sheet1",
                    "source_row": 2,
                },
                {
                    "alert_content": "b",
                    "alert_type": "墒情预警",
                    "alert_subtype": "土壤",
                    "alert_time": "2026-01-03 00:00:00",
                    "alert_level": "重旱",
                    "region_code": "2",
                    "region_name": "x",
                    "alert_value": "11",
                    "device_code": "d2",
                    "device_name": "n2",
                    "longitude": "1",
                    "latitude": "2",
                    "city": "淮安市",
                    "county": "B",
                    "sms_content": "",
                    "disposal_suggestion": "建议2",
                    "source_file": "f.xlsx",
                    "source_sheet": "sheet1",
                    "source_row": 3,
                },
                {
                    "alert_content": "c",
                    "alert_type": "墒情预警",
                    "alert_subtype": "土壤",
                    "alert_time": "2026-01-03 08:00:00",
                    "alert_level": "涝渍",
                    "region_code": "3",
                    "region_name": "x",
                    "alert_value": "30",
                    "device_code": "d1",
                    "device_name": "n1",
                    "longitude": "1",
                    "latitude": "2",
                    "city": "徐州市",
                    "county": "C",
                    "sms_content": "",
                    "disposal_suggestion": "建议3",
                    "source_file": "f.xlsx",
                    "source_sheet": "sheet1",
                    "source_row": 4,
                },
            ]
        )
        self.agent = DocAIAgent(repo)

    def tearDown(self):
        self.td.cleanup()

    def test_count_query(self):
        result = self.agent.answer("2026年以来指挥调度平台发生了多少预警信息？")
        self.assertEqual(result["mode"], "data_query")
        self.assertIn("2", result["answer"])
        self.assertIn("sql", result["evidence"])
        self.assertIn("samples", result["evidence"])
        self.assertEqual(result["processing"]["answer_generation"], "模板回答")
        self.assertEqual(result["processing"]["ai_involvement"], "低")

    def test_top_query(self):
        result = self.agent.answer("2026年以来top5的是哪几个市？")
        self.assertEqual(result["mode"], "data_query")
        self.assertTrue(len(result["data"]) >= 1)
        self.assertEqual(result["data"][0]["name"], "淮安市")

    def test_top_query_returns_empty_message_with_available_range_when_no_rows(self):
        result = self.agent.answer("2030年以来top5的是哪几个市？")
        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(result["data"], [])
        self.assertIn("暂无", result["answer"])
        self.assertIn("当前可用告警数据范围为 2026-01-02 至 2026-01-03", result["answer"])
        self.assertEqual(
            result["evidence"]["available_data_ranges"],
            [
                {
                    "source": "alerts",
                    "label": "告警数据",
                    "min_time": "2026-01-02 00:00:00",
                    "max_time": "2026-01-03 08:00:00",
                }
            ],
        )
        self.assertEqual(result["evidence"]["no_data_reasons"][0]["code"], "outside_available_window")
        self.assertEqual(result["evidence"]["recovery_suggestions"][0]["action"], "use_available_window")
        self.assertIn("2026-01-02 至 2026-01-03", result["evidence"]["recovery_suggestions"][0]["message"])
        self.assertIn("2026年1月以来", result["evidence"]["recovery_suggestions"][0]["suggested_question"])

    def test_count_query_returns_available_range_when_no_rows(self):
        result = self.agent.answer("2030年以来指挥调度平台发生了多少预警信息？")
        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(result["data"][0]["count"], 0)
        self.assertIn("预警信息共 0 条", result["answer"])
        self.assertIn("当前可用告警数据范围为 2026-01-02 至 2026-01-03", result["answer"])
        self.assertEqual(
            result["evidence"]["available_data_ranges"],
            [
                {
                    "source": "alerts",
                    "label": "告警数据",
                    "min_time": "2026-01-02 00:00:00",
                    "max_time": "2026-01-03 08:00:00",
                }
            ],
        )
        self.assertEqual(result["evidence"]["no_data_reasons"][0]["code"], "outside_available_window")

    def test_avg_alert_value_group_by_level_query(self):
        result = self.agent.answer("按告警等级分组，平均告警值分别是多少？")
        self.assertEqual(result["mode"], "data_query")
        self.assertIn("重旱", result["answer"])
        self.assertIn("涝渍", result["answer"])
        self.assertTrue(any(row["level"] == "重旱" for row in result["data"]))
        self.assertIn("AVG", result["evidence"]["sql"])

    def test_consecutive_two_day_devices_query(self):
        result = self.agent.answer("相同设备在连续两天都触发预警的有哪些？")
        self.assertEqual(result["mode"], "data_query")
        self.assertIn("d1", result["answer"])
        self.assertTrue(any(row["device_code"] == "d1" for row in result["data"]))

    def test_advice_query(self):
        result = self.agent.answer("台风过后，对于小麦种植需要注意哪些？")
        self.assertEqual(result["mode"], "advice")
        self.assertIn("排水", result["answer"])
        self.assertEqual(result["evidence"]["generation_mode"], "rule")

    def test_llm_driven_top_query(self):
        agent = DocAIAgent(
            self.agent.repo,
            llm_client=FakeLLMClient(),
            router_model="gpt-4.1-mini",
            advice_model="gpt-4.1",
        )
        result = agent.answer("请按城市给我前3个预警最多的地区，从2026年开始")
        self.assertEqual(result["mode"], "data_query")
        self.assertTrue(len(result["data"]) >= 1)
        self.assertIn("1.", result["answer"])
        self.assertIn("淮安市", result["answer"])
        self.assertIn("LIMIT 3", result["evidence"]["sql"])

    def test_llm_driven_advice(self):
        agent = DocAIAgent(
            self.agent.repo,
            llm_client=FakeLLMClient(),
            router_model="gpt-4.1-mini",
            advice_model="gpt-4.1",
        )
        result = agent.answer("给我处置建议")
        self.assertEqual(result["mode"], "advice")
        self.assertIn("模型建议", result["answer"])
        self.assertEqual(result["evidence"]["generation_mode"], "llm")
        self.assertEqual(result["evidence"]["model"], "gpt-4.1")
        self.assertEqual(result["processing"]["intent_recognition"], "GPT-4.1-mini")
        self.assertEqual(result["processing"]["answer_generation"], "GPT-4.1")
        self.assertEqual(result["processing"]["ai_involvement"], "高")

    def test_advice_with_sources(self):
        agent = DocAIAgent(
            self.agent.repo,
            llm_client=FakeLLMClient(),
            router_model="gpt-4.1-mini",
            advice_model="gpt-4.1",
            source_provider=FakeSourceProvider(),
        )
        result = agent.answer("台风过后，对于小麦种植需要注意哪些？")
        self.assertEqual(result["mode"], "advice")
        self.assertIn("sources", result["evidence"])
        self.assertEqual(result["evidence"]["sources"][0]["title"], "农业农村部防灾指导")


class AgentGraphTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.td.cleanup()

    def test_thread_follow_up_forecast_uses_langgraph_and_memory(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        first = agent.answer("过去5个月虫情最严重的地方是哪里？", thread_id="thread-forecast")
        second = agent.answer("未来两周呢", thread_id="thread-forecast")

        self.assertEqual(first["mode"], "data_query")
        self.assertEqual(second["mode"], "data_query")
        self.assertEqual(second["processing"]["orchestration"], "LangGraph")
        self.assertEqual(second["processing"]["memory"], "LocalMemory")
        self.assertEqual(second["evidence"]["analysis_context"]["domain"], "pest")
        self.assertEqual(second["evidence"]["forecast"]["horizon_days"], 14)
        self.assertEqual(second["evidence"]["forecast"]["forecast_backend"], "statsforecast")
        self.assertEqual(second["evidence"]["forecast"]["model_name"], "AutoETS")
        self.assertTrue(second["evidence"]["request_understanding"]["used_context"])
        self.assertIn("未来两周", second["answer"])

    def test_follow_up_advice_reuses_previous_analysis_context(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )
        spy_advice = SpyAdviceEngine()
        agent.advice_engine = spy_advice

        agent.answer("过去5个月虫情最严重的地方是哪里？", thread_id="thread-advice")
        result = agent.answer("给建议", thread_id="thread-advice")

        self.assertEqual(result["mode"], "advice")
        self.assertEqual(result["processing"]["orchestration"], "LangGraph")
        self.assertEqual(result["evidence"]["analysis_context"]["domain"], "pest")
        self.assertEqual(spy_advice.calls[-1]["context"]["domain"], "pest")
        self.assertIn("徐州市", result["answer"])

    def test_mixed_historical_forecast_and_rag_request_returns_execution_plan(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            source_provider=RichFakeSourceProvider(),
        )

        result = agent.answer(
            "我不太会表达，你先看看过去5个月虫情最严重的地方是哪里，"
            "再判断未来两周会不会更糟，解释一下为什么，最后给处置建议",
            thread_id="thread-mixed",
        )

        self.assertEqual(result["mode"], "analysis")
        self.assertEqual(result["processing"]["orchestration"], "LangGraph")
        self.assertEqual(
            result["evidence"]["execution_plan"],
            ["understand_request", "historical_query", "forecast", "knowledge_retrieval", "answer_synthesis"],
        )
        self.assertEqual(result["evidence"]["request_understanding"]["resolved_question"], result["evidence"]["request_understanding"]["original_question"])
        self.assertEqual(result["evidence"]["analysis_context"]["domain"], "pest")
        self.assertEqual(result["evidence"]["forecast"]["horizon_days"], 14)
        self.assertTrue(result["evidence"]["knowledge"])
        self.assertEqual(result["evidence"]["knowledge"][0]["retrieval_backend"], "qdrant")
        self.assertEqual(result["evidence"]["memory_state"]["memory_version"], 2)
        self.assertEqual(result["processing"]["retrieval"], "Qdrant / semantic-vector")
        self.assertIn("历史数据", result["answer"])
        self.assertIn("预测", result["answer"])
        self.assertIn("建议", result["answer"])

    def test_explanation_follow_up_uses_context_and_returns_reasoning(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            llm_client=AggressiveRouterLLM(),
            router_model="gpt-4.1-mini",
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            source_provider=RichFakeSourceProvider(),
        )

        agent.answer("过去5个月灾害最严重的地方是哪里", thread_id="thread-why")
        agent.answer("墒情", thread_id="thread-why")
        result = agent.answer("为什么", thread_id="thread-why")

        self.assertEqual(result["mode"], "advice")
        self.assertTrue(result["evidence"]["request_understanding"]["used_context"])
        self.assertEqual(result["evidence"]["analysis_context"]["domain"], "soil")
        self.assertIn("原因", result["answer"])
        self.assertIn(result["evidence"]["analysis_context"]["region_name"], result["answer"])

    def test_identity_question_returns_agent_intro(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("你是谁？", thread_id="thread-identity")

        self.assertEqual(result["mode"], "advice")
        self.assertIn("AI农情工作台", result["answer"])
        self.assertIn("虫情", result["answer"])

    def test_joint_risk_question_keeps_mixed_domain_semantics(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("过去90天，哪些地区同时出现高虫情和低墒情？", thread_id="thread-joint-risk")

        self.assertEqual(result["mode"], "data_query")
        self.assertIn("联合风险地区", result["answer"])
        self.assertEqual(result["evidence"]["analysis_context"]["query_type"], "joint_risk")

    def test_short_city_follow_up_switches_region_in_forecast_context(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            source_provider=RichFakeSourceProvider(),
        )

        agent.answer("近3个星期，受灾最严重的地方是哪里", thread_id="thread-short-city")
        agent.answer("虫情", thread_id="thread-short-city")
        agent.answer("未来两周会怎样", thread_id="thread-short-city")
        result = agent.answer("南京呢", thread_id="thread-short-city")

        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(result["evidence"]["analysis_context"]["region_name"], "南京市")
        self.assertIn("南京市", result["answer"])
        self.assertIn("未来两周", result["answer"])

    def test_generic_future_advice_follow_up_does_not_stick_to_top_ranked_city(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        agent.answer("近3个星期，受灾最严重的地方是哪里", thread_id="thread-generic-future-advice")
        agent.answer("虫情", thread_id="thread-generic-future-advice")
        result = agent.answer("未来虫害怎么养", thread_id="thread-generic-future-advice")

        self.assertEqual(result["mode"], "advice")
        self.assertEqual(result["evidence"]["analysis_context"]["domain"], "pest")
        self.assertEqual(result["evidence"]["analysis_context"]["region_name"], "")
        self.assertNotIn("徐州市", result["answer"])

    def test_empty_structured_pest_top_mentions_available_range(self):
        agent = DocAIAgent(
            EmptyStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("过去5个月虫情最严重的地方是哪里？", thread_id="thread-empty-pest-top")

        self.assertEqual(result["mode"], "data_query")
        self.assertIn("暂无可用虫情严重度数据", result["answer"])
        self.assertIn("当前可用虫情监测数据范围为 2026-01-05 至 2026-04-08", result["answer"])
        self.assertEqual(
            result["evidence"]["available_data_ranges"],
            [
                {
                    "source": "pest",
                    "label": "虫情监测数据",
                    "min_time": "2026-01-05 00:00:00",
                    "max_time": "2026-04-08 00:00:00",
                }
            ],
        )
        self.assertEqual(result["evidence"]["no_data_reasons"][0]["code"], "no_matching_records")

    def test_empty_structured_soil_top_mentions_available_range(self):
        agent = DocAIAgent(
            EmptyStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("过去5个月缺水最厉害的地方是哪里？", thread_id="thread-empty-soil-top")

        self.assertEqual(result["mode"], "data_query")
        self.assertIn("暂无可用于地区统计的墒情异常数据", result["answer"])
        self.assertIn("当前可用墒情监测数据范围为 2026-01-07 至 2026-04-09", result["answer"])
        self.assertEqual(
            result["evidence"]["available_data_ranges"],
            [
                {
                    "source": "soil",
                    "label": "墒情监测数据",
                    "min_time": "2026-01-07 00:00:00",
                    "max_time": "2026-04-09 00:00:00",
                }
            ],
        )
        self.assertEqual(result["evidence"]["no_data_reasons"][0]["code"], "no_matching_records")

    def test_empty_structured_pest_trend_mentions_available_range(self):
        agent = DocAIAgent(
            EmptyStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("南京近三周虫害走势怎么样？", thread_id="thread-empty-pest-trend")

        self.assertEqual(result["mode"], "data_query")
        self.assertIn("南京市", result["answer"])
        self.assertIn("暂无可用虫情趋势数据", result["answer"])
        self.assertIn("当前可用虫情监测数据范围为 2026-01-05 至 2026-04-08", result["answer"])
        self.assertNotIn("1970-01-01", result["answer"])
        self.assertEqual(
            result["evidence"]["available_data_ranges"],
            [
                {
                    "source": "pest",
                    "label": "虫情监测数据",
                    "min_time": "2026-01-05 00:00:00",
                    "max_time": "2026-04-08 00:00:00",
                }
            ],
        )
        self.assertEqual(result["evidence"]["no_data_reasons"][0]["code"], "no_region_records")
        self.assertEqual(result["evidence"]["recovery_suggestions"][0]["action"], "broaden_region_scope")
        self.assertIn("先去掉南京市", result["evidence"]["recovery_suggestions"][0]["message"])

    def test_empty_structured_soil_trend_mentions_available_range(self):
        agent = DocAIAgent(
            EmptyStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("南京近三周墒情走势怎么样？", thread_id="thread-empty-soil-trend")

        self.assertEqual(result["mode"], "data_query")
        self.assertIn("南京市", result["answer"])
        self.assertIn("暂无可用墒情趋势数据", result["answer"])
        self.assertIn("当前可用墒情监测数据范围为 2026-01-07 至 2026-04-09", result["answer"])
        self.assertNotIn("1970-01-01", result["answer"])
        self.assertEqual(
            result["evidence"]["available_data_ranges"],
            [
                {
                    "source": "soil",
                    "label": "墒情监测数据",
                    "min_time": "2026-01-07 00:00:00",
                    "max_time": "2026-04-09 00:00:00",
                }
            ],
        )
        self.assertEqual(result["evidence"]["no_data_reasons"][0]["code"], "no_region_records")

    def test_empty_structured_joint_risk_mentions_both_available_ranges(self):
        agent = DocAIAgent(
            EmptyStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("近两个月哪些地方虫情高而且缺水更明显？", thread_id="thread-empty-joint-risk")

        self.assertEqual(result["mode"], "data_query")
        self.assertIn("暂无满足联合风险条件的地区", result["answer"])
        self.assertIn("当前可用虫情监测数据范围为 2026-01-05 至 2026-04-08", result["answer"])
        self.assertIn("当前可用墒情监测数据范围为 2026-01-07 至 2026-04-09", result["answer"])
        self.assertEqual(
            result["evidence"]["available_data_ranges"],
            [
                {
                    "source": "pest",
                    "label": "虫情监测数据",
                    "min_time": "2026-01-05 00:00:00",
                    "max_time": "2026-04-08 00:00:00",
                },
                {
                    "source": "soil",
                    "label": "墒情监测数据",
                    "min_time": "2026-01-07 00:00:00",
                    "max_time": "2026-04-09 00:00:00",
                },
            ],
        )
        self.assertEqual(result["evidence"]["no_data_reasons"][0]["code"], "no_joint_risk_matches")
        self.assertEqual(result["evidence"]["recovery_suggestions"][0]["action"], "split_joint_risk")
        self.assertIn("先分别查看虫情和墒情", result["evidence"]["recovery_suggestions"][0]["message"])
        self.assertEqual(len(result["evidence"]["recovery_suggestions"][0]["suggested_questions"]), 2)

    def test_region_overview_question_returns_overview_instead_of_top_ranking(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("给我过去五个月徐州的虫害情况", thread_id="thread-region-overview")

        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(result["evidence"]["analysis_context"]["query_type"], "pest_overview")
        self.assertEqual(result["evidence"]["analysis_context"]["region_name"], "徐州市")
        self.assertEqual(result["evidence"]["request_understanding"]["task_type"], "region_overview")
        self.assertIn("徐州市", result["answer"])
        self.assertNotIn("Top5", result["answer"])


if __name__ == "__main__":
    unittest.main()
