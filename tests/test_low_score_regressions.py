import os
import tempfile
import unittest

from doc_ai_agent.agent import DocAIAgent


class RegressionStructuredRepo:
    def top_pest_regions(self, since, until, region_level="city", top_n=5, city=None, county=None):
        if region_level == "county" and city == "常州市":
            return [
                {
                    "region_name": "溧阳市",
                    "severity_score": 12,
                    "record_count": 6,
                    "active_days": 4,
                },
                {
                    "region_name": "金坛区",
                    "severity_score": 9,
                    "record_count": 5,
                    "active_days": 3,
                },
            ][:top_n]
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
                "city_name": "常州市",
                "county_name": "溧阳市",
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

    def joint_risk_regions(self, since, until, region_level="city", top_n=5, city=None, county=None):
        rows = [
            {"region_name": "宿迁市", "joint_score": 166, "pest_score": 98, "low_soil_score": 68},
            {"region_name": "徐州市", "joint_score": 156, "pest_score": 92, "low_soil_score": 64},
            {"region_name": "淮安市", "joint_score": 128, "pest_score": 75, "low_soil_score": 53},
        ]
        if city:
            rows = [row for row in rows if row["region_name"] == city]
        if county:
            rows = [row for row in rows if row["region_name"] == county]
        return rows[:top_n]

    def alerts_trend(self, since, until=None, city=None):
        if city == "常州市":
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


class RegressionSourceProvider:
    def search(self, question, limit=3, context=None):
        return [
            {
                "title": "虫情监测与绿色防控技术",
                "url": "https://example.gov/pest",
                "published_at": "2026-02-14",
                "snippet": "针对迁飞性害虫应加强监测预警，按阈值采取分区防控措施。",
                "domain": "pest",
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
                "retrieval_engine": "qdrant",
                "retrieval_backend": "qdrant",
                "retrieval_strategy": "semantic-vector",
            },
        ][:limit]


class LowScoreRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def _agent(self, *, memory_name="agent-memory.json") -> DocAIAgent:
        return DocAIAgent(
            RegressionStructuredRepo(),
            memory_store_path=os.path.join(self.tempdir.name, memory_name),
            source_provider=RegressionSourceProvider(),
        )

    @staticmethod
    def _first_line(text: str) -> str:
        return next((line.strip() for line in str(text).splitlines() if line.strip()), "")

    def test_boolean_question_answer_starts_with_boolean_judgment(self):
        result = self._agent().answer("近两个月墒情有没有缓解？", thread_id="reg-boolean")

        first_line = self._first_line(result["answer"])
        self.assertRegex(first_line, r"^(有缓解迹象|暂未缓解|暂无明显缓解|暂无法判断|是|否)")
        self.assertNotIn("墒情趋势：", first_line)

    def test_trend_question_answer_starts_with_direction(self):
        result = self._agent().answer("过去5个月虫情总体是上升还是下降？", thread_id="reg-trend")

        first_line = self._first_line(result["answer"])
        self.assertRegex(first_line, r"^(上升|下降|持平|波动平稳)")
        self.assertNotIn("虫情趋势：", first_line)

    def test_joint_risk_boolean_question_uses_region_scope_and_yes_no_opening(self):
        result = self._agent().answer("过去90天，宿迁同时出现高虫情和低墒情吗？", thread_id="reg-joint-risk-boolean")

        first_line = self._first_line(result["answer"])
        self.assertRegex(first_line, r"^(是|否|暂无法判断)")
        self.assertIn("宿迁市", result["answer"])
        self.assertNotIn("1.", first_line)

    def test_county_question_answers_county_rows_instead_of_city_fallback(self):
        result = self._agent().answer("常州市下面虫情最严重的县有哪些？", thread_id="reg-county")

        self.assertIn("溧阳市", result["answer"])
        self.assertIn("金坛区", result["answer"])
        self.assertNotIn("请让我按县一级重新返回结果", result["answer"])
        self.assertEqual(result["evidence"]["historical_query"]["region_level"], "county")
        self.assertEqual(result["evidence"]["historical_query"]["city"], "常州市")

    def test_multi_turn_carry_over_keeps_trend_contract(self):
        agent = self._agent(memory_name="reg-multi.json")

        agent.answer("过去5个月虫情总体是上升还是下降？", thread_id="reg-multi")
        second = agent.answer("常州呢？", thread_id="reg-multi")
        third = agent.answer("苏州呢？", thread_id="reg-multi")

        self.assertRegex(self._first_line(second["answer"]), r"^(上升|下降|持平|波动平稳)")
        self.assertRegex(self._first_line(third["answer"]), r"^(上升|下降|持平|波动平稳)")
        self.assertIn("常州市", second["answer"])
        self.assertIn("苏州市", third["answer"])

    def test_composite_question_contains_rank_reason_and_advice_sections(self):
        result = self._agent().answer(
            "先给我过去5个月虫情最严重的县，再解释原因，再给建议",
            thread_id="reg-composite",
        )

        self.assertEqual(result["mode"], "analysis")
        self.assertRegex(result["answer"], r"\d+\.")
        self.assertIn("原因", result["answer"])
        self.assertIn("建议", result["answer"])


if __name__ == "__main__":
    unittest.main()
