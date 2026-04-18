import json
import os
import tempfile
import unittest

from doc_ai_agent.agent import DocAIAgent
from doc_ai_agent.capabilities.forecast import ForecastCapability
from doc_ai_agent.request_understanding import RequestUnderstanding


FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "multiturn_human_score_cases.json")


class HumanScoreRegressionRepo:
    def __init__(self):
        self.last_abnormal_soil_devices_kwargs = {}

    def count_since(self, since):
        del since
        return 22

    def top_n(self, field, n, since):
        return self.top_n_filtered(field, n, since)

    def available_alert_time_range(self):
        return {
            "min_time": "2026-01-01 00:00:00",
            "max_time": "2026-04-10 00:00:00",
        }

    def top_n_filtered(self, field, n, since, until=None, city=None, level=None, min_alert_value=None):
        del since, until, city, level, min_alert_value
        if field == "county":
            return [
                {"name": "如东县", "count": 9},
                {"name": "溧阳市", "count": 7},
            ][:n]
        return [
            {"name": "常州市", "count": 12},
            {"name": "徐州市", "count": 10},
        ][:n]

    def sample_alerts(self, since, limit=3):
        del since
        return [{"alert_id": "A-1"}][:limit]

    def count_filtered(self, since, until=None, city=None, level=None):
        del since, until, city, level
        return 22

    def alerts_trend(self, since, until=None, city=None):
        del since, until
        if city == "常州市":
            return [
                {"date": "2026-03-20", "alert_count": 3},
                {"date": "2026-03-27", "alert_count": 5},
                {"date": "2026-04-03", "alert_count": 8},
            ]
        return [
            {"date": "2026-03-20", "alert_count": 6},
            {"date": "2026-03-27", "alert_count": 9},
            {"date": "2026-04-03", "alert_count": 12},
        ]

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

    def top_active_devices(self, since, until=None, limit=10, city=None, county=None):
        del since, until, city, county
        return [
            {
                "device_code": "SNS001",
                "device_name": "活跃设备1",
                "alert_count": 8,
                "active_days": 4,
                "last_alert_time": "2026-04-10 10:00:00",
            },
            {
                "device_code": "SNS002",
                "device_name": "活跃设备2",
                "alert_count": 7,
                "active_days": 3,
                "last_alert_time": "2026-04-09 10:00:00",
            },
            {
                "device_code": "SNS003",
                "device_name": "活跃设备3",
                "alert_count": 6,
                "active_days": 3,
                "last_alert_time": "2026-04-08 10:00:00",
            },
        ][:limit]

    def abnormal_soil_devices(self, since, until=None, city=None, county=None, limit=10, device_codes=None):
        self.last_abnormal_soil_devices_kwargs = {
            "since": since,
            "until": until,
            "city": city,
            "county": county,
            "limit": limit,
            "device_codes": list(device_codes or []),
        }
        rows = [
            {
                "device_sn": "SNS001",
                "device_name": "活跃设备1",
                "city_name": "南通市",
                "county_name": "如东县",
                "abnormal_count": 3,
                "last_sample_time": "2026-04-10 09:00:00",
            },
            {
                "device_sn": "SNS003",
                "device_name": "活跃设备3",
                "city_name": "常州市",
                "county_name": "新北区",
                "abnormal_count": 1,
                "last_sample_time": "2026-04-09 09:00:00",
            },
        ]
        allowed = set(device_codes or [])
        if allowed:
            rows = [row for row in rows if row["device_sn"] in allowed]
        return rows[:limit]


class HumanScoreRegressionSourceProvider:
    def search(self, question, limit=3, context=None):
        return [
            {
                "title": "虫情监测与绿色防控技术",
                "snippet": "加强监测预警，按阈值和区域分级响应。",
                "domain": "pest",
            }
        ][:limit]


