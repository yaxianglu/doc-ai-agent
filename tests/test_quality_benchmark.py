import os
import tempfile
import unittest

from doc_ai_agent.agent import DocAIAgent
from doc_ai_agent.query_planner import QueryPlanner
from doc_ai_agent.request_understanding import RequestUnderstanding

from tests.test_agent import FakeStructuredRepo


UNDERSTANDING_CASES = [
    ("给我过去五个月徐州的虫害情况", {"domain": "pest", "region_name": "徐州市", "task_type": "region_overview", "window_type": "months", "window_value": 5}),
    ("苏州进5个月的虫害数据", {"domain": "pest", "region_name": "苏州市", "task_type": "data_detail", "window_type": "months", "window_value": 5}),
    ("南京近三周虫害走势怎么样", {"domain": "pest", "region_name": "南京市", "task_type": "trend", "window_type": "weeks", "window_value": 3}),
    ("过去90天哪些地方同时出现高虫情和低墒情", {"domain": "mixed", "task_type": "joint_risk", "window_type": "days", "window_value": 90}),
    ("近两个月哪些地方虫情高而且缺水更明显", {"domain": "mixed", "task_type": "joint_risk", "window_type": "months", "window_value": 2}),
    ("徐州未来两周虫害会怎样", {"domain": "pest", "region_name": "徐州市", "window_type": "all"}),
    ("过去5个月墒情最严重的地方是哪里", {"domain": "soil", "task_type": "ranking", "window_type": "months", "window_value": 5}),
    ("麻烦你帮我看一下过去五个月徐州这边的虫害整体情况怎么样", {"domain": "pest", "region_name": "徐州市", "task_type": "region_overview", "window_type": "months", "window_value": 5}),
]

PLANNER_CASES = [
    ("近3个星期虫情最严重的地方是哪里", {"intent": "data_query", "query_type": "pest_top", "window_type": "weeks", "window_value": 3}),
    ("给我过去五个月徐州市的虫害情况", {"intent": "data_query", "query_type": "pest_overview", "window_type": "months", "window_value": 5}),
    ("给我过去五个月徐州市的虫害数据", {"intent": "data_query", "query_type": "pest_detail", "window_type": "months", "window_value": 5}),
    ("苏州市近5个月的灾害数据", {"intent": "advice", "reason": "agri_domain_ambiguous", "window_type": "months", "window_value": 5}),
    ("设备SNS00204659最近一次预警时间是什么", {"intent": "data_query", "query_type": "latest_device"}),
    ("2026年4月9日告警值超过150的预警主要在哪些城市", {"intent": "data_query", "query_type": "threshold_summary"}),
]

CITIES = ["南京", "无锡", "徐州", "常州", "苏州", "南通", "连云港", "淮安", "盐城", "扬州", "镇江", "泰州", "宿迁"]
DOMAIN_CASES = [
    ("虫情", "虫害", "pest_detail"),
    ("墒情", "墒情", "soil_detail"),
]


class QualityBenchmarkTests(unittest.TestCase):
    def test_understanding_benchmark(self):
        understanding = RequestUnderstanding()

        for question, expected in UNDERSTANDING_CASES:
            with self.subTest(question=question):
                result = understanding.analyze(question)
                self.assertEqual(result["domain"], expected["domain"])
                if "region_name" in expected:
                    self.assertEqual(result["region_name"], expected["region_name"])
                if "task_type" in expected:
                    self.assertEqual(result["task_type"], expected["task_type"])
                self.assertEqual(result["window"]["window_type"], expected["window_type"])
                if "window_value" in expected:
                    self.assertEqual(result["window"]["window_value"], expected["window_value"])

    def test_planner_benchmark(self):
        planner = QueryPlanner(None)

        for question, expected in PLANNER_CASES:
            with self.subTest(question=question):
                plan = planner.plan(question)
                self.assertEqual(plan["intent"], expected["intent"])
                if "query_type" in expected:
                    self.assertEqual(plan["route"]["query_type"], expected["query_type"])
                if "reason" in expected:
                    self.assertEqual(plan["reason"], expected["reason"])
                if "window_type" in expected:
                    self.assertEqual(plan["route"]["window"]["window_type"], expected["window_type"])
                if "window_value" in expected:
                    self.assertEqual(plan["route"]["window"]["window_value"], expected["window_value"])

    def test_follow_up_benchmark(self):
        with tempfile.TemporaryDirectory() as td:
            agent = DocAIAgent(
                FakeStructuredRepo(),
                memory_store_path=os.path.join(td, "agent-memory.json"),
            )

            cases = [
                (["过去5个月灾害最严重的地方是哪里", "虫情"], "徐州市"),
                (["给我过去五个月徐州的虫害情况", "换成墒情"], "徐州市"),
                (["给我过去五个月徐州的虫害情况", "那过去半年呢"], "徐州市"),
                (["近3个星期，受灾最严重的地方是哪里", "虫情", "未来两周会怎样", "南京呢"], "南京市"),
            ]

            for idx, (turns, expected_region) in enumerate(cases, start=1):
                with self.subTest(turns=turns):
                    thread_id = f"benchmark-thread-{idx}"
                    result = None
                    for turn in turns:
                        result = agent.answer(turn, thread_id=thread_id)
                    assert result is not None
                    self.assertEqual(result["evidence"]["analysis_context"]["region_name"], expected_region)
                    self.assertTrue(bool(result["answer"]))

    def test_dialogue_regression_200_turns(self):
        total_turns = 0
        with tempfile.TemporaryDirectory() as td:
            agent = DocAIAgent(
                FakeStructuredRepo(),
                memory_store_path=os.path.join(td, "agent-memory.json"),
            )

            scenario_index = 0
            for city in CITIES:
                expected_city = f"{city}市"
                for domain_label, domain_noun, expected_query_type in DOMAIN_CASES:
                    scenarios = [
                        ([f"{city}进5个月的灾害数据", domain_label], expected_query_type),
                        ([f"给我过去五个月{city}的{domain_noun}情况", "我说的是具体数据"], expected_query_type),
                        ([f"{city}近5个月{domain_noun}走势怎么样", "不是趋势，是具体数据啊"], expected_query_type),
                        ([f"{city}过去五个月的{domain_noun}数据", "那过去半年呢"], expected_query_type),
                    ]
                    for turns, query_type in scenarios:
                        scenario_index += 1
                        thread_id = f"dialogue-benchmark-{scenario_index}"
                        result = None
                        for turn in turns:
                            total_turns += 1
                            result = agent.answer(turn, thread_id=thread_id)
                        assert result is not None
                        with self.subTest(city=city, domain=domain_label, turns=turns):
                            self.assertEqual(result["mode"], "data_query")
                            self.assertEqual(result["evidence"]["analysis_context"]["region_name"], expected_city)
                            self.assertEqual(result["evidence"]["analysis_context"]["query_type"], query_type)
                            self.assertNotIn("请补充要看的地区", result["answer"])
                            self.assertTrue(
                                "2026-03-28" in result["answer"] or expected_city in result["answer"],
                                msg=result["answer"],
                            )

        self.assertGreaterEqual(total_turns, 200)


if __name__ == "__main__":
    unittest.main()
