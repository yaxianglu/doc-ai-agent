"""统一 Query Parser：把请求理解层输出收口到 QueryDSL。"""

from __future__ import annotations

from .query_dsl import QueryDSL, query_dsl_from_understanding
from .request_understanding import RequestUnderstanding


class QueryParser:
    """规则优先的统一查询解析器。"""

    def __init__(self, understanding_engine: RequestUnderstanding | None = None):
        self.understanding_engine = understanding_engine or RequestUnderstanding()

    def parse(self, question: str, history: object = None, context: dict | None = None) -> QueryDSL:
        """解析问题并返回统一 QueryDSL。"""

        understanding = self.understanding_engine.analyze(question, history=history, context=context)
        return query_dsl_from_understanding(understanding)
