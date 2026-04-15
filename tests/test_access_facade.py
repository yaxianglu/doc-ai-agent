import unittest

from doc_ai_agent.access_facade import AccessFacade


class FakeRepo:
    def backend_label(self):
        return "SQLite"


class FakeSourceProvider:
    def backend_label(self):
        return "Qdrant"

    def search(self, question, limit=3, context=None):
        return [{"title": "知识A", "question": question, "limit": limit, "context": context or {}}]


class FakePlaybookRouter:
    def backend_label(self):
        return "StaticPlaybookRouter"

    def route(self, question, context=None):
        return {"query_type": "pest_top", "question": question, "context": context or {}}


class AccessFacadeTests(unittest.TestCase):
    def test_access_facade_exposes_unified_backend_summary(self):
        facade = AccessFacade(
            repo=FakeRepo(),
            source_provider=FakeSourceProvider(),
            query_playbook_router=FakePlaybookRouter(),
        )

        summary = facade.backend_summary()

        self.assertEqual(summary["data_backend"], "SQLite")
        self.assertEqual(summary["knowledge_backend"], "Qdrant")
        self.assertEqual(summary["playbook_backend"], "StaticPlaybookRouter")

    def test_access_facade_routes_playbooks_and_sources(self):
        facade = AccessFacade(
            repo=FakeRepo(),
            source_provider=FakeSourceProvider(),
            query_playbook_router=FakePlaybookRouter(),
        )

        routed = facade.route_query("哪些地区虫情最严重？", context={"domain": "pest"})
        sources = facade.search_sources("为什么虫情高？", limit=2, context={"domain": "pest"})

        self.assertEqual(routed["query_type"], "pest_top")
        self.assertEqual(routed["context"]["domain"], "pest")
        self.assertEqual(sources[0]["limit"], 2)
        self.assertEqual(sources[0]["context"]["domain"], "pest")


if __name__ == "__main__":
    unittest.main()
