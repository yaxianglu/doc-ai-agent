import unittest

from doc_ai_agent.query_playbook_router import (
    LlamaIndexQueryPlaybookRouter,
    StaticQueryPlaybookRouter,
    create_query_playbook_router,
)


class FakeLlamaBackend:
    def __init__(self, payload):
        self.payload = payload

    def search(self, question: str, limit: int = 1, context: dict | None = None):
        if isinstance(self.payload, list):
            return [dict(item) for item in self.payload[:limit]]
        return [dict(self.payload)]


class QueryPlaybookRouterTests(unittest.TestCase):
    def test_static_router_matches_joint_risk_phrase(self):
        router = StaticQueryPlaybookRouter()

        result = router.route("近两个月哪些地方虫情高而且缺水更明显？")

        self.assertEqual(result["query_type"], "joint_risk")
        self.assertEqual(result["intent"], "data_query")
        self.assertEqual(result["retrieval_engine"], "static")

    def test_static_router_matches_soil_top_phrase_without_explicit_soil_keyword(self):
        router = StaticQueryPlaybookRouter()

        result = router.route("过去5个月缺水最厉害的地方是哪里？")

        self.assertEqual(result["query_type"], "soil_top")
        self.assertEqual(result["domain"], "soil")

    def test_llamaindex_router_falls_back_to_static_when_backend_missing(self):
        router = LlamaIndexQueryPlaybookRouter(backend=None)

        result = router.route("南京近三周虫害走势怎么样？")

        self.assertEqual(result["query_type"], "pest_trend")
        self.assertEqual(result["retrieval_engine"], "static-fallback")

    def test_create_router_returns_llamaindex_router_when_enabled(self):
        router = create_query_playbook_router(backend="llamaindex")

        self.assertIsInstance(router, LlamaIndexQueryPlaybookRouter)

    def test_static_router_does_not_upgrade_generic_alert_top_question(self):
        router = StaticQueryPlaybookRouter()

        result = router.route("给我前3个预警最多的地区，从2026年开始")

        self.assertEqual(result, {})

    def test_llamaindex_router_uses_static_guardrail_for_joint_risk_question(self):
        router = LlamaIndexQueryPlaybookRouter(
            backend=FakeLlamaBackend(
                {
                    "intent": "data_query",
                    "query_type": "pest_top",
                    "domain": "pest",
                    "title": "虫情严重地区排行",
                    "retrieval_engine": "llamaindex",
                    "matched_terms": ["虫情"],
                    "score": 0.91,
                }
            )
        )

        result = router.route("近两个月哪些地方虫情高而且缺水更明显？")

        self.assertEqual(result["query_type"], "joint_risk")
        self.assertEqual(result["retrieval_engine"], "static-fallback")

    def test_llamaindex_router_reranks_trend_over_overview_for_ambiguous_candidates(self):
        router = LlamaIndexQueryPlaybookRouter(
            backend=FakeLlamaBackend(
                [
                    {
                        "intent": "data_query",
                        "query_type": "pest_overview",
                        "domain": "pest",
                        "title": "虫情地区概览",
                        "retrieval_engine": "llamaindex",
                        "matched_terms": ["虫害"],
                        "score": 0.92,
                    },
                    {
                        "intent": "data_query",
                        "query_type": "pest_trend",
                        "domain": "pest",
                        "title": "虫情趋势分析",
                        "retrieval_engine": "llamaindex",
                        "matched_terms": ["虫害", "走势"],
                        "score": 0.81,
                    },
                ]
            )
        )

        result = router.route("南京近三周虫害走势怎么样？")

        self.assertEqual(result["query_type"], "pest_trend")
        self.assertEqual(result["retrieval_rank"], 1)
        self.assertEqual(result["recall_rank"], 2)
        self.assertTrue(result["retrieval_reranked"])

    def test_llamaindex_router_reranks_overview_over_top_for_region_summary(self):
        router = LlamaIndexQueryPlaybookRouter(
            backend=FakeLlamaBackend(
                [
                    {
                        "intent": "data_query",
                        "query_type": "pest_top",
                        "domain": "pest",
                        "title": "虫情严重地区排行",
                        "retrieval_engine": "llamaindex",
                        "matched_terms": ["虫情"],
                        "score": 0.93,
                    },
                    {
                        "intent": "data_query",
                        "query_type": "pest_overview",
                        "domain": "pest",
                        "title": "虫情地区概览",
                        "retrieval_engine": "llamaindex",
                        "matched_terms": ["虫情", "整体"],
                        "score": 0.79,
                    },
                ]
            )
        )

        result = router.route("过去5个月徐州市虫情整体情况如何？")

        self.assertEqual(result["query_type"], "pest_overview")
        self.assertTrue(result["retrieval_reranked"])


if __name__ == "__main__":
    unittest.main()
