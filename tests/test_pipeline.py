import unittest
from unittest.mock import patch

from carebridge.agents import run_carebridge_agent
from carebridge.mcp_client import ResourceMCPClient


class PipelineTests(unittest.TestCase):
    def test_mcp_server_lists_and_calls_tools(self):
        with ResourceMCPClient() as client:
            tool_names = [tool["name"] for tool in client.list_tools()]
            self.assertIn("search_resources", tool_names)
            resources = client.call_tool(
                "search_resources",
                {
                    "query": "rent and groceries",
                    "location": "Austin, TX",
                    "needs": ["housing", "food"],
                    "limit": 3,
                },
            )

        self.assertGreaterEqual(len(resources), 1)
        self.assertIn("name", resources[0])

    @patch.dict("os.environ", {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=False)
    def test_agent_pipeline_returns_safe_plan(self):
        plan = run_carebridge_agent(
            {
                "text": "My hours were cut, rent is due Friday, and we need food. Email alex@example.com.",
                "location": "Austin, TX",
                "household_size": 3,
                "language": "English",
            }
        )

        self.assertEqual(plan["track"], "Agents for Good")
        self.assertIn("housing", plan["needs"])
        self.assertIn("food", plan["needs"])
        self.assertIn("[REDACTED_EMAIL]", plan["sanitized_request"])
        self.assertEqual(plan["mode"], "deterministic_fallback")
        self.assertFalse(plan["llm"]["enabled"])
        self.assertGreaterEqual(len(plan["resources"]), 1)
        self.assertGreaterEqual(len(plan["trace"]), 5)

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "gemini-test"}, clear=False)
    @patch("carebridge.agents.GeminiClient")
    def test_agent_pipeline_uses_gemini_when_configured(self, fake_client_class):
        fake_client = fake_client_class.return_value
        fake_client.configured = True
        fake_client.model = "gemini-test"
        fake_client.generate_json.side_effect = [
            {
                "needs": ["housing", "food"],
                "urgency": "urgent",
                "rationale": "Rent and food support requested.",
            },
            {
                "summary": "Gemini generated support plan.",
                "steps": [
                    {
                        "title": "Call the strongest matches",
                        "actions": ["Call the top housing and food resources from the MCP results."],
                    }
                ],
                "call_script": "I need urgent food and rent navigation support.",
            },
        ]

        plan = run_carebridge_agent(
            {
                "text": "Rent is due today and we need groceries. Email alex@example.com.",
                "location": "Austin, TX",
                "household_size": 3,
                "language": "English",
            }
        )

        self.assertEqual(plan["mode"], "gemini")
        self.assertTrue(plan["llm"]["enabled"])
        self.assertEqual(plan["llm"]["model"], "gemini-test")
        self.assertIn("[REDACTED_EMAIL]", plan["sanitized_request"])
        self.assertIn("gemini.generateContent:gemini-test", str(plan["trace"]))
        self.assertEqual(fake_client.generate_json.call_count, 2)


if __name__ == "__main__":
    unittest.main()
