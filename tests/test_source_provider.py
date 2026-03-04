import unittest

from doc_ai_agent.source_provider import StaticSourceProvider


class SourceProviderTests(unittest.TestCase):
    def test_search_by_keyword(self):
        provider = StaticSourceProvider(
            [
                {
                    "title": "台风后小麦田间管理技术意见",
                    "url": "https://example.gov/a",
                    "published_at": "2026-02-10",
                    "snippet": "台风后小麦应及时清沟排水，防倒伏。",
                },
                {
                    "title": "玉米虫害防治要点",
                    "url": "https://example.gov/b",
                    "published_at": "2026-02-11",
                    "snippet": "玉米螟监测与防治。",
                },
            ]
        )
        result = provider.search("台风后小麦注意什么", limit=3)
        self.assertEqual(len(result), 1)
        self.assertIn("排水", result[0]["snippet"])


if __name__ == "__main__":
    unittest.main()
