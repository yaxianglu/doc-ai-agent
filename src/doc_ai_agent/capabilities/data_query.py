"""Data Query Capability：统一封装历史事实查询。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..capability_result import CapabilityResult

if TYPE_CHECKING:
    from ..query_engine import QueryEngine


class DataQueryCapability:
    """对 QueryEngine 的轻量能力封装。"""

    def __init__(self, query_engine: QueryEngine):
        self.query_engine = query_engine

    def execute(self, question: str, route: dict) -> tuple[object, CapabilityResult]:
        result = self.query_engine.answer(question, plan=route)
        return result, result.to_capability_result()
