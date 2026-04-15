import unittest


LOW_SCORE_FIXTURES = {
    "boolean_first": {
        "index": 20,
        "question": "近两个月墒情有没有缓解？",
        "checks_failed": ["fallback_instead_of_answer", "trend_missing_direction"],
        "answer": "这次回答没有对齐到墒情口径，我先保守收口：请让我按墒情数据重新回答，避免混入虫情或预警结果。",
    },
    "trend_direction_first": {
        "index": 16,
        "question": "过去5个月虫情总体是上升还是下降？",
        "checks_failed": ["fallback_instead_of_answer", "trend_missing_direction"],
        "answer": "这次回答没有对齐到虫情口径，我先保守收口：请让我按虫情数据重新回答，避免混入墒情或预警结果。",
    },
    "county_no_silent_city_degrade": {
        "index": 69,
        "question": "最近7天风险最高的是哪些县？",
        "checks_failed": ["fallback_instead_of_answer", "county_scope_mismatch"],
        "answer": "这次回答没有对齐到县级口径，我先保守收口：请让我按县一级重新返回结果，避免把市级排行误当成县级答案。",
    },
    "multi_turn_carry_over": {
        "index": 133,
        "question": "过去5个月虫情总体是上升还是下降？ -> 常州呢？ -> 苏州呢？",
        "checks_failed": ["fallback_instead_of_answer", "trend_missing_direction"],
        "answer": "你这条输入信息不足。请告诉我：要做数据统计，还是要处置建议？",
    },
    "composite_rank_reason_advice": {
        "index": 113,
        "question": "先给我过去5个月最严重的县，再解释原因，再给建议",
        "checks_failed": [
            "explanation_missing_reason_section",
            "explanation_missing_grounding",
            "explanation_missing_followup_checks",
        ],
        "answer": "你希望我做数据统计，还是生成处置建议？可以补充时间范围或地区。",
    },
}


class LowScoreRegressionTests(unittest.TestCase):
    @staticmethod
    def _first_line(text: str) -> str:
        return next((line.strip() for line in str(text).splitlines() if line.strip()), "")

    def test_boolean_question_answer_starts_with_yes_or_no(self):
        fixture = LOW_SCORE_FIXTURES["boolean_first"]
        first_line = self._first_line(fixture["answer"])
        self.assertRegex(first_line, r"^(是|否|有|没有|会|不会)")

    def test_trend_question_answer_starts_with_direction(self):
        fixture = LOW_SCORE_FIXTURES["trend_direction_first"]
        first_line = self._first_line(fixture["answer"])
        self.assertRegex(first_line, r"^(上升|下降|持平|缓解|加重)")

    def test_county_question_does_not_silently_degrade_to_city(self):
        fixture = LOW_SCORE_FIXTURES["county_no_silent_city_degrade"]
        answer = fixture["answer"]
        self.assertIn("县", fixture["question"])
        self.assertNotIn("请让我按县一级重新返回结果", answer)
        self.assertRegex(answer, r"\d+[\.|、]")

    def test_multi_turn_carry_over_keeps_domain_and_trend_intent(self):
        fixture = LOW_SCORE_FIXTURES["multi_turn_carry_over"]
        answer = fixture["answer"]
        self.assertIn("常州", fixture["question"])
        self.assertIn("苏州", fixture["question"])
        self.assertRegex(answer, r"(上升|下降|持平|缓解|加重)")

    def test_composite_question_contains_rank_reason_and_advice_sections(self):
        fixture = LOW_SCORE_FIXTURES["composite_rank_reason_advice"]
        answer = fixture["answer"]
        self.assertRegex(answer, r"\d+[\.|、]")
        self.assertIn("原因", answer)
        self.assertIn("建议", answer)


if __name__ == "__main__":
    unittest.main()
