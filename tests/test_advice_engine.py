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

    def test_generic_disaster_advice_can_ask_for_crop_and_scene_when_needed(self):
        engine = AdviceEngine()

        result = engine.answer("台风过后需要注意什么？")

        self.assertEqual(result.generation_mode, "rule")
        self.assertIn("作物", result.answer)
        self.assertIn("场景", result.answer)
        self.assertIn("例如小麦", result.answer)

    def test_scene_aware_soil_advice_uses_context_scene_instead_of_generic_mixed_advice(self):
        engine = AdviceEngine()

        result = engine.answer(
            "给一个行动建议。",
            context={"domain": "soil", "region_name": "徐州市", "scene": "设施大棚"},
        )

        self.assertIn("设施大棚", result.answer)
        self.assertTrue("补灌" in result.answer or "排水" in result.answer)
        self.assertNotIn("成虫/幼虫", result.answer)
        self.assertNotIn("天气过程", result.answer)


if __name__ == "__main__":
    unittest.main()
