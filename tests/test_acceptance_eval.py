import json
import importlib.util
import tempfile
import unittest
from pathlib import Path

from doc_ai_agent.acceptance_eval import compare_scored_runs, load_question_bank, score_run


class AcceptanceEvalTests(unittest.TestCase):
    @staticmethod
    def _load_script_module(name: str, relative_path: str):
        path = Path(__file__).resolve().parents[1] / relative_path
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_load_question_bank_reads_fixed_140_cases(self):
        question_bank = load_question_bank(
            Path(__file__).resolve().parents[1] / "evals" / "strict_acceptance_140.json"
        )

        self.assertEqual(len(question_bank), 140)
        self.assertEqual(question_bank[0]["index"], 1)
        self.assertEqual(question_bank[-1]["index"], 140)
        self.assertIn("turns", question_bank[-1])
        self.assertTrue(question_bank[-1]["turns"])

    def test_score_run_penalizes_alert_misroute_and_rewards_grounded_forecast(self):
        raw = [
            {
                "index": 3,
                "category": "基础查询",
                "question": "最近30天预警最多的是哪些地区？",
                "ok": True,
                "mode": "data_query",
                "seconds": 1.2,
                "answer": "从2026-03-15起，墒情异常最多的地区为：1.淮安市。",
            },
            {
                "index": 21,
                "category": "预测能力",
                "question": "未来两周虫情会怎样？",
                "ok": True,
                "mode": "data_query",
                "seconds": 0.8,
                "answer": "未来两周虫情风险预计为高（置信度0.62，样本覆盖 12 个观测日）。依据：最近值仍高于窗口均值、预测结果仍接近历史高位。",
            },
        ]

        scored = score_run(raw)

        by_index = {item["index"]: item for item in scored["items"]}
        self.assertLess(by_index[3]["score"], 7.0)
        self.assertGreaterEqual(by_index[21]["score"], 8.5)
        self.assertIn("alert_domain_mismatch", by_index[3]["checks_failed"])
        self.assertEqual(scored["summary"]["count"], 2)

    def test_score_run_accepts_placeholder_clarification_and_domain_clarification(self):
        raw = [
            {
                "index": 27,
                "category": "原因解释",
                "question": "为什么这个县的墒情异常最多？",
                "ok": True,
                "mode": "advice",
                "seconds": 0.1,
                "answer": "请补充具体对象，比如县名、区名或设备编码，我再继续分析。",
            },
            {
                "index": 46,
                "category": "多轮上下文",
                "question": "过去5个月最严重的是哪里？",
                "ok": True,
                "mode": "advice",
                "seconds": 0.1,
                "answer": "你想看虫情还是墒情？比如可以问：近3个星期虫情最严重的地方是哪里。",
            },
            {
                "index": 124,
                "category": "多轮上下文",
                "question": "未来两周会怎样？",
                "ok": True,
                "mode": "advice",
                "seconds": 0.1,
                "answer": "你想看虫情还是墒情？比如可以问：未来两周虫情会怎样，或者未来两周墒情会怎样。",
            },
            {
                "index": 129,
                "category": "多轮上下文",
                "question": "最近30天最多的是哪里？",
                "ok": True,
                "mode": "advice",
                "seconds": 0.1,
                "answer": "你想看虫情、墒情还是预警？比如可以问：最近30天预警最多的是哪里，或者最近30天虫情最严重的是哪里。",
            },
        ]

        scored = score_run(raw)
        by_index = {item["index"]: item for item in scored["items"]}
        self.assertGreaterEqual(by_index[27]["score"], 8.5)
        self.assertNotIn("misrouted_to_advice", by_index[27]["checks_failed"])
        self.assertGreaterEqual(by_index[46]["score"], 8.5)
        self.assertGreaterEqual(by_index[124]["score"], 8.5)
        self.assertNotIn("forecast_missing_confidence", by_index[124]["checks_failed"])
        self.assertGreaterEqual(by_index[129]["score"], 8.5)
        self.assertNotIn("misrouted_to_advice", by_index[129]["checks_failed"])

    def test_compare_scored_runs_reports_regressions_and_improvements(self):
        previous = {
            "summary": {"average_score": 7.0},
            "items": [
                {"index": 3, "score": 5.0, "question": "最近30天预警最多的是哪些地区？"},
                {"index": 21, "score": 6.0, "question": "未来两周虫情会怎样？"},
            ],
        }
        current = {
            "summary": {"average_score": 7.8},
            "items": [
                {"index": 3, "score": 7.5, "question": "最近30天预警最多的是哪些地区？"},
                {"index": 21, "score": 5.5, "question": "未来两周虫情会怎样？"},
            ],
        }

        comparison = compare_scored_runs(current=current, baseline=previous)

        self.assertEqual(comparison["summary"]["average_delta"], 0.8)
        self.assertEqual(comparison["improved"][0]["index"], 3)
        self.assertEqual(comparison["regressed"][0]["index"], 21)

    def test_score_run_can_be_written_as_json_fixture(self):
        raw = [
            {
                "index": 26,
                "category": "原因解释",
                "question": "为什么最近虫情变严重了？",
                "ok": True,
                "mode": "analysis",
                "seconds": 2.0,
                "answer": "结论：当前判断，整体虫情上升。原因：从数据看，峰值86，最近值80。待核查项包括监测点位和阈值口径。依据：参考 虫情监测与绿色防控技术。",
            }
        ]

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "scored.json"
            target.write_text(json.dumps(score_run(raw), ensure_ascii=False, indent=2), encoding="utf-8")
            loaded = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(loaded["summary"]["count"], 1)
        self.assertEqual(loaded["items"][0]["index"], 26)

    def test_score_run_rewards_boundary_guard_and_penalizes_agri_hijack(self):
        raw = [
            {
                "index": 51,
                "category": "边界能力",
                "question": "浙江天气",
                "ok": True,
                "mode": "advice",
                "seconds": 0.3,
                "answer": "我目前主要支持农业虫情、墒情、预警数据分析，暂不直接提供天气查询。你如果要看农情，我可以继续帮你查浙江相关风险。",
            },
            {
                "index": 54,
                "category": "边界能力",
                "question": "上海天气预报",
                "ok": True,
                "mode": "data_query",
                "seconds": 0.5,
                "answer": "从2026-03-14起，墒情异常最多的地区为：1.淮安市。",
            },
            {
                "index": 58,
                "category": "边界能力",
                "question": "你是谁？",
                "ok": True,
                "mode": "advice",
                "seconds": 0.1,
                "answer": "我是 AI农情工作台 助手，可以基于虫情、墒情历史数据做问答、趋势分析、预测判断，并给出处置建议。",
            },
        ]

        scored = score_run(raw)
        by_index = {item["index"]: item for item in scored["items"]}
        self.assertGreaterEqual(by_index[51]["score"], 8.5)
        self.assertLessEqual(by_index[54]["score"], 3.0)
        self.assertIn("boundary_hijacked_by_agri", by_index[54]["checks_failed"])
        self.assertGreaterEqual(by_index[58]["score"], 8.5)

    def test_score_run_reports_subsuite_scores(self):
        raw = [
            {
                "index": 21,
                "category": "预测能力",
                "question": "未来两周虫情会怎样？",
                "ok": True,
                "mode": "data_query",
                "seconds": 0.8,
                "answer": "未来两周虫情风险预计为高（置信度0.62，样本覆盖 12 个观测日）。依据：最近值仍高于窗口均值、预测结果仍接近历史高位。",
            },
            {
                "index": 26,
                "category": "原因解释",
                "question": "为什么最近虫情变严重了？",
                "ok": True,
                "mode": "analysis",
                "seconds": 2.0,
                "answer": "结论：当前判断，整体虫情上升。原因：从数据看，峰值86，最近值80。待核查项包括监测点位和阈值口径。依据：参考 虫情监测与绿色防控技术。",
            },
            {
                "index": 47,
                "category": "多轮上下文",
                "question": "其中虫情的呢？",
                "ok": True,
                "mode": "data_query",
                "seconds": 0.2,
                "answer": "过去5个月虫情最严重的县包括铜山区、睢宁县。",
            },
            {
                "index": 51,
                "category": "边界能力",
                "question": "浙江天气",
                "ok": True,
                "mode": "advice",
                "seconds": 0.3,
                "answer": "我目前主要支持农业虫情、墒情、预警数据分析，暂不直接提供天气查询。你如果要看农情，我可以继续帮你查浙江相关风险。",
            },
        ]

        scored = score_run(raw)

        suite_scores = scored["summary"]["suite_scores"]
        self.assertIn("forecast", suite_scores)
        self.assertIn("explanation", suite_scores)
        self.assertIn("context", suite_scores)
        self.assertIn("ood", suite_scores)
        self.assertGreaterEqual(suite_scores["forecast"], 8.0)
        self.assertGreaterEqual(suite_scores["ood"], 8.5)

    def test_transformer_hard_case_banks_are_expanded(self):
        root = Path(__file__).resolve().parents[1] / "evals"

        self.assertEqual(len(load_question_bank(root / "ood_eval.json")), 15)
        self.assertEqual(len(load_question_bank(root / "explanation_eval.json")), 10)
        self.assertEqual(len(load_question_bank(root / "forecast_eval.json")), 10)
        self.assertEqual(len(load_question_bank(root / "context_eval.json")), 10)

    def test_score_run_surfaces_low_score_items_grouped_by_suite(self):
        raw = [
            {
                "index": 54,
                "category": "边界能力",
                "question": "上海天气预报",
                "ok": True,
                "mode": "data_query",
                "seconds": 0.5,
                "answer": "从2026-03-14起，墒情异常最多的地区为：1.淮安市。",
            },
            {
                "index": 24,
                "category": "预测能力",
                "question": "未来10天哪些县风险最高？",
                "ok": True,
                "mode": "data_query",
                "seconds": 0.4,
                "answer": "未来10天风险较高。",
            },
        ]

        scored = score_run(raw)

        by_suite = scored["summary"]["low_score_items_by_suite"]
        self.assertIn("ood", by_suite)
        self.assertIn("forecast", by_suite)
        self.assertEqual(by_suite["ood"][0]["index"], 54)
        self.assertEqual(by_suite["forecast"][0]["index"], 24)

    def test_eval_thread_ids_are_namespaced_per_run(self):
        strict_eval = self._load_script_module("run_strict_acceptance_eval", "scripts/run_strict_acceptance_eval.py")
        acceptance_suite = self._load_script_module("run_acceptance_suite", "scripts/run_acceptance_suite.py")

        strict_known: dict[str, str] = {}
        acceptance_known: dict[str, str] = {}

        strict_a = strict_eval._thread_id_for("多轮上下文", strict_known, "run-a")
        strict_b = strict_eval._thread_id_for("多轮上下文", {}, "run-b")
        acceptance_a = acceptance_suite._thread_id_for("多轮上下文", acceptance_known, "run-a")
        acceptance_b = acceptance_suite._thread_id_for("多轮上下文", {}, "run-b")

        self.assertNotEqual(strict_a, strict_b)
        self.assertNotEqual(acceptance_a, acceptance_b)

    def test_score_run_penalizes_trend_missing_direction_and_county_scope_mismatch(self):
        raw = [
            {
                "index": 6,
                "category": "区域粒度",
                "question": "我问的是县，不是市，过去5个月虫情最高的县有哪些？",
                "ok": True,
                "mode": "data_query",
                "seconds": 0.9,
                "answer": "过去5个月虫情最高的市为：徐州市、淮安市。",
            },
            {
                "index": 19,
                "category": "趋势分析",
                "question": "最近30天预警数量是增加还是减少？",
                "ok": True,
                "mode": "data_query",
                "seconds": 0.6,
                "answer": "最近30天预警信息共 12 条。",
            },
        ]

        scored = score_run(raw)
        by_index = {item["index"]: item for item in scored["items"]}
        self.assertIn("county_scope_mismatch", by_index[6]["checks_failed"])
        self.assertLess(by_index[6]["score"], 7.5)
        self.assertIn("trend_missing_direction", by_index[19]["checks_failed"])
        self.assertLess(by_index[19]["score"], 7.5)

    def test_score_run_penalizes_weak_forecast_overclaim(self):
        raw = [
            {
                "index": 21,
                "category": "预测能力",
                "question": "未来两周虫情会怎样？",
                "ok": True,
                "mode": "data_query",
                "seconds": 0.8,
                "answer": "未来两周虫情风险预计为高（置信度0.62，样本覆盖 0 个观测日）。依据：最近值仍高于窗口均值。",
            }
        ]

        scored = score_run(raw)
        item = scored["items"][0]
        self.assertIn("forecast_overclaims_weak_evidence", item["checks_failed"])
        self.assertLess(item["score"], 7.5)

    def test_score_run_penalizes_fallback_shaped_county_answer(self):
        raw = [
            {
                "index": 117,
                "category": "综合能力",
                "question": "最近30天哪些县虫情高但预警并不多？",
                "ok": True,
                "mode": "data_query",
                "seconds": 0.4,
                "answer": "这次回答没有对齐到县级口径，我先保守收口：请让我按县一级重新返回结果，避免把市级排行误当成县级答案。",
            }
        ]

        scored = score_run(raw)
        item = scored["items"][0]
        self.assertIn("fallback_instead_of_answer", item["checks_failed"])
        self.assertIn("county_scope_mismatch", item["checks_failed"])
        self.assertLess(item["score"], 5.0)

    def test_score_run_rewards_invalid_input_clarification_and_penalizes_business_hijack(self):
        raw = [
            {
                "index": 141,
                "category": "无效输入",
                "suite": "invalid_input",
                "question": "h d k j h sa d k l j",
                "ok": True,
                "mode": "advice",
                "seconds": 0.1,
                "answer": "我没看懂这条输入。你可以直接问虫情、墒情、预警数据，或让我给处置建议。",
                "evidence": {
                    "generation_mode": "clarification",
                    "response_meta": {"fallback_reason": "invalid_gibberish"},
                },
            },
            {
                "index": 142,
                "category": "无效输入",
                "suite": "invalid_input",
                "question": "asd qwe zxc",
                "ok": True,
                "mode": "advice",
                "seconds": 0.1,
                "answer": "建议：1. 先分区核查土壤墒情。 2. 对低墒地块优先补水。",
                "evidence": {
                    "generation_mode": "llm",
                    "response_meta": {"fallback_reason": "router_advice"},
                },
            },
        ]

        scored = score_run(raw)
        by_index = {item["index"]: item for item in scored["items"]}
        self.assertGreaterEqual(by_index[141]["score"], 9.0)
        self.assertLess(by_index[142]["score"], 3.5)
        self.assertIn("invalid_input_business_hijack", by_index[142]["checks_failed"])
        self.assertIn("invalid_input_wrong_generation_mode", by_index[142]["checks_failed"])

    def test_score_run_reports_invalid_input_suite_scores(self):
        raw = [
            {
                "index": 141,
                "category": "无效输入",
                "suite": "invalid_input",
                "question": "!!! ??? 12345",
                "ok": True,
                "mode": "advice",
                "seconds": 0.1,
                "answer": "我没看懂这条输入。你可以直接问虫情、墒情、预警数据，或让我给处置建议。",
                "evidence": {
                    "generation_mode": "clarification",
                    "response_meta": {"fallback_reason": "invalid_noise"},
                },
            }
        ]

        scored = score_run(raw)
        self.assertIn("invalid_input", scored["summary"]["suite_scores"])
        self.assertGreaterEqual(scored["summary"]["suite_scores"]["invalid_input"], 9.0)


if __name__ == "__main__":
    unittest.main()
