import unittest

from doc_ai_agent.input_guard import classify_input_quality


class InputGuardTests(unittest.TestCase):
    def test_keyboard_mash_is_marked_invalid(self):
        decision = classify_input_quality("h d k j h sa d k l j")

        self.assertFalse(decision["is_valid_input"])
        self.assertEqual(decision["reason"], "invalid_gibberish")
        self.assertTrue(decision["should_clarify"])

    def test_short_english_fragments_are_marked_invalid(self):
        decision = classify_input_quality("asd qwe zxc")

        self.assertFalse(decision["is_valid_input"])
        self.assertEqual(decision["reason"], "invalid_gibberish")
        self.assertTrue(decision["should_clarify"])

    def test_symbol_and_digit_noise_is_marked_invalid(self):
        decision = classify_input_quality("!!! ??? 12345")

        self.assertFalse(decision["is_valid_input"])
        self.assertEqual(decision["reason"], "invalid_noise")
        self.assertTrue(decision["should_clarify"])
