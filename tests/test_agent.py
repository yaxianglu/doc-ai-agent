import os
import tempfile
import unittest

from doc_ai_agent.agent import DocAIAgent
from doc_ai_agent.advice_engine import AdviceResult
from doc_ai_agent.repository import AlertRepository
from doc_ai_agent.source_provider import QdrantSourceProvider


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


class RecallThenRerankBackend:
    def __init__(self):
        self.last_limit = None

    def search(self, question, limit=3, context=None):
        del question, context
        self.last_limit = limit
        return [
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
            {
                "title": "虫情监测与绿色防控技术",
                "url": "https://example.gov/pest-generic",
                "published_at": "2026-02-14",
                "snippet": "针对迁飞性害虫应加强监测预警，按阈值采取分区防控措施。",
                "domain": "pest",
                "tags": ["虫情", "防控", "阈值"],
                "retrieval_engine": "qdrant",
                "retrieval_backend": "qdrant",
                "retrieval_strategy": "semantic-vector",
            },
            {
                "title": "徐州市虫情阈值分区防控指南",
                "url": "https://example.gov/pest-xz",
                "published_at": "2026-03-01",
                "snippet": "徐州市连续高值时，按地块阈值执行分区防控并在24-48小时复查。",
                "domain": "pest",
                "tags": ["徐州市", "虫情", "阈值", "分区防控"],
                "retrieval_engine": "qdrant",
                "retrieval_backend": "qdrant",
                "retrieval_strategy": "semantic-vector",
            },
        ][:limit]


class FakeStructuredRepo:
    def top_pest_regions(self, since, until, region_level="city", top_n=5, city=None, county=None):
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

    def top_soil_regions(self, since, until, region_level="city", top_n=5, anomaly_direction=None, city=None, county=None):
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

    def alerts_trend(self, since, until=None, city=None):
        if city == "徐州市":
            return [
                {"date": "2026-03-15", "alert_count": 2},
                {"date": "2026-03-29", "alert_count": 5},
                {"date": "2026-04-13", "alert_count": 8},
            ]
        return [
            {"date": "2026-03-15", "alert_count": 4},
            {"date": "2026-03-29", "alert_count": 9},
            {"date": "2026-04-13", "alert_count": 12},
        ]


class CountyRankingRepo(FakeStructuredRepo):
    def __init__(self):
        self.last_top_pest_region_level = None
        self.last_top_pest_city = None

    def top_pest_regions(self, since, until, region_level="city", top_n=5, city=None, county=None):
        self.last_top_pest_region_level = region_level
        self.last_top_pest_city = city
        return [
            {
                "region_name": "铜山区",
                "severity_score": 92,
                "record_count": 18,
                "active_days": 9,
            },
            {
                "region_name": "睢宁县",
                "severity_score": 75,
                "record_count": 13,
                "active_days": 7,
            },
        ][:top_n]


class LargeRankingRepo(FakeStructuredRepo):
    def top_pest_regions(self, since, until, region_level="city", top_n=5, city=None, county=None):
        rows = []
        for idx in range(1, 13):
            rows.append(
                {
                    "region_name": f"地区{idx}",
                    "severity_score": 120 - idx,
                    "record_count": 30 - idx,
                    "active_days": 15 - min(idx, 10),
                }
            )
        return rows[:top_n]


class VerboseDetailRepo(FakeStructuredRepo):
    def pest_trend(self, since, until, region_name, region_level="city"):
        return [
            {"date": "2026-03-01", "severity_score": 1},
            {"date": "2026-03-02", "severity_score": 0},
            {"date": "2026-03-03", "severity_score": 2},
            {"date": "2026-03-04", "severity_score": 4},
            {"date": "2026-03-05", "severity_score": 0},
            {"date": "2026-03-06", "severity_score": 6},
            {"date": "2026-03-07", "severity_score": 8},
            {"date": "2026-03-08", "severity_score": 3},
            {"date": "2026-03-09", "severity_score": 12},
            {"date": "2026-03-10", "severity_score": 5},
            {"date": "2026-03-11", "severity_score": 15},
            {"date": "2026-03-12", "severity_score": 7},
        ]


class BucketDetailRepo(FakeStructuredRepo):
    def pest_trend(self, since, until, region_name, region_level="city"):
        return [
            {"bucket": "2026-04-03", "severity_score": 0},
            {"bucket": "2026-04-04", "severity_score": 2},
            {"bucket": "2026-04-05", "severity_score": 5},
            {"bucket": "2026-04-06", "severity_score": 0},
            {"bucket": "2026-04-07", "severity_score": 7},
            {"bucket": "2026-04-08", "severity_score": 4},
            {"bucket": "2026-04-09", "severity_score": 1},
        ]


