import json
import tempfile
import unittest
from pathlib import Path

from doc_ai_agent.acceptance_eval import compare_scored_runs, load_question_bank, score_run


class AcceptanceEvalTests(unittest.TestCase):
    def test_load_question_bank_reads_fixed_50_questions(self):
        question_bank = load_question_bank(
            Path(__file__).resolve().parents[1] / "evals" / "strict_acceptance_50.json"
        )

        self.assertEqual(len(question_bank), 50)
        self.assertEqual(question_bank[0]["index"], 1)
        self.assertEqual(question_bank[-1]["index"], 50)

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
        ]

        scored = score_run(raw)
        by_index = {item["index"]: item for item in scored["items"]}
        self.assertGreaterEqual(by_index[27]["score"], 8.5)
        self.assertNotIn("misrouted_to_advice", by_index[27]["checks_failed"])
        self.assertGreaterEqual(by_index[46]["score"], 8.5)

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


if __name__ == "__main__":
    unittest.main()