class WeakEvidenceForecastService:
    def forecast_top_regions(self, domain, since, horizon_days, region_level="city", top_n=1, city=None, county=None, anomaly_direction=None):
        del since, anomaly_direction
        region_name = county or city or ("如东县" if region_level == "county" else "常州市")
        return {
            "answer": f"未来{horizon_days}天{region_name}{domain}风险一定会继续恶化。",
            "data": [{"region_name": region_name, "risk_level": "高"}][:top_n],
            "forecast": {
                "domain": domain,
                "mode": "ranking",
                "confidence": 0.18,
                "history_points": 3,
                "top_factors": ["样本覆盖 3 个观测日", "最近值仍高于窗口均值"],
                "risk_level": "高",
            },
            "analysis_context": {"domain": domain, "region_name": region_name, "region_level": region_level},
        }

    def forecast_region(self, route, context=None):
        del route, context
        return {
            "answer": "未来两周常州市虫情一定会继续恶化。",
            "data": [{"region_name": "常州市", "risk_level": "高"}],
            "forecast": {
                "domain": "pest",
                "mode": "region",
                "confidence": 0.18,
                "history_points": 3,
                "top_factors": ["样本覆盖 3 个观测日", "最近值仍高于窗口均值"],
                "risk_level": "高",
            },
            "analysis_context": {"domain": "pest", "region_name": "常州市", "region_level": "city"},
        }


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

    def test_joint_risk_region_refine_keeps_joint_risk_family_end_to_end(self):
        agent = self._agent()

        agent.answer("最近30天联合风险最高的是哪里？", thread_id="human-score-joint-risk")
        result = agent.answer("只看常州。", thread_id="human-score-joint-risk")

        self.assertIn("常州市", result["answer"])
        self.assertEqual(result["evidence"]["historical_query"]["query_type"], "joint_risk")
        self.assertEqual(result["evidence"]["historical_query"]["city"], "常州市")

    def test_group_17_weak_evidence_follow_up_uses_conservative_wording(self):
        agent = self._agent(memory_name="multiturn-human-weak-forecast.json")
        agent.forecast_capability = ForecastCapability(WeakEvidenceForecastService())

        agent.answer("未来10天哪些县风险最高？", thread_id="human-score-17")
        result = agent.answer("如果证据弱，你应该怎么回答？", thread_id="human-score-17")

        self.assertIn("待核查", result["answer"])
        self.assertIn("趋势判断", result["answer"])
        self.assertIn("样本覆盖", result["answer"])
        self.assertNotIn("一定会继续恶化", result["answer"])

    def test_group_17_evidence_sufficiency_follow_up_answers_directly(self):
        agent = self._agent(memory_name="multiturn-human-evidence-sufficiency.json")

        agent.answer("未来10天哪些县风险最高？", thread_id="human-score-17-evidence")
        result = agent.answer("你的证据够吗？", thread_id="human-score-17-evidence")

        self.assertIn("证据", result["answer"])
        self.assertIn("样本覆盖", result["answer"])
        self.assertIn("置信度", result["answer"])
        self.assertTrue("基本够" in result["answer"] or "偏弱" in result["answer"] or "不足" in result["answer"])
        self.assertNotIn("未来两周虫情风险最高", result["answer"])
        self.assertNotIn("台风", result["answer"])
        self.assertNotIn("处置建议", result["answer"])

    def test_group_19_active_device_follow_up_filters_soil_devices_and_reuses_list_for_7_days(self):
        agent = self._agent(memory_name="multiturn-human-active-device-soil.json")

        agent.answer("给我列出最近最活跃的10台设备。", thread_id="human-score-19")
        second = agent.answer("其中墒情设备有哪些？", thread_id="human-score-19")
        third = agent.answer("最近7天异常次数分别多少？", thread_id="human-score-19")

        self.assertEqual(second["mode"], "data_query")
        self.assertEqual(second["evidence"]["historical_query"]["query_type"], "soil_abnormal_devices")
        self.assertIn("SNS001", second["answer"])
        self.assertIn("SNS003", second["answer"])
        self.assertEqual(
            second["evidence"]["historical_query"]["device_codes"],
            ["SNS001", "SNS002", "SNS003"],
        )
        self.assertEqual(third["mode"], "data_query")
        self.assertEqual(third["evidence"]["historical_query"]["query_type"], "soil_abnormal_devices")
        self.assertEqual(third["evidence"]["historical_query"]["window"]["window_type"], "days")
        self.assertEqual(third["evidence"]["historical_query"]["window"]["window_value"], 7)
        self.assertEqual(
            third["evidence"]["historical_query"]["device_codes"],
            ["SNS001", "SNS003"],
        )
        self.assertIn("SNS001", third["answer"])

    def test_generic_metric_clarification_follow_up_uses_context_domain_instead_of_generic_intent(self):
        agent = self._agent(memory_name="multiturn-human-slot-clarify.json")

        first = agent.answer("最近30天最多的是哪里？", thread_id="human-score-slot-clarify")
        second = agent.answer("我说的是预警。", thread_id="human-score-slot-clarify")

        self.assertEqual(first["mode"], "advice")
        self.assertNotIn("数据统计，还是生成处置建议", first["answer"])
        self.assertEqual(second["mode"], "data_query")
        self.assertEqual(second["evidence"]["historical_query"]["query_type"], "alerts_top")
        self.assertNotIn("数据统计，还是生成处置建议", second["answer"])

    def test_scene_follow_up_keeps_soil_domain_and_avoids_generic_mixed_advice(self):
        agent = self._agent(memory_name="multiturn-human-scene-aware.json")

        agent.answer("过去30天常州墒情具体数据", thread_id="human-score-scene-aware")
        result = agent.answer("大棚地块该怎么处理？", thread_id="human-score-scene-aware")

        self.assertEqual(result["mode"], "advice")
        self.assertIn("大棚", result["answer"])
        self.assertTrue("补灌" in result["answer"] or "排水" in result["answer"])
        self.assertNotIn("成虫/幼虫", result["answer"])
        self.assertNotIn("天气过程", result["answer"])


if __name__ == "__main__":
    unittest.main()
