import unittest

from doc_ai_agent.advice_engine import AdviceEngine


class FailingLLMClient:
    def complete_text(self, model, system_prompt, user_prompt):
        raise RuntimeError("upstream 400")


class AdviceEngineFallbackTests(unittest.TestCase):
    def test_falls_back_to_rule_answer_when_llm_call_fails(self):
        engine = AdviceEngine(llm_client=FailingLLMClient(), model="gpt-test")

        result = engine.answer(
            "给一个行动建议。",
            context={"domain": "pest", "region_name": "宿迁市"},
        )

        self.assertEqual(result.generation_mode, "rule")
        self.assertEqual(result.model, "")
        self.assertIn("建议：", result.answer)
        self.assertIn("宿迁市", result.answer)


if __name__ == "__main__":
    unittest.main()
