import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tavily_search import TavilyRoleResearcher


class TavilyRoleResearcherTests(unittest.TestCase):
    def test_search_sends_only_role_direction_and_returns_capped_sources(self):
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "results": [
                    {"title": "岗位要求", "url": "https://example.invalid/role", "content": "X" * 5000},
                    {"title": "招聘指南", "url": "https://example.invalid/guide", "content": "常见职责。"},
                ]
            },
        )
        researcher = TavilyRoleResearcher(
            enabled=True, api_key="test-key", timeout=7, max_results=2
        )

        with patch("tavily_search.requests.post", return_value=response) as post:
            results = researcher.search("AI 应用开发", ["后端开发"])

        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.tavily.com/search")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(kwargs["timeout"], 7)
        self.assertIn("AI 应用开发", kwargs["json"]["query"])
        self.assertIn("后端开发", kwargs["json"]["query"])
        self.assertFalse(kwargs["json"]["include_raw_content"])
        self.assertEqual(len(results), 2)
        self.assertEqual(len(results[0]["content"]), 1200)

    def test_disabled_or_missing_key_never_makes_a_request(self):
        for researcher in (
            TavilyRoleResearcher(enabled=False, api_key="test-key"),
            TavilyRoleResearcher(enabled=True, api_key=""),
        ):
            with self.subTest(enabled=researcher.enabled, api_key=researcher.api_key):
                with patch("tavily_search.requests.post") as post:
                    self.assertEqual(researcher.search("AI 应用开发", []), [])
                post.assert_not_called()

    def test_request_failure_propagates_for_service_fallback(self):
        researcher = TavilyRoleResearcher(enabled=True, api_key="test-key")

        with patch("tavily_search.requests.post", side_effect=TimeoutError("timeout")):
            with self.assertRaises(TimeoutError):
                researcher.search("AI 应用开发", [])


if __name__ == "__main__":
    unittest.main()
