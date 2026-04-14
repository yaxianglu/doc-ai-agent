import unittest

from doc_ai_agent.semantic_judger import SemanticJudger


class SemanticJudgerTests(unittest.TestCase):
    def test_weather_query_uses_explicit_ood_category(self):
        judger = SemanticJudger()

        decision = judger.judge("浙江天气怎么样")

        self.assertEqual(decision["reason"], "out_of_scope_weather")
        self.assertEqual(decision["fallback_reason"], "out_of_scope_weather")
        self.assertTrue(decision["needs_clarification"])

    def test_news_query_uses_explicit_ood_category(self):
        judger = SemanticJudger()

        decision = judger.judge("今天有什么新闻")

        self.assertEqual(decision["reason"], "out_of_scope_news")
        self.assertEqual(decision["fallback_reason"], "out_of_scope_news")
        self.assertTrue(decision["needs_clarification"])

    def test_transport_ticket_query_uses_explicit_ood_category(self):
        judger = SemanticJudger()

        decision = judger.judge("帮我订高铁票")

        self.assertEqual(decision["reason"], "out_of_scope_transport_ticket")
        self.assertEqual(decision["fallback_reason"], "out_of_scope_transport_ticket")
        self.assertTrue(decision["needs_clarification"])

    def test_identity_query_uses_explicit_edge_category(self):
        judger = SemanticJudger()

        decision = judger.judge("你是谁？")

        self.assertEqual(decision["reason"], "identity_self_intro")
        self.assertEqual(decision["fallback_reason"], "identity_self_intro")
        self.assertFalse(decision["needs_clarification"])

    def test_greeting_query_uses_explicit_edge_category(self):
        judger = SemanticJudger()

        decision = judger.judge("你好")

        self.assertEqual(decision["reason"], "greeting_intro")
        self.assertEqual(decision["fallback_reason"], "greeting_intro")
        self.assertFalse(decision["needs_clarification"])

    def test_generic_explanation_returns_direct_explanation_mode(self):
        judger = SemanticJudger()

        decision = judger.judge("从数据看，这次异常最可能的原因是什么？")

        self.assertEqual(decision["reason"], "generic_explanation")
        self.assertEqual(decision["fallback_reason"], "generic_explanation")
        self.assertFalse(decision["needs_clarification"])
