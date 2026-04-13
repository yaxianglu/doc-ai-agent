import unittest

from doc_ai_agent.answer_style import (
    compose_analysis_answer,
    polish_advice_text,
    polish_conclusion_text,
    polish_explanation_text,
)


class AnswerStyleTests(unittest.TestCase):
    def test_polish_conclusion_text_adds_judgment_lead(self):
        text = polish_conclusion_text("徐州市虫情整体偏高，当前仍处高位")

        self.assertTrue(text.startswith("当前判断，"))
        self.assertIn("当前仍处高位", text)

    def test_polish_explanation_text_adds_business_reasoning_lead(self):
        text = polish_explanation_text("峰值明显高于常态，最近值仍处高位")

        self.assertTrue(text.startswith("从数据看，"))
        self.assertIn("最近值仍处高位", text)

    def test_polish_advice_text_adds_prioritized_lead(self):
        text = polish_advice_text("先复核高值点位，再做分区处置")

        self.assertTrue(text.startswith("建议优先"))
        self.assertIn("分区处置", text)
        self.assertIn("再做分区处置", text)

    def test_compose_analysis_answer_deduplicates_sections(self):
        answer = compose_analysis_answer(["原因：从数据看，风险偏高。", "原因：从数据看，风险偏高。", "建议：建议优先复核。"])

        self.assertEqual(answer.count("原因："), 1)
        self.assertEqual(answer.count("建议："), 1)


if __name__ == "__main__":
    unittest.main()
