import unittest

from doc_ai_agent.source_provider import (
    LlamaIndexSourceProvider,
    QdrantSourceProvider,
    StaticSourceProvider,
    create_source_provider,
)


class FakeSemanticBackend:
    def search(self, question: str, limit: int = 3, context: dict | None = None):
        return [
            {
                "title": "虫情监测与绿色防控技术",
                "url": "https://example.gov/pest",
                "published_at": "2026-02-14",
                "snippet": f"semantic::{question}",
                "domain": "pest",
                "tags": ["虫情", "防控", "阈值"],
                "retrieval_engine": "qdrant",
                "retrieval_backend": "qdrant",
                "retrieval_strategy": "semantic-vector",
            }
        ][:limit]


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

    def test_domain_aware_retrieval_for_explanation_and_advice(self):
        provider = StaticSourceProvider(
            [
                {
                    "title": "虫情监测与绿色防控技术",
                    "url": "https://example.gov/pest",
                    "published_at": "2026-02-14",
                    "snippet": "针对迁飞性害虫应加强监测预警，按阈值采取分区防控措施。",
                    "domain": "pest",
                    "tags": ["虫情", "防控", "阈值"],
                },
                {
                    "title": "墒情调度与灌排要点",
                    "url": "https://example.gov/soil",
                    "published_at": "2026-02-15",
                    "snippet": "低墒优先补灌，高墒优先排水，并复核未来天气。",
                    "domain": "soil",
                    "tags": ["墒情", "排水", "补灌"],
                },
            ]
        )

        result = provider.search("为什么徐州市虫情这么高，怎么处置？", limit=2, context={"domain": "pest"})

        self.assertEqual(result[0]["domain"], "pest")
        self.assertIn("matched_terms", result[0])
        self.assertIn("虫情", result[0]["matched_terms"])
        self.assertIn("score", result[0])

    def test_llamaindex_provider_falls_back_to_static_when_backend_unavailable(self):
        items = [
            {
                "title": "虫情监测与绿色防控技术",
                "url": "https://example.gov/pest",
                "published_at": "2026-02-14",
                "snippet": "针对迁飞性害虫应加强监测预警，按阈值采取分区防控措施。",
                "domain": "pest",
                "tags": ["虫情", "防控", "阈值"],
            },
            {
                "title": "墒情调度与灌排要点",
                "url": "https://example.gov/soil",
                "published_at": "2026-02-15",
                "snippet": "低墒优先补灌，高墒优先排水，并复核未来天气。",
                "domain": "soil",
                "tags": ["墒情", "排水", "补灌"],
            },
        ]
        provider = LlamaIndexSourceProvider(items=items, backend=None)

        result = provider.search("为什么徐州市虫情这么高，怎么处置？", limit=2, context={"domain": "pest"})

        self.assertEqual(result[0]["domain"], "pest")
        self.assertEqual(result[0]["retrieval_engine"], "static-fallback")

    def test_create_source_provider_returns_llamaindex_when_enabled(self):
        items = [
            {
                "title": "虫情监测与绿色防控技术",
                "url": "https://example.gov/pest",
                "published_at": "2026-02-14",
                "snippet": "针对迁飞性害虫应加强监测预警，按阈值采取分区防控措施。",
                "domain": "pest",
                "tags": ["虫情", "防控", "阈值"],
            }
        ]

        provider = create_source_provider(items, backend="llamaindex")

        self.assertIsInstance(provider, LlamaIndexSourceProvider)

    def test_qdrant_provider_uses_semantic_backend_metadata_when_available(self):
        items = [
            {
                "title": "虫情监测与绿色防控技术",
                "url": "https://example.gov/pest",
                "published_at": "2026-02-14",
                "snippet": "针对迁飞性害虫应加强监测预警，按阈值采取分区防控措施。",
                "domain": "pest",
                "tags": ["虫情", "防控", "阈值"],
            }
        ]
        provider = QdrantSourceProvider(items=items, backend=FakeSemanticBackend())

        result = provider.search("为什么徐州市虫情这么高，怎么处置？", limit=1, context={"domain": "pest"})

        self.assertEqual(result[0]["retrieval_engine"], "qdrant")
        self.assertEqual(result[0]["retrieval_backend"], "qdrant")
        self.assertEqual(result[0]["retrieval_strategy"], "semantic-vector")

    def test_qdrant_provider_falls_back_to_static_when_backend_unavailable(self):
        items = [
            {
                "title": "虫情监测与绿色防控技术",
                "url": "https://example.gov/pest",
                "published_at": "2026-02-14",
                "snippet": "针对迁飞性害虫应加强监测预警，按阈值采取分区防控措施。",
                "domain": "pest",
                "tags": ["虫情", "防控", "阈值"],
            }
        ]
        provider = QdrantSourceProvider(items=items, backend=None)

        result = provider.search("为什么徐州市虫情这么高，怎么处置？", limit=1, context={"domain": "pest"})

        self.assertEqual(result[0]["retrieval_engine"], "static-fallback")
        self.assertEqual(result[0]["retrieval_backend"], "qdrant-fallback")

    def test_create_source_provider_returns_qdrant_when_enabled(self):
        items = [
            {
                "title": "虫情监测与绿色防控技术",
                "url": "https://example.gov/pest",
                "published_at": "2026-02-14",
                "snippet": "针对迁飞性害虫应加强监测预警，按阈值采取分区防控措施。",
                "domain": "pest",
                "tags": ["虫情", "防控", "阈值"],
            }
        ]

        provider = create_source_provider(items, backend="qdrant")

        self.assertIsInstance(provider, QdrantSourceProvider)


if __name__ == "__main__":
    unittest.main()