class CompareStructuredRepo(FakeStructuredRepo):
    PEST_SERIES = {
        "徐州市": [
            {"date": "2026-03-28", "severity_score": 18},
            {"date": "2026-03-29", "severity_score": 24},
            {"date": "2026-03-30", "severity_score": 32},
        ],
        "苏州市": [
            {"date": "2026-03-28", "severity_score": 5},
            {"date": "2026-03-29", "severity_score": 7},
            {"date": "2026-03-30", "severity_score": 9},
        ],
        "淮安市": [
            {"date": "2026-03-28", "severity_score": 9},
            {"date": "2026-03-29", "severity_score": 12},
            {"date": "2026-03-30", "severity_score": 16},
        ],
        "南京市": [
            {"date": "2026-03-28", "severity_score": 7},
            {"date": "2026-03-29", "severity_score": 8},
            {"date": "2026-03-30", "severity_score": 10},
        ],
    }
    SOIL_SERIES = {
        "南京市": [
            {"date": "2026-03-28", "avg_anomaly_score": 11},
            {"date": "2026-03-29", "avg_anomaly_score": 9},
            {"date": "2026-03-30", "avg_anomaly_score": 8},
        ],
        "无锡市": [
            {"date": "2026-03-28", "avg_anomaly_score": 4},
            {"date": "2026-03-29", "avg_anomaly_score": 3},
            {"date": "2026-03-30", "avg_anomaly_score": 2},
        ],
        "苏州市": [
            {"date": "2026-03-28", "avg_anomaly_score": 3},
            {"date": "2026-03-29", "avg_anomaly_score": 4},
            {"date": "2026-03-30", "avg_anomaly_score": 3},
        ],
    }

    def pest_trend(self, since, until, region_name, region_level="city"):
        return list(self.PEST_SERIES.get(region_name, self.PEST_SERIES["苏州市"]))

    def soil_trend(self, since, until, region_name, region_level="city"):
        return list(self.SOIL_SERIES.get(region_name, self.SOIL_SERIES["苏州市"]))


