"""统一访问门面：把数据、知识和 playbook 路由收口到一个入口。"""

from __future__ import annotations


class AccessFacade:
    """面向能力层提供统一访问接口，隐藏底层数据源差异。"""

    def __init__(self, *, repo, source_provider=None, query_playbook_router=None):
        self.repo = repo
        self.source_provider = source_provider
        self.query_playbook_router = query_playbook_router

    def backend_summary(self) -> dict:
        """返回访问层各后端标签，便于调试与回放。"""
        return {
            "data_backend": self._backend_label(self.repo, default="UnknownData"),
            "knowledge_backend": self._backend_label(self.source_provider, default="Unavailable"),
            "playbook_backend": self._backend_label(self.query_playbook_router, default="Unavailable"),
        }

    def route_query(self, question: str, context: dict | None = None) -> dict:
        """把自然语言问题路由到具体 playbook。"""
        if self.query_playbook_router is None:
            return {}
        route = getattr(self.query_playbook_router, "route", None)
        if callable(route):
            return dict(route(question, context=context) or {})
        return {}

    def search_sources(self, question: str, limit: int = 3, context: dict | None = None) -> list[dict]:
        """统一查询知识源，保证返回列表。"""
        if self.source_provider is None:
            return []
        search = getattr(self.source_provider, "search", None)
        if not callable(search):
            return []
        try:
            results = search(question, limit=limit, context=context)
        except TypeError:
            results = search(question, limit=limit)
        return list(results or [])

    def search(self, question: str, limit: int = 3, context: dict | None = None) -> list[dict]:
        """兼容现有 source_provider.search 调用面。"""
        return self.search_sources(question, limit=limit, context=context)

    @staticmethod
    def _backend_label(component, *, default: str) -> str:
        if component is None:
            return default
        label = getattr(component, "backend_label", None)
        if callable(label):
            try:
                value = str(label() or "")
            except Exception:
                value = ""
            if value:
                return value
        return component.__class__.__name__
