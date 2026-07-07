import unittest

from carebridge.gemini_client import normalize_model_name, parse_json_object


class GeminiClientTests(unittest.TestCase):
    def test_parse_json_object_from_plain_json(self):
        payload = parse_json_object('{"needs": ["food"], "urgency": "standard"}')

        self.assertEqual(payload["needs"], ["food"])

    def test_parse_json_object_from_markdown_fence(self):
        payload = parse_json_object('```json\n{"summary": "ok"}\n```')

        self.assertEqual(payload["summary"], "ok")

    def test_normalize_model_name_accepts_models_prefix_and_spaces(self):
        self.assertEqual(normalize_model_name("models/gemini-3.5-flash"), "gemini-3.5-flash")
        self.assertEqual(normalize_model_name("Gemini 3.5 Flash"), "gemini-3.5-flash")


if __name__ == "__main__":
    unittest.main()
