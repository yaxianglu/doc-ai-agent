import os
import tempfile
import unittest

from doc_ai_agent.agent import DocAIAgent
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

    def test_top_query(self):
        result = self.agent.answer("2026年以来top5的是哪几个市？")
        self.assertEqual(result["mode"], "data_query")
        self.assertTrue(len(result["data"]) >= 1)
        self.assertEqual(result["data"][0]["name"], "淮安市")

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
        self.assertEqual(len(result["data"]), 1)
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


if __name__ == "__main__":
    unittest.main()
