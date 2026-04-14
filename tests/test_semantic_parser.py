import unittest

from doc_ai_agent.semantic_parser import SemanticParser


class SemanticParserTests(unittest.TestCase):
    def test_weather_question_is_marked_out_of_scope(self):
        parser = SemanticParser()

        result = parser.parse("浙江天气")

        self.assertTrue(result.is_out_of_scope)
        self.assertEqual(result.intent, "advice")
        self.assertIn("ood", result.trace)


if __name__ == "__main__":
    unittest.main()
