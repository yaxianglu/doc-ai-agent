import unittest

from doc_ai_agent.answer_guard import AnswerGuard


class AnswerGuardTests(unittest.TestCase):
    def setUp(self):
        self.guard = AnswerGuard()

    def test_rewrites_count_only_trend_answer(self):
        result = self.guard.review(
            question="最近30天预警数量是增加还是减少？",
            understanding={"domain": "", "needs_forecast": False},
            plan={"route": {"query_type": "alerts_trend"}},
            query_result={
                "answer": "最近30天预警信息共 12 条。",
                "data": [
                    {"date": "2026-03-15", "alert_count": 4},
                    {"date": "2026-03-29", "alert_count": 9},
                    {"date": "2026-04-13", "alert_count": 12},
                ],
                "evidence": {"query_type": "alerts_trend"},
            },
            forecast_result={},
            response={"mode": "data_query", "answer": "最近30天预警信息共 12 条。", "data": [], "evidence": {}},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "rewrite")
        self.assertEqual(result["violations"][0]["code"], "trend_missing_direction")
        self.assertIn("预警数量趋势", result["rewritten_answer"])
        self.assertRegex(result["rewritten_answer"], r"(整体上升|整体下降|整体波动平稳|样本不足)")

    def test_appends_forecast_evidence_when_missing(self):
        result = self.guard.review(
            question="未来两周虫情会怎样？",
            understanding={"domain": "pest", "needs_forecast": True},
            plan={"route": {"query_type": "pest_forecast"}},
            query_result={},
            forecast_result={
                "forecast": {
                    "confidence": 0.62,
                    "history_points": 12,
                    "top_factors": ["最近值仍高于窗口均值", "预测结果仍接近历史高位", "样本覆盖 12 个观测日"],
                }
            },
            response={"mode": "data_query", "answer": "未来两周虫情风险预计为高。", "data": [], "evidence": {}},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "rewrite")
        self.assertEqual(result["violations"][0]["code"], "forecast_missing_support")
        self.assertIn("置信度0.62", result["rewritten_answer"])
        self.assertIn("样本覆盖 12 个观测日", result["rewritten_answer"])
        self.assertIn("依据：", result["rewritten_answer"])

    def test_falls_back_when_domain_is_misaligned(self):
        result = self.guard.review(
            question="最近30天预警最多的是哪些地区？",
            understanding={"domain": "", "needs_forecast": False},
            plan={"route": {"query_type": "alerts_top"}},
            query_result={},
            forecast_result={},
            response={
                "mode": "data_query",
                "answer": "从2026-03-14起，墒情异常最多的地区为：1.淮安市（异常强度1015.26，异常43条，低墒15，高墒28）。",
                "data": [],
                "evidence": {},
            },
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "fallback")
        self.assertEqual(result["violations"][0]["code"], "domain_mismatch")
        self.assertIn("预警", result["fallback_answer"])
        self.assertNotIn("墒情异常最多", result["fallback_answer"])

    def test_sanitizes_internal_epoch_date(self):
        result = self.guard.review(
            question="过去5个月虫情总体是上升还是下降？",
            understanding={"domain": "pest", "needs_forecast": False},
            plan={"route": {"query_type": "pest_trend"}},
            query_result={},
            forecast_result={},
            response={
                "mode": "data_query",
                "answer": "从1970-01-01起整体虫情趋势：整体上升。",
                "data": [],
                "evidence": {},
            },
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "rewrite")
        self.assertEqual(result["violations"][0]["code"], "internal_default_time_exposed")
        self.assertNotIn("1970-01-01", result["rewritten_answer"])

    def test_retries_county_scope_mismatch_with_parent_city_route(self):
        result = self.guard.review(
            question="常州市下面虫情最严重的县有哪些？",
            understanding={"domain": "pest", "needs_forecast": False},
            plan={"route": {"query_type": "pest_top", "region_level": "county", "city": "常州市", "county": "常州市"}},
            query_result={},
            forecast_result={},
            response={
                "mode": "data_query",
                "answer": "历史上，虫情严重度最高的Top5市为：1.常州市。",
                "data": [],
                "evidence": {},
            },
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "retry")
        self.assertEqual(result["violations"][0]["code"], "county_scope_mismatch")
        self.assertEqual(result["retry_route"]["city"], "常州市")
        self.assertIsNone(result["retry_route"]["county"])
        self.assertEqual(result["retry_route"]["region_level"], "county")

    def test_falls_back_when_answer_time_range_conflicts_with_question(self):
        result = self.guard.review(
            question="最近30天预警最多的是哪些地区？",
            understanding={"domain": "", "needs_forecast": False},
            plan={"route": {"query_type": "alerts_top"}},
            query_result={},
            forecast_result={},
            response={
                "mode": "data_query",
                "answer": "过去5个月预警最多的地区为：1.淮安市。",
                "data": [],
                "evidence": {},
            },
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "fallback")
        self.assertEqual(result["violations"][0]["code"], "time_range_mismatch")

    def test_invalid_input_business_advice_is_rewritten_to_clarification(self):
        result = self.guard.review(
            question="h d k j h sa d k l j",
            understanding={"fallback_reason": "invalid_gibberish"},
            plan={"intent": "advice"},
            query_result={},
            forecast_result={},
            response={"mode": "advice", "answer": "建议：先分区核查土壤墒情。"},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "fallback")
        self.assertEqual(result["violations"][0]["code"], "invalid_input_business_answer")
        self.assertIn("没看懂", result["fallback_answer"])


if __name__ == "__main__":
    unittest.main()
