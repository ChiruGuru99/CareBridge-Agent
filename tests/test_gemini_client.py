import unittest

from carebridge.gemini_client import parse_json_object


class GeminiClientTests(unittest.TestCase):
    def test_parse_json_object_from_plain_json(self):
        payload = parse_json_object('{"needs": ["food"], "urgency": "standard"}')

        self.assertEqual(payload["needs"], ["food"])

    def test_parse_json_object_from_markdown_fence(self):
        payload = parse_json_object('```json\n{"summary": "ok"}\n```')

        self.assertEqual(payload["summary"], "ok")


if __name__ == "__main__":
    unittest.main()
