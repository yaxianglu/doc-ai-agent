import unittest

from doc_ai_agent.agri_semantics import (
    asks_county_scope,
    has_negated_advice,
    infer_region_scope,
    needs_advice,
    needs_explanation,
    needs_forecast,
)


class AgriSemanticsTests(unittest.TestCase):
    def test_needs_explanation_detects_reason_tokens(self):
        self.assertTrue(needs_explanation("为什么过去5个月徐州虫情这么高"))
        self.assertTrue(needs_explanation("请给我原因和依据"))
        self.assertFalse(needs_explanation("过去5个月徐州虫情最高的是哪里"))

    def test_needs_advice_respects_negation(self):
        self.assertTrue(needs_advice("未来两周徐州虫情怎么处理"))
        self.assertFalse(needs_advice("不要建议，只说原因"))
        self.assertTrue(has_negated_advice("不要建议，只说原因"))

    def test_needs_forecast_uses_future_window_and_future_question(self):
        self.assertTrue(needs_forecast("未来两周徐州虫情会怎样", {"window_type": "weeks", "window_value": 2}))
        self.assertTrue(needs_forecast("未来徐州虫情会怎样", None))
        self.assertTrue(needs_forecast("徐州虫情会不会更糟", None))
        self.assertFalse(needs_forecast("未来虫害怎么养", None, needs_advice=True))

    def test_infer_region_scope_reuses_county_scope_semantics(self):
        self.assertEqual(infer_region_scope("最高的县有哪些"), "county")
        self.assertEqual(infer_region_scope("徐州虫情最高"), "city")
        self.assertTrue(asks_county_scope("排前面的县是哪些"))


if __name__ == "__main__":
    unittest.main()