class EmptyStructuredRepo:
    def top_pest_regions(self, since, until, region_level="city", top_n=5, city=None, county=None):
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

    def top_soil_regions(self, since, until, region_level="city", top_n=5, anomaly_direction=None, city=None, county=None):
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
    def test_agent_planner_consumes_semantic_parse_result_for_ood(self):
        class NeutralSemanticJudger:
            def judge(self, _question: str):
                return {
                    "reason": "",
                    "intent": "advice",
                    "confidence": 0.0,
                    "needs_clarification": False,
                    "clarification": None,
                }

        class ForcedOutOfScopeSemanticParser:
            def parse(self, question: str, context: dict | None = None):
                del context
                from doc_ai_agent.semantic_parse import SemanticParseResult

                return SemanticParseResult(
                    normalized_query=str(question or "").strip(),
                    intent="advice",
                    is_out_of_scope=True,
                    fallback_reason="out_of_scope_weather",
                    trace=["normalize", "ood", "ood:out_of_scope_weather"],
                )

        agent = DocAIAgent(
            AlertRepository(self.db),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            semantic_parser=ForcedOutOfScopeSemanticParser(),
        )
        agent.query_planner.semantic_judger = NeutralSemanticJudger()

        result = agent.answer("过去5个月虫情最严重的地方是哪里", thread_id="thread-semantic-ood")

        self.assertEqual(result["mode"], "advice")
        self.assertEqual(result["evidence"]["response_meta"]["fallback_reason"], "out_of_scope_weather")
        self.assertIn("虫情", result["answer"])

    def test_low_semantic_confidence_uses_clarification_response_meta(self):
        class NeutralSemanticJudger:
            def judge(self, _question: str):
                return {
                    "reason": "",
                    "intent": "advice",
                    "confidence": 0.0,
                    "needs_clarification": False,
                    "clarification": None,
                }

        class ForcedLowConfidenceSemanticParser:
            def parse(self, question: str, context: dict | None = None):
                del context
                from doc_ai_agent.semantic_parse import SemanticParseResult

                return SemanticParseResult(
                    normalized_query=str(question or "").strip(),
                    intent="data_query",
                    domain="pest",
                    task_type="trend",
                    confidence=0.22,
                    trace=["normalize", "slots"],
                )

        agent = DocAIAgent(
            AlertRepository(self.db),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            semantic_parser=ForcedLowConfidenceSemanticParser(),
        )
        agent.query_planner.semantic_judger = NeutralSemanticJudger()

        result = agent.answer("过去5个月虫情趋势如何", thread_id="thread-semantic-low-confidence")

        self.assertEqual(result["mode"], "advice")
        self.assertEqual(result["evidence"]["generation_mode"], "clarification")
        self.assertEqual(result["evidence"]["response_meta"]["fallback_reason"], "semantic_low_confidence")
        self.assertLess(result["evidence"]["response_meta"]["confidence"], 0.4)

    def test_identity_question_returns_capability_intro(self):
        agent = DocAIAgent(
            AlertRepository(self.db),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("你是谁？", thread_id="thread-identity")

        self.assertEqual(result["mode"], "advice")
        self.assertIn("AI农情工作台", result["answer"])
        self.assertIn("虫情", result["answer"])
        self.assertEqual(result["evidence"]["generation_mode"], "rule")
        self.assertFalse(result["evidence"]["request_understanding"]["used_context"])
        self.assertEqual(result["evidence"]["request_understanding"]["fallback_reason"], "identity_self_intro")
        self.assertIn("edge:identity_self_intro", result["evidence"]["request_understanding"]["trace"])

    def test_greeting_does_not_answer_with_stale_agri_context(self):
        agent = DocAIAgent(
            AlertRepository(self.db),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        agent.answer("过去5个月常州虫情最严重的地方是哪里", thread_id="thread-greeting")
        follow_up = agent.answer("你好", thread_id="thread-greeting")

        self.assertEqual(follow_up["mode"], "advice")
        self.assertIn("AI农情工作台", follow_up["answer"])
        self.assertNotIn("常州市", follow_up["answer"])
        self.assertEqual(follow_up["evidence"]["generation_mode"], "rule")
        self.assertFalse(follow_up["evidence"]["request_understanding"]["used_context"])
        self.assertEqual(follow_up["evidence"]["request_understanding"]["fallback_reason"], "greeting_intro")
        self.assertIn("edge:greeting_intro", follow_up["evidence"]["request_understanding"]["trace"])

    def test_non_agri_topic_does_not_answer_with_stale_agri_context(self):
        agent = DocAIAgent(
            AlertRepository(self.db),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        agent.answer("过去5个月墒情最严重的地方是哪里", thread_id="thread-weather")
        follow_up = agent.answer("浙江天气", thread_id="thread-weather")

        self.assertEqual(follow_up["evidence"]["generation_mode"], "clarification")
        self.assertFalse(follow_up["evidence"]["request_understanding"]["used_context"])
        self.assertIn("天气", follow_up["answer"])
        self.assertIn("虫情", follow_up["answer"])
        self.assertNotIn("淮安", follow_up["answer"])
        self.assertNotIn("徐州", follow_up["answer"])
        self.assertGreaterEqual(follow_up["evidence"]["request_understanding"]["confidence"], 0.8)
        self.assertEqual(follow_up["evidence"]["request_understanding"]["fallback_reason"], "out_of_scope_weather")
        self.assertIn("ood", follow_up["evidence"]["request_understanding"]["trace"])
        self.assertIn("ood:out_of_scope_weather", follow_up["evidence"]["request_understanding"]["trace"])
        self.assertEqual(follow_up["evidence"]["response_meta"]["fallback_reason"], "out_of_scope_weather")

    def test_non_agri_topic_news_and_ticket_use_explicit_fallback_categories(self):
        agent = DocAIAgent(
            AlertRepository(self.db),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        cases = [
            ("今天有什么新闻", "out_of_scope_news"),
            ("帮我订高铁票", "out_of_scope_transport_ticket"),
        ]
        for question, reason in cases:
            with self.subTest(question=question):
                result = agent.answer(question, thread_id=f"thread-ood-{reason}")
                self.assertEqual(result["evidence"]["generation_mode"], "clarification")
                self.assertEqual(result["evidence"]["request_understanding"]["fallback_reason"], reason)
                self.assertIn(f"ood:{reason}", result["evidence"]["request_understanding"]["trace"])
                self.assertEqual(result["evidence"]["response_meta"]["fallback_reason"], reason)

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
        self.assertEqual(result["evidence"]["response_meta"]["fallback_reason"], "outside_available_window")
        self.assertIn("db", result["evidence"]["response_meta"]["source_types"])
        self.assertLess(result["evidence"]["response_meta"]["confidence"], 0.5)

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

    def test_single_day_city_count_uses_exact_city_filter(self):
        result = self.agent.answer("2026年1月3日徐州市发生了多少条预警？")

        self.assertEqual(result["mode"], "data_query")
        self.assertIn("徐州市预警信息共 1 条", result["answer"])
        self.assertEqual(result["evidence"]["city"], "徐州市")
        self.assertEqual(result["evidence"]["since"], "2026-01-03 00:00:00")
        self.assertEqual(result["evidence"]["until"], "2026-01-04 00:00:00")

    def test_single_day_city_level_count_uses_exact_city_filter(self):
        result = self.agent.answer("2026年1月3日徐州市涝渍等级预警有多少条？")

        self.assertEqual(result["mode"], "data_query")
        self.assertIn("徐州市涝渍等级预警信息共 1 条", result["answer"])
        self.assertEqual(result["evidence"]["city"], "徐州市")
        self.assertEqual(result["evidence"]["alert_level"], "涝渍")

    def test_alert_top_question_with_baojing_wording_is_not_misrouted_to_advice(self):
        result = self.agent.answer("最近10天报警最多的是哪里？")

        self.assertEqual(result["mode"], "data_query")
        self.assertNotIn("你希望我做数据统计", result["answer"])
        self.assertIn("Top", result["answer"])
        self.assertEqual(result["evidence"]["query_type"], "top")

    def test_threshold_summary_stays_data_only(self):
        result = self.agent.answer("告警值超过20的预警主要在哪些城市？")

        self.assertEqual(result["mode"], "data_query")
        self.assertIn("主要集中在", result["answer"])
        self.assertNotIn("预测：", result["answer"])
        self.assertNotIn("建议：", result["answer"])
        self.assertNotIn("未来两周", result["answer"])

    def test_advice_query(self):
        result = self.agent.answer("台风过后，对于小麦种植需要注意哪些？")
        self.assertEqual(result["mode"], "advice")
        self.assertIn("排水", result["answer"])
        self.assertEqual(result["evidence"]["generation_mode"], "rule")

    def test_advice_query_uses_expert_style_sections(self):
        result = self.agent.answer("台风过后，对于小麦种植需要注意哪些？")

        self.assertEqual(result["mode"], "advice")
        self.assertIn("建议：", result["answer"])

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
        self.assertIn("llm", result["evidence"]["response_meta"]["source_types"])
        self.assertGreater(result["evidence"]["response_meta"]["confidence"], 0.7)

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
        self.assertIn("置信度", second["answer"])
        self.assertTrue(second["evidence"]["forecast"]["top_factors"])
        self.assertGreater(second["evidence"]["forecast"]["confidence"], 0)

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

    def test_follow_up_explanation_uses_expert_style_sections(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        agent.answer("过去5个月虫情最严重的地方是哪里？", thread_id="thread-explanation")
        result = agent.answer("为什么", thread_id="thread-explanation")

        self.assertEqual(result["mode"], "advice")
        self.assertIn("原因：", result["answer"])
        self.assertIn("依据：", result["answer"])

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
        self.assertIn("结论：", result["answer"])
        self.assertIn("预测", result["answer"])
        self.assertIn("建议", result["answer"])
        self.assertEqual(
            [task["type"] for task in result["evidence"]["task_graph"]["tasks"]],
            ["historical_rank", "cause_retrieval", "forecast", "advice_retrieval", "merge_answer"],
        )
        self.assertEqual(result["evidence"]["task_graph"]["merge_strategy"], "sectioned_answer")
        self.assertEqual(
            [task["stage"] for task in result["evidence"]["task_graph"]["tasks"]],
            ["historical_query", "knowledge_retrieval", "forecast", "knowledge_retrieval", "answer_synthesis"],
        )
        self.assertGreater(result["evidence"]["response_meta"]["confidence"], 0.7)
        self.assertEqual(result["evidence"]["response_meta"]["fallback_reason"], "")
        self.assertEqual(result["evidence"]["response_meta"]["source_types"], ["db", "forecast", "rag"])
        self.assertIn("结论：", result["answer"])
        self.assertIn("原因：", result["answer"])
        self.assertIn("依据：", result["answer"])
        self.assertIn("建议：", result["answer"])

    def test_analysis_answer_uses_reranked_knowledge_grounding_order(self):
        backend = RecallThenRerankBackend()
        source_provider = QdrantSourceProvider(items=[], backend=backend)
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            source_provider=source_provider,
        )

        result = agent.answer(
            "我不太会表达，你先看看过去5个月虫情最严重的地方是哪里，"
            "再解释一下为什么，最后给处置建议",
            thread_id="thread-mixed-rerank",
        )

        self.assertEqual(result["mode"], "analysis")
        self.assertGreater(backend.last_limit or 0, 3)
        self.assertEqual(result["evidence"]["knowledge"][0]["title"], "徐州市虫情阈值分区防控指南")
        self.assertEqual(result["evidence"]["knowledge_sources"][0]["title"], "徐州市虫情阈值分区防控指南")
        self.assertIn("依据：参考 徐州市虫情阈值分区防控指南；虫情监测与绿色防控技术", result["answer"])

    def test_compare_two_regions_returns_actual_comparison(self):
        agent = DocAIAgent(
            CompareStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("对比过去5个月徐州和苏州的虫情", thread_id="thread-compare-regions")

        self.assertEqual(result["mode"], "data_query")
        self.assertIn("徐州市", result["answer"])
        self.assertIn("苏州市", result["answer"])
        self.assertIn("对比结果", result["answer"])
        self.assertIn("更突出", result["answer"])
        self.assertEqual(result["evidence"]["analysis_context"]["query_type"], "pest_compare")

    def test_compare_two_regions_trend_returns_two_sided_answer(self):
        agent = DocAIAgent(
            CompareStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("今年以来徐州和淮安虫情变化对比", thread_id="thread-compare-trend")

        self.assertEqual(result["mode"], "data_query")
        self.assertIn("徐州市", result["answer"])
        self.assertIn("淮安市", result["answer"])
        self.assertIn("变化对比", result["answer"])
        self.assertEqual(result["evidence"]["analysis_context"]["query_type"], "pest_compare")

    def test_compare_same_region_cross_domain_returns_more_prominent_issue(self):
        agent = DocAIAgent(
            CompareStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("过去3个月苏州虫情和墒情哪个问题更突出", thread_id="thread-compare-cross-domain")

        self.assertEqual(result["mode"], "data_query")
        self.assertIn("苏州市", result["answer"])
        self.assertIn("虫情", result["answer"])
        self.assertIn("墒情", result["answer"])
        self.assertIn("更突出", result["answer"])
        self.assertEqual(result["evidence"]["analysis_context"]["query_type"], "cross_domain_compare")

    def test_simple_ranking_request_emits_minimal_task_graph(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("过去5个月虫情最严重的地方是哪里？", thread_id="thread-task-graph-simple")

        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(
            [task["type"] for task in result["evidence"]["task_graph"]["tasks"]],
            ["historical_rank", "merge_answer"],
        )

    def test_county_ranking_request_preserves_county_scope_end_to_end(self):
        repo = CountyRankingRepo()
        agent = DocAIAgent(
            repo,
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("过去5个月虫情最严重的是哪些县", thread_id="thread-county-ranking")

        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(repo.last_top_pest_region_level, "county")
        self.assertIn("区县", result["answer"])
        self.assertIn("铜山区", result["answer"])
        self.assertEqual(result["evidence"]["request_understanding"]["region_level"], "county")
        self.assertEqual(result["evidence"]["historical_query"]["region_level"], "county")
        self.assertEqual(result["evidence"]["analysis_context"]["region_level"], "county")
        self.assertEqual(result["evidence"]["memory_state"]["route"]["region_level"], "county")

    def test_highest_county_ranking_request_preserves_county_scope_end_to_end(self):
        repo = CountyRankingRepo()
        agent = DocAIAgent(
            repo,
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("近3个月虫情最高的县有哪些", thread_id="thread-county-ranking-highest")

        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(repo.last_top_pest_region_level, "county")
        self.assertIn("区县", result["answer"])
        self.assertIn("铜山区", result["answer"])
        self.assertEqual(result["evidence"]["request_understanding"]["task_type"], "ranking")
        self.assertEqual(result["evidence"]["request_understanding"]["region_level"], "county")
        self.assertEqual(result["evidence"]["historical_query"]["query_type"], "pest_top")
        self.assertEqual(result["evidence"]["historical_query"]["region_level"], "county")
        self.assertEqual(result["evidence"]["analysis_context"]["region_level"], "county")
        self.assertEqual(result["evidence"]["memory_state"]["route"]["region_level"], "county")

    def test_city_scoped_county_ranking_does_not_leak_1970_in_answer(self):
        repo = CountyRankingRepo()
        agent = DocAIAgent(
            repo,
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("常州市下面虫情最严重的县有哪些？", thread_id="thread-city-county-ranking")

        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(repo.last_top_pest_city, "常州市")
        self.assertEqual(result["evidence"]["request_understanding"]["region_level"], "county")
        self.assertEqual(result["evidence"]["historical_query"]["region_level"], "county")
        self.assertNotIn("1970-01-01", result["answer"])
        self.assertIn("区县", result["answer"])

    def test_multi_turn_highest_county_and_future_follow_up_preserve_ranking_scope(self):
        agent = DocAIAgent(
            CountyRankingRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        first = agent.answer("过去5个月最严重的是哪里？", thread_id="thread-multi-turn-ranking")
        second = agent.answer("其中虫情的呢？", thread_id="thread-multi-turn-ranking")
        third = agent.answer("最高的县有哪些？", thread_id="thread-multi-turn-ranking")
        fourth = agent.answer("那未来两周呢？", thread_id="thread-multi-turn-ranking")

        self.assertEqual(first["mode"], "advice")
        self.assertEqual(second["mode"], "data_query")
        self.assertEqual(third["mode"], "data_query")
        self.assertEqual(third["evidence"]["analysis_context"]["region_level"], "county")
        self.assertNotEqual(third["evidence"]["analysis_context"]["region_name"], "最高的县")
        self.assertEqual(fourth["mode"], "data_query")
        self.assertEqual(fourth["evidence"]["forecast"]["mode"], "ranking")
        self.assertIn("风险最高", fourth["answer"])

    def test_ranking_request_respects_requested_top_n(self):
        agent = DocAIAgent(
            LargeRankingRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("最近30天虫情最严重的前10个地区", thread_id="thread-top-10")

        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(len(result["data"]), 10)
        self.assertIn("Top10", result["answer"])
        self.assertIn("10.", result["answer"])

    def test_agent_prefers_query_plan_execution_route_over_legacy_route(self):
        agent = DocAIAgent(
            LargeRankingRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        execution_route = {
            "query_type": "pest_top",
            "since": "2025-11-01 00:00:00",
            "until": None,
            "city": None,
            "county": None,
            "device_code": None,
            "region_level": "city",
            "window": {"window_type": "months", "window_value": 5},
            "top_n": 3,
            "forecast_window": None,
            "forecast_mode": "",
        }
        legacy_route = dict(execution_route)
        legacy_route["top_n"] = 1
        query_plan = {
            "version": "v1",
            "goal": "agri_analysis",
            "intent": "analysis",
            "slots": {
                "domain": "pest",
                "metric": "pest_severity",
                "time_range": {"mode": "relative", "value": "5_months"},
                "region_scope": {"level": "city", "value": "all"},
                "aggregation": "top_k",
                "k": 3,
                "need_explanation": False,
                "need_forecast": False,
                "need_advice": False,
            },
            "constraints": {
                "must_use_structured_data": True,
                "allow_clarification": True,
            },
            "execution": {
                "route": execution_route,
                "domain": "pest",
                "region_name": "",
                "historical_window": {"window_type": "months", "window_value": 5},
                "future_window": None,
                "answer_mode": "ranking",
            },
        }

        agent.query_planner.plan = lambda *args, **kwargs: {
            "intent": "data_query",
            "confidence": 0.9,
            "route": legacy_route,
            "query_plan": query_plan,
            "needs_clarification": False,
            "clarification": None,
            "reason": "test_execution_route_source",
            "context_trace": [],
        }

        result = agent.answer("过去5个月虫情最严重的地方是哪里？", thread_id="thread-query-plan-route")

        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(len(result["data"]), 3)
        self.assertIn("Top3", result["answer"])
        self.assertEqual(result["evidence"]["memory_state"]["route"]["top_n"], 3)

    def test_memory_state_exposes_slot_metadata(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("给我过去5个月苏州市的虫害情况", thread_id="thread-slot-memory")

        slots = result["evidence"]["memory_state"]["slots"]
        self.assertEqual(slots["domain"]["value"], "pest")
        self.assertEqual(slots["region"]["value"], "苏州市")
        self.assertEqual(slots["time_range"]["value"], {"mode": "relative", "value": "5_months"})
        self.assertEqual(slots["intent"]["value"], "analysis")
        for slot_name in ["domain", "region", "time_range", "intent"]:
            for field in ["value", "source", "priority", "ttl", "updated_at_turn"]:
                self.assertIn(field, slots[slot_name])

    def test_greeting_does_not_overwrite_business_slots(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        agent.answer("给我过去5个月苏州市的虫害情况", thread_id="thread-slot-greeting")
        follow_up = agent.answer("你好", thread_id="thread-slot-greeting")

        slots = follow_up["evidence"]["memory_state"]["slots"]
        self.assertEqual(slots["domain"]["value"], "pest")
        self.assertEqual(slots["region"]["value"], "苏州市")
        self.assertEqual(slots["time_range"]["value"], {"mode": "relative", "value": "5_months"})
        self.assertEqual(slots["domain"]["updated_at_turn"], 1)
        self.assertEqual(slots["region"]["updated_at_turn"], 1)
        self.assertEqual(slots["time_range"]["updated_at_turn"], 1)

    def test_detail_answer_is_summarized_instead_of_dumping_full_series(self):
        agent = DocAIAgent(
            VerboseDetailRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("给我过去5个月徐州的虫害具体数据", thread_id="thread-detail-summary")

        self.assertEqual(result["mode"], "data_query")
        self.assertIn("具体数据摘要", result["answer"])
        self.assertIn("共12个观测日", result["answer"])
        self.assertIn("峰值15", result["answer"])
        self.assertIn("最近7个观测日", result["answer"])
        self.assertIn("2026-03-12", result["answer"])
        self.assertNotIn("2026-03-01 严重度1", result["answer"])

    def test_detail_answer_uses_bucket_dates_when_date_field_is_missing(self):
        agent = DocAIAgent(
            BucketDetailRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("过去5个月徐州虫情具体数据。", thread_id="thread-detail-bucket")

        self.assertIn("2026-04-09", result["answer"])
        self.assertIn("2026-04-08", result["answer"])
        self.assertNotIn("峰值7（）", result["answer"])
        self.assertNotIn("最近值1（）", result["answer"])

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
        self.assertEqual(result["evidence"]["request_understanding"]["followup_type"], "explanation_follow_up")
        self.assertEqual(
            result["evidence"]["memory_state"]["conversation_state"]["last_followup_type"],
            "explanation_follow_up",
        )
        self.assertEqual(result["evidence"]["analysis_context"]["domain"], "soil")
        self.assertIn("原因", result["answer"])
        self.assertIn(result["evidence"]["analysis_context"]["region_name"], result["answer"])

    def test_direct_explanation_question_preserves_scope_and_returns_reasoning(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            llm_client=FakeLLMClient(),
            router_model="gpt-4.1-mini",
            source_provider=RichFakeSourceProvider(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("为什么过去5个月徐州虫情这么高", thread_id="thread-why-direct")

        self.assertEqual(result["mode"], "analysis")
        self.assertIn("徐州市", result["answer"])
        self.assertIn("结论：当前判断，", result["answer"])
        self.assertIn("原因", result["answer"])
        self.assertNotIn("Top5地区", result["answer"])
        self.assertEqual(result["evidence"]["historical_query"]["query_type"], "pest_overview")
        self.assertEqual(result["evidence"]["historical_query"]["region_name"], "徐州市")
        self.assertEqual(result["evidence"]["analysis_context"]["region_name"], "徐州市")
        reason_section = result["answer"].split("原因：", 1)[1]
        self.assertIn("从数据看", reason_section)
        self.assertEqual(
            result["evidence"]["analysis_context"]["window"],
            {"window_type": "months", "window_value": 5},
        )

    def test_generic_explanation_question_returns_reason_and_followup_checks(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("从数据看，这次异常最可能的原因是什么？", thread_id="thread-generic-why")

        self.assertEqual(result["mode"], "advice")
        self.assertIn("原因", result["answer"])
        self.assertIn("依据", result["answer"])
        self.assertIn("待核查", result["answer"])

    def test_unknown_region_explanation_returns_mapping_reasoning(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("为什么会出现“未知区域”？", thread_id="thread-unknown-region")

        self.assertEqual(result["mode"], "advice")
        self.assertIn("原因", result["answer"])
        self.assertIn("未知区域", result["answer"])
        self.assertIn("待核查", result["answer"])

    def test_explanation_without_structured_evidence_reports_insufficient_evidence(self):
        agent = DocAIAgent(
            EmptyStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            source_provider=RichFakeSourceProvider(),
        )

        result = agent.answer("为什么过去5个月徐州虫情这么高", thread_id="thread-why-insufficient")

        self.assertEqual(result["mode"], "analysis")
        self.assertIn("证据不足", result["answer"])
        self.assertNotIn("峰值0", result["answer"])
        self.assertNotIn("最近值0", result["answer"])

    def test_mixed_reason_and_advice_emit_separate_sections(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            source_provider=RichFakeSourceProvider(),
        )

        result = agent.answer("过去5个月徐州虫情具体数据，解释为什么高，再给建议", thread_id="thread-mix-sections")

        self.assertEqual(result["mode"], "analysis")
        self.assertIn("原因：", result["answer"])
        self.assertIn("建议：", result["answer"])
        self.assertIn("\n\n原因：", result["answer"])
        self.assertIn("\n\n建议：", result["answer"])
        advice_section = result["answer"].split("建议：", 1)[1]
        self.assertIn("复核高值点位", advice_section)
        self.assertIn("分区处置", advice_section)

    def test_colloquial_reason_and_advice_variant_returns_expert_sections(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            source_provider=RichFakeSourceProvider(),
        )

        result = agent.answer("过去5个月徐州虫情为啥这么高，再说说怎么处理", thread_id="thread-colloquial-why")

        self.assertEqual(result["mode"], "analysis")
        self.assertIn("原因：", result["answer"])
        self.assertIn("建议：", result["answer"])
        self.assertEqual(result["evidence"]["analysis_context"]["region_name"], "徐州市")

    def test_colloquial_how_to_handle_variant_returns_advice(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            source_provider=RichFakeSourceProvider(),
        )

        result = agent.answer("过去5个月徐州虫情这么高，该咋办", thread_id="thread-colloquial-advice")

        self.assertIn("建议：", result["answer"])
        self.assertEqual(result["evidence"]["analysis_context"]["region_name"], "徐州市")

    def test_continue_to_worsen_variant_returns_forecast_section(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            source_provider=RichFakeSourceProvider(),
        )

        result = agent.answer("过去5个月徐州虫情这么高，未来会不会继续变严重", thread_id="thread-colloquial-forecast")

        self.assertEqual(result["mode"], "analysis")
        self.assertIn("预测：", result["answer"])
        self.assertEqual(result["evidence"]["analysis_context"]["region_name"], "徐州市")

    def test_high_risk_advice_uses_time_bound_follow_up_language(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            source_provider=RichFakeSourceProvider(),
        )

        result = agent.answer(
            "过去5个月徐州虫情具体数据，判断未来两周会不会更糟，再给建议",
            thread_id="thread-high-risk-advice",
        )

        self.assertEqual(result["mode"], "analysis")
        advice_section = result["answer"].split("建议：", 1)[1]
        self.assertIn("24-48 小时复查", advice_section)
        self.assertIn("优先盯住峰值附近区域", advice_section)

    def test_mixed_reasoning_references_observed_metrics(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            source_provider=RichFakeSourceProvider(),
        )

        result = agent.answer(
            "过去5个月徐州虫情具体数据，解释为什么高，再判断未来两周会不会更糟",
            thread_id="thread-mix-grounded",
        )

        self.assertEqual(result["mode"], "analysis")
        reason_section = result["answer"].split("原因：", 1)[1].split("预测：", 1)[0]
        self.assertIn("峰值86", reason_section)
        self.assertIn("最近值86", reason_section)
        self.assertIn("整体", reason_section)
        self.assertIn("未来两周", reason_section)
        self.assertIn("高值", reason_section)
        prediction_section = result["answer"].split("预测：", 1)[1].split("依据：", 1)[0]
        self.assertIn("样本覆盖", prediction_section)

    def test_explicit_no_advice_request_returns_data_only(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            source_provider=RichFakeSourceProvider(),
        )

        result = agent.answer("不要建议，先给我数据，徐州过去3个月墒情", thread_id="thread-no-advice")

        self.assertEqual(result["mode"], "data_query")
        self.assertNotIn("建议：", result["answer"])
        self.assertNotIn("知识依据：", result["answer"])
        self.assertIn("徐州市", result["answer"])

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
        self.assertEqual(result["evidence"]["request_understanding"]["followup_type"], "region_follow_up")
        self.assertEqual(
            result["evidence"]["memory_state"]["conversation_state"]["last_followup_type"],
            "region_follow_up",
        )
        self.assertEqual(result["evidence"]["analysis_context"]["region_name"], "南京市")
        self.assertIn("南京市", result["answer"])
        self.assertIn("未来两周", result["answer"])

    def test_domain_switch_follow_up_reuses_previous_scope(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        agent.answer("给我过去五个月徐州的虫害情况", thread_id="thread-domain-switch")
        result = agent.answer("换成墒情", thread_id="thread-domain-switch")

        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(result["evidence"]["analysis_context"]["domain"], "soil")
        self.assertEqual(result["evidence"]["analysis_context"]["region_name"], "徐州市")
        self.assertIn("徐州市", result["answer"])

    def test_historical_window_follow_up_reuses_previous_scope(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        agent.answer("给我过去五个月徐州的虫害情况", thread_id="thread-window-switch")
        result = agent.answer("那过去半年呢", thread_id="thread-window-switch")

        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(result["evidence"]["analysis_context"]["domain"], "pest")
        self.assertEqual(result["evidence"]["analysis_context"]["region_name"], "徐州市")
        self.assertEqual(result["evidence"]["historical_query"]["query_type"], "pest_overview")
        self.assertIn("徐州市", result["answer"])

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

    def test_domain_clarification_for_dataset_question_returns_detail_data(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        first = agent.answer("苏州进5个月的灾害数据", thread_id="thread-domain-dataset")
        result = agent.answer("虫情", thread_id="thread-domain-dataset")

        self.assertEqual(first["mode"], "advice")
        self.assertEqual(first["evidence"]["response_meta"]["fallback_reason"], "agri_domain_ambiguous")
        self.assertIn("planner", first["evidence"]["response_meta"]["source_types"])
        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(result["evidence"]["analysis_context"]["query_type"], "pest_detail")
        self.assertEqual(result["evidence"]["analysis_context"]["region_name"], "苏州市")
        self.assertIn("苏州市", result["answer"])
        self.assertIn("2026-03-28", result["answer"])

    def test_detail_follow_up_reuses_previous_region_scope(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        agent.answer("给我过去五个月苏州的虫害情况", thread_id="thread-detail-follow-up")
        result = agent.answer("我说的是虫情的具体数据", thread_id="thread-detail-follow-up")

        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(result["evidence"]["analysis_context"]["query_type"], "pest_detail")
        self.assertEqual(result["evidence"]["analysis_context"]["region_name"], "苏州市")
        self.assertIn("2026-03-28", result["answer"])
        self.assertNotIn("请补充要看的地区", result["answer"])

    def test_negated_trend_follow_up_switches_to_detail_data(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        agent.answer("苏州近5个月虫害走势怎么样", thread_id="thread-negated-trend")
        result = agent.answer("不是趋势，是具体数据啊", thread_id="thread-negated-trend")

        self.assertEqual(result["mode"], "data_query")
        self.assertEqual(result["evidence"]["analysis_context"]["query_type"], "pest_detail")
        self.assertEqual(result["evidence"]["analysis_context"]["region_name"], "苏州市")
        self.assertIn("2026-03-28", result["answer"])
        self.assertNotIn("请补充要看的地区", result["answer"])

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

    def test_global_pest_trend_question_no_longer_requires_region(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("过去5个月虫情总体是上升还是下降？", thread_id="thread-global-pest-trend")

        self.assertEqual(result["mode"], "data_query")
        self.assertNotIn("请补充要看的地区", result["answer"])
        self.assertIn("整体", result["answer"])
        self.assertEqual(result["evidence"]["historical_query"]["query_type"], "pest_trend")

    def test_global_soil_trend_question_no_longer_requires_region(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("近两个月墒情有没有缓解？", thread_id="thread-global-soil-trend")

        self.assertEqual(result["mode"], "data_query")
        self.assertNotIn("请补充要看的地区", result["answer"])
        self.assertIn("整体", result["answer"])
        self.assertEqual(result["evidence"]["historical_query"]["query_type"], "soil_trend")

    def test_alert_trend_question_returns_increase_or_decrease_without_region(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("最近30天预警数量是增加还是减少？", thread_id="thread-alert-trend")

        self.assertEqual(result["mode"], "data_query")
        self.assertNotIn("请补充", result["answer"])
        self.assertRegex(result["answer"], r"(增加|减少|上升|下降)")
        self.assertEqual(result["evidence"]["historical_query"]["query_type"], "alerts_trend")

    def test_county_advice_question_targets_county_not_city(self):
        agent = DocAIAgent(
            CountyRankingRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
            source_provider=RichFakeSourceProvider(),
        )

        result = agent.answer("对当前虫情最严重的县有什么建议？", thread_id="thread-county-advice")

        self.assertEqual(result["mode"], "analysis")
        self.assertEqual(result["evidence"]["historical_query"]["region_level"], "county")
        self.assertIn("铜山区", result["answer"])
        self.assertNotIn("常州市当前", result["answer"])

    def test_pronoun_county_question_without_context_asks_for_specific_object(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        result = agent.answer("为什么这个县的墒情异常最多？", thread_id="thread-pronoun-county")

        self.assertEqual(result["mode"], "advice")
        self.assertIn("请补充具体对象", result["answer"])

    def test_pronoun_county_follow_up_does_not_reuse_previous_city_context(self):
        agent = DocAIAgent(
            FakeStructuredRepo(),
            memory_store_path=os.path.join(self.td.name, "agent-memory.json"),
        )

        agent.answer("为什么最近虫情变严重了？", thread_id="thread-pronoun-follow-up")
        result = agent.answer("为什么这个县的墒情异常最多？", thread_id="thread-pronoun-follow-up")

        self.assertEqual(result["mode"], "advice")
        self.assertIn("请补充具体对象", result["answer"])
        self.assertNotIn("常州市", result["answer"])


if __name__ == "__main__":
    unittest.main()
