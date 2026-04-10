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


if __name__ == "__main__":
    unittest.main()
