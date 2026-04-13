import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from doc_ai_agent.config import AppConfig
from doc_ai_agent.server import build_app


class QuestionSuiteTests(unittest.TestCase):
    @staticmethod
    def _acceptance_artifact_candidates() -> list[Path]:
        repo_root = Path(__file__).resolve().parents[1]
        direct = repo_root / "output" / "acceptance_run_after_data_refresh.json"
        candidates = [direct]
        try:
            proc = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=True,
            )
        except Exception:
            return candidates
        for line in proc.stdout.splitlines():
            if not line.startswith("worktree "):
                continue
            worktree_path = Path(line.split(" ", 1)[1].strip())
            artifact = worktree_path / "output" / "acceptance_run_after_data_refresh.json"
            if artifact not in candidates:
                candidates.append(artifact)
        return candidates

    @classmethod
    def _load_acceptance_baseline(cls) -> dict[int, dict]:
        for candidate in cls._acceptance_artifact_candidates():
            if candidate.exists():
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                return {int(item["index"]): item for item in payload}
        raise unittest.SkipTest("acceptance_run_after_data_refresh.json not available in any repo worktree")

    def test_recommended_questions(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        with tempfile.TemporaryDirectory() as td:
            cfg = AppConfig(
                data_dir=repo_root,
                db_path=os.path.join(td, "alerts.db"),
                refresh_interval_minutes=5,
                port=0,
                openai_api_key="",
                openai_base_url="https://api.openai.com/v1",
                openai_router_model="gpt-4.1-mini",
                openai_advice_model="gpt-4.1",
                openai_timeout_seconds=30,
            )
            app = build_app(cfg)
            inserted = app.refresh()
            self.assertGreater(inserted, 0)

            data_questions = [
                "2025年12月24日全省一共发生了多少条预警？",
                "2025年12月24日涝渍等级预警有多少条？",
                "2025年12月24日重旱等级预警有多少条？",
                "徐州市在2025年12月24日发生了多少条预警？",
                "2025年12月24日各城市预警数量 Top5 是哪些？",
                "2025年12月24日哪个区县预警最多？",
                "告警值最高的10条记录分别是什么（时间、设备、地区、告警值）？",
                "告警值超过150的预警有多少条？主要集中在哪些城市？",
                "设备SNS00204659最近一次预警时间、等级、处置建议是什么？",
                "昆山市花桥镇这条预警的处置建议是什么？",
                "沛县相关预警里，哪些记录sms_content为空？",
                "相同设备在连续两天都触发预警的有哪些？",
                "按告警等级分组，平均告警值分别是多少？",
                "土壤墒情仪类型预警中，墒情预警子类型占比多少？",
                "2025年12月23日到12月24日，徐州市预警数量变化了多少？",
            ]

            for question in data_questions:
                result = app.chat(question)
                self.assertEqual(result["mode"], "data_query", msg=question)
                self.assertTrue(bool(result["answer"]), msg=question)
                self.assertNotEqual(result["answer"], "自1970-01-01以来，预警信息共 1288 条。", msg=question)

            advice_questions = [
                "针对涝渍预警，给出一份可执行的24小时处置清单。",
                "对重旱地块，按大田/设施大棚/林果分别给建议。",
                "如果同一设备连续两天涝渍，优先排查哪些问题？",
                "对告警值异常高（如>160）的地块，先排水还是先停灌？给出判断依据。",
                "请把处置建议改写成面向农户的短信版本（80字内）。",
            ]

            for question in advice_questions:
                result = app.chat(question)
                self.assertIn(result["mode"], {"advice", "data_query"}, msg=question)
                self.assertTrue(bool(result["answer"]), msg=question)

            meaningless_questions = [
                "哈哈哈哈",
                "123456",
                "今天天气真不错所以呢",
                "这个那个然后呢",
                "给我来点神秘力量",
            ]

            for question in meaningless_questions:
                result = app.chat(question)
                # 无意义问题的目标是“稳健响应”，而不是特定业务准确率。
                self.assertIn(result["mode"], {"advice", "data_query"}, msg=question)
                self.assertTrue(bool(result["answer"]), msg=question)

    def test_acceptance_timeout_cases_are_now_answered(self):
        results = self._load_acceptance_baseline()
        for index in (4, 5, 6):
            item = results[index]
            self.assertTrue(item["ok"], msg=index)
            self.assertIn(item.get("mode"), {"data_query", "analysis"}, msg=index)
            self.assertTrue(bool(item.get("answer")), msg=index)
            self.assertLess(float(item["seconds"] or 0), 60.0, msg=index)

    def test_acceptance_county_scope_and_time_parse_issues_are_fixed(self):
        results = self._load_acceptance_baseline()

        county_under_city = results[7]
        self.assertEqual(
            county_under_city["evidence"]["request_understanding"]["region_level"],
            "county",
        )
        self.assertNotIn("1970-01-01", county_under_city["answer"])

        soil_county_ranking = results[8]
        self.assertEqual(
            soil_county_ranking["evidence"]["analysis_context"]["region_level"],
            "county",
        )
        self.assertEqual(
            soil_county_ranking["evidence"]["historical_query"]["city"],
            "苏州市",
        )

        city_then_county = results[10]
        self.assertEqual(city_then_county["evidence"]["request_understanding"]["region_name"], "")
        self.assertEqual(
            city_then_county["evidence"]["analysis_context"]["region_level"],
            "county",
        )

        forecast_county = results[24]
        self.assertEqual(forecast_county["evidence"]["request_understanding"]["region_name"], "")
        self.assertEqual(
            forecast_county["evidence"]["request_understanding"]["region_level"],
            "county",
        )
        self.assertNotIn("常州市未来10天", forecast_county["answer"])

    def test_acceptance_placeholder_queries_now_clarify_or_route_correctly(self):
        results = self._load_acceptance_baseline()

        unknown_device = results[37]
        self.assertIn("请补充具体对象", unknown_device["answer"])
        self.assertEqual(unknown_device["evidence"]["generation_mode"], "clarification")

        unknown_county = results[39]
        self.assertIn("请补充具体对象", unknown_county["answer"])
        self.assertEqual(unknown_county["evidence"]["generation_mode"], "clarification")

        top_devices = results[40]
        self.assertEqual(
            top_devices["evidence"]["analysis_context"]["query_type"],
            "active_devices",
        )
        self.assertIn("最活跃的Top", top_devices["answer"])

    def test_acceptance_unknown_region_and_empty_field_queries_route_correctly(self):
        results = self._load_acceptance_baseline()

        unknown_region = results[42]
        self.assertEqual(
            unknown_region["evidence"]["analysis_context"]["query_type"],
            "unknown_region_devices",
        )
        self.assertIn("未知区域", unknown_region["answer"])

        county_empty = results[43]
        self.assertEqual(
            county_empty["evidence"]["analysis_context"]["query_type"],
            "empty_county_records",
        )
        self.assertIn("县字段为空", county_empty["answer"])

        unmatched_region = results[44]
        self.assertEqual(
            unmatched_region["evidence"]["analysis_context"]["query_type"],
            "unmatched_region_records",
        )
        self.assertIn("未匹配到区域", unmatched_region["answer"])


if __name__ == "__main__":
    unittest.main()
