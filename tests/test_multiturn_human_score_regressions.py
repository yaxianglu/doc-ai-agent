import json
import os
import tempfile
import unittest

from doc_ai_agent.agent import DocAIAgent
from doc_ai_agent.request_understanding import RequestUnderstanding


FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "multiturn_human_score_cases.json")


class HumanScoreRegressionRepo:
    def top_pest_regions(self, since, until, region_level="city", top_n=5, city=None, county=None):
        city_rows = [
            {"region_name": "常州市", "severity_score": 120, "record_count": 16, "active_days": 7},
            {"region_name": "徐州市", "severity_score": 92, "record_count": 14, "active_days": 6},
        ]
        county_rows = [
            {"region_name": "溧阳市", "severity_score": 48, "record_count": 7, "active_days": 4},
            {"region_name": "金坛区", "severity_score": 36, "record_count": 5, "active_days": 3},
        ]
        if region_level == "county":
            if city == "常州市":
                return county_rows[:top_n]
            if city == "徐州市":
                return [
                    {"region_name": "沛县", "severity_score": 41, "record_count": 6, "active_days": 4},
                    {"region_name": "邳州市", "severity_score": 29, "record_count": 4, "active_days": 3},
                ][:top_n]
            return (county_rows + [{"region_name": "沛县", "severity_score": 41, "record_count": 6, "active_days": 4}])[:top_n]
        if city:
            return [row for row in city_rows if row["region_name"] == city][:top_n]
        return city_rows[:top_n]

    def pest_trend(self, since, until, region_name, region_level="city"):
        if region_name in {"常州市", "溧阳市", "金坛区"}:
            return [
                {"date": "2026-03-20", "severity_score": 16},
                {"date": "2026-03-27", "severity_score": 24},
                {"date": "2026-04-03", "severity_score": 33},
            ]
        return [
            {"date": "2026-03-20", "severity_score": 20},
            {"date": "2026-03-27", "severity_score": 19},
            {"date": "2026-04-03", "severity_score": 18},
        ]

    def sample_pest_records(self, since, until, limit=3):
        return [
            {
                "city_name": "常州市",
                "county_name": "溧阳市",
                "normalized_pest_count": 12,
                "monitor_time": "2026-04-03 08:00:00",
            }
        ][:limit]

    def joint_risk_regions(self, since, until, region_level="city", top_n=5, city=None, county=None):
        rows = [
            {"region_name": "常州市", "joint_score": 118, "pest_score": 80, "low_soil_score": 38},
            {"region_name": "徐州市", "joint_score": 102, "pest_score": 71, "low_soil_score": 31},
        ]
        if city:
            rows = [row for row in rows if row["region_name"] == city]
        return rows[:top_n]


class HumanScoreRegressionSourceProvider:
    def search(self, question, limit=3, context=None):
        return [
            {
                "title": "虫情监测与绿色防控技术",
                "snippet": "加强监测预警，按阈值和区域分级响应。",
                "domain": "pest",
            }
        ][:limit]


class MultiTurnHumanScoreRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def _agent(self, *, memory_name="multiturn-human.json") -> DocAIAgent:
        return DocAIAgent(
            HumanScoreRegressionRepo(),
            memory_store_path=os.path.join(self.tempdir.name, memory_name),
            source_provider=HumanScoreRegressionSourceProvider(),
        )

    def test_fixture_contains_critical_multiturn_groups(self):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)

        self.assertEqual(payload["source"], "cw-评分表.xlsx / 多轮 / critical subset")
        self.assertEqual({item["group_id"] for item in payload["groups"]}, {"01", "03", "17", "19"})

    def test_fixture_followup_samples_emit_refine_subtypes(self):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            payload = {item["group_id"]: item for item in json.load(handle)["groups"]}

        understanding = RequestUnderstanding()
        context = {
            "domain": "pest",
            "region_name": "常州市",
            "route": {"query_type": "pest_top", "region_level": "county", "city": "常州市"},
            "conversation_state": {"last_query_family": "ranking", "last_region_level": "county"},
            "answer_form": "rank",
        }

        domain_turn = understanding.analyze(payload["01"]["turns"][1]["user_input"], context=context)
        granularity_turn = understanding.analyze(payload["01"]["turns"][2]["user_input"], context=context)
        region_turn = understanding.analyze(payload["03"]["turns"][2]["user_input"], context=context)

        self.assertEqual(domain_turn["followup_subtype"], "domain_refine")
        self.assertEqual(granularity_turn["followup_subtype"], "granularity_refine")
        self.assertEqual(region_turn["followup_subtype"], "region_refine")

    def test_memory_policy_exposes_extended_slot_inheritance_for_region_refine(self):
        understanding = RequestUnderstanding()

        result = understanding.analyze(
            "只看常州市。",
            context={
                "domain": "pest",
                "region_name": "常州市",
                "route": {
                    "query_type": "pest_top",
                    "region_level": "county",
                    "city": "常州市",
                },
                "device_code": "SNS00204659",
                "answer_form": "rank",
                "conversation_state": {
                    "last_query_family": "ranking",
                    "last_region_level": "county",
                    "last_answer_form": "rank",
                },
            },
        )

        self.assertEqual(result["memory_policy"]["inheritance_decision"], "allow")
        self.assertIn("query_family", result["memory_policy"]["inherited_slots"])
        self.assertIn("region_level", result["memory_policy"]["inherited_slots"])
        self.assertIn("answer_form", result["memory_policy"]["inherited_slots"])
        self.assertIn("referent", result["memory_policy"]["inherited_slots"])

    def test_group_03_region_refine_keeps_county_scope(self):
        agent = self._agent()

        agent.answer("最近30天风险最高的是哪里？", thread_id="human-score-03")
        agent.answer("按县，不要按市。", thread_id="human-score-03")
        result = agent.answer("只看常州市。", thread_id="human-score-03")

        self.assertIn("溧阳市", result["answer"])
        self.assertIn("金坛区", result["answer"])
        self.assertEqual(result["evidence"]["historical_query"]["region_level"], "county")
        self.assertEqual(result["evidence"]["historical_query"]["city"], "常州市")


if __name__ == "__main__":
    unittest.main()
