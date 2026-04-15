"""Data Query Capability：统一封装历史事实查询。"""

from __future__ import annotations

from ..capability_result import CapabilityResult


class DataQueryCapability:
    """对 QueryEngine 的轻量能力封装。"""

    def __init__(self, query_engine):
        self.query_engine = query_engine

    def execute(self, question: str, route: dict) -> tuple[object, CapabilityResult]:
        result = self.query_engine.answer(question, plan=route)
        return result, result.to_capability_result()
