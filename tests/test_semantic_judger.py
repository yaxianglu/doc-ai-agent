import unittest

from doc_ai_agent.semantic_judger import SemanticJudger


class SemanticJudgerTests(unittest.TestCase):
    def test_generic_explanation_returns_direct_explanation_mode(self):
        judger = SemanticJudger()

        decision = judger.judge("从数据看，这次异常最可能的原因是什么？")

        self.assertEqual(decision["reason"], "generic_explanation")
        self.assertFalse(decision["needs_clarification"])

