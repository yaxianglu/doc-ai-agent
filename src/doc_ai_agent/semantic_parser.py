"""统一语义解析编排器。

当前版本先提供一个最小可用的 orchestrator：
- 统一做基础归一化；
- 识别明显越界的问题；
- 输出 `SemanticParseResult`，供后续模块渐进接入。
"""

from __future__ import annotations

import re

from .entity_extraction import EntityExtractionService
from .semantic_parse import SemanticParseResult


class SemanticParser:
    """语义解析编排器。

    该类后续会逐步吸纳更多理解能力；当前先提供稳定的最小合同。
    """

    OUT_OF_SCOPE_WEATHER_PATTERN = re.compile(r"(天气|下雨|降雨|气温|温度|天气预报)")

    def __init__(self, backend=None, extractor: EntityExtractionService | None = None):
        self.backend = backend
        self.extractor = extractor or EntityExtractionService()

    def parse(self, question: str, context: dict | None = None) -> SemanticParseResult:
        """把原始问题解析为统一语义结果。"""
        del context  # 当前最小版本先保留接口，不消费上下文。
        normalized = str(question or "").strip()
        trace = ["normalize"]

        if self.OUT_OF_SCOPE_WEATHER_PATTERN.search(normalized):
            trace.append("ood")
            return SemanticParseResult(
                normalized_query=normalized,
                intent="advice",
                is_out_of_scope=True,
                fallback_reason="out_of_scope_capability",
                trace=trace,
            )

        return SemanticParseResult(
            normalized_query=normalized,
            intent="data_query" if "虫情" in normalized else "advice",
            trace=trace,
        )
