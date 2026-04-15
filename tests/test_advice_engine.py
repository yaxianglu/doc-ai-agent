import unittest

from doc_ai_agent.advice_engine import AdviceEngine


class FailingLLMClient:
    def complete_text(self, model, system_prompt, user_prompt):
        raise RuntimeError("upstream 400")


class FacadeOnlySourceProvider:
    def search(self, question, limit=3, context=None):
        raise AssertionError("AdviceEngine should not call raw source provider directly")


class SpyAccessFacade:
    def __init__(self):
        self.calls = []

    def search_sources(self, question, limit=3, context=None):
        self.calls.append({"question": question, "limit": limit, "context": dict(context or {})})
        return [{"title": "知识A", "snippet": "通过 facade 检索"}]


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

    def test_uses_access_facade_for_source_retrieval(self):
        facade = SpyAccessFacade()
        engine = AdviceEngine(
            llm_client=FailingLLMClient(),
            model="gpt-test",
            source_provider=FacadeOnlySourceProvider(),
            access_facade=facade,
        )

        result = engine.answer(
            "给一个行动建议。",
            context={"domain": "pest", "region_name": "宿迁市"},
        )

        self.assertEqual(len(facade.calls), 1)
        self.assertEqual(facade.calls[0]["limit"], 3)
        self.assertEqual(facade.calls[0]["context"]["domain"], "pest")
        self.assertTrue(result.sources)


if __name__ == "__main__":
    unittest.main()
