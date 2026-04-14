"""查询 playbook 路由实现。

模块提供两层能力：
- 静态规则路由（可离线、稳定兜底）
- 向量检索路由（LlamaIndex）+ 守卫规则

目标是把用户问题快速映射到更具体的农业查询类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Protocol


DEFAULT_QUERY_PLAYBOOKS: list[dict] = [
    {
        "query_type": "pest_overview",
        "title": "虫情地区概览",
        "domain": "pest",
        "description": "适用于询问某个地区一段时间内的虫情情况、整体表现、概况。",
        "cues": ["虫情", "虫害", "情况", "概况", "整体", "怎么样", "如何"],
        "examples": [
            "给我过去五个月徐州的虫害情况",
            "南京最近一个月虫情怎么样",
            "徐州市虫情整体表现如何",
        ],
    },
    {
        "query_type": "soil_overview",
        "title": "墒情地区概览",
        "domain": "soil",
        "description": "适用于询问某个地区一段时间内的墒情情况、整体表现、概况。",
        "cues": ["墒情", "缺水", "情况", "概况", "整体", "怎么样", "如何"],
        "examples": [
            "给我过去五个月徐州的墒情情况",
            "南京最近一个月墒情怎么样",
            "徐州市墒情整体表现如何",
        ],
    },
    {
        "query_type": "pest_top",
        "title": "虫情严重地区排行",
        "domain": "pest",
        "description": "适用于询问哪些地方虫害最重、虫情最厉害、虫子最多。",
        "cues": ["虫情", "虫害", "害虫", "虫子", "最厉害", "最严重", "最多"],
        "examples": [
            "近三周虫情最严重的地方是哪里",
            "哪些地区虫害最厉害",
            "最近虫子最多的是哪里",
        ],
    },
    {
        "query_type": "soil_top",
        "title": "墒情异常地区排行",
        "domain": "soil",
        "description": "适用于询问哪里最缺水、低墒最严重、墒情异常最明显。",
        "cues": ["墒情", "低墒", "高墒", "缺水", "太干", "干旱", "异常", "最厉害", "最严重"],
        "examples": [
            "过去五个月缺水最厉害的地方是哪里",
            "低墒最严重的是哪些地区",
            "最近哪里墒情异常最明显",
        ],
    },
    {
        "query_type": "pest_trend",
        "title": "虫情趋势分析",
        "domain": "pest",
        "description": "适用于询问虫情走势、波动、变化趋势。",
        "cues": ["虫情", "虫害", "走势", "走向", "波动", "变化", "趋势"],
        "examples": [
            "南京近三周虫害走势怎么样",
            "徐州虫情变化趋势如何",
            "最近一个月虫情波动明显吗",
        ],
    },
    {
        "query_type": "soil_trend",
        "title": "墒情趋势分析",
        "domain": "soil",
        "description": "适用于询问墒情变化、缺水走势、土壤含水趋势。",
        "cues": ["墒情", "缺水", "含水", "走势", "走向", "波动", "变化", "趋势"],
        "examples": [
            "最近一个月墒情走势怎么样",
            "南京缺水变化趋势如何",
            "土壤含水波动明显吗",
        ],
    },
    {
        "query_type": "joint_risk",
        "title": "虫情与低墒联合风险",
        "domain": "mixed",
        "description": "适用于询问既有虫情又缺水、虫害和低墒叠加的高风险地区。",
        "cues": ["虫情", "虫害", "低墒", "缺水", "同时", "而且", "叠加", "联合风险"],
        "examples": [
            "哪些地方虫情高而且缺水更明显",
            "同时有虫害和低墒的地区有哪些",
            "虫情和墒情叠加风险最大的地方",
        ],
    },
]


class QueryPlaybookBackend(Protocol):
    """可插拔检索后端协议。"""

    def search(self, question: str, limit: int = 1, context: dict | None = None) -> List[dict]:
        """按问题和上下文返回最相关的 playbook 列表。"""
        ...


@dataclass
class StaticQueryPlaybookRouter:
    """基于关键词与意图特征打分的静态路由器。"""

    playbooks: List[dict] = field(default_factory=lambda: [dict(item) for item in DEFAULT_QUERY_PLAYBOOKS])
    minimum_score: float = 4.0

    def search(self, question: str, limit: int = 1, context: dict | None = None) -> List[dict]:
        """返回得分最高的 playbook 结果列表。"""
        scored: list[tuple[float, dict]] = []
        for playbook in self.playbooks:
            score, matched_terms = self._score_playbook(question, playbook, context=context)
            if score < self.minimum_score:
                continue
            enriched = dict(playbook)
            enriched["intent"] = "data_query"
            enriched["matched_terms"] = matched_terms
            enriched["score"] = round(score, 4)
            enriched["reason"] = playbook.get("title") or playbook.get("query_type")
            enriched["retrieval_engine"] = "static"
            scored.append((score, enriched))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [result for _, result in scored[:limit]]

    def route(self, question: str, context: dict | None = None) -> dict:
        """便捷接口：仅返回最佳单条结果。"""
        results = self.search(question, limit=1, context=context)
        return results[0] if results else {}

    def _score_playbook(self, question: str, playbook: dict, context: dict | None = None) -> tuple[float, list[str]]:
        """计算单个 playbook 与问题的匹配得分。"""
        q = (question or "").strip()
        context = dict(context or {})
        matched_terms = self._matched_terms_for_question(q, playbook)
        score = 0.0
        trend_tokens = ["走势", "走向", "波动", "变化", "趋势"]
        overview_tokens = ["情况", "概况", "整体", "总体", "表现", "怎么样", "如何"]

        if not self._has_domain_signal(q, playbook, context=context, matched_terms=matched_terms):
            # 先做领域门控，避免“趋势词命中”把问题误路由到错误领域。
            return 0.0, []

        for cue in matched_terms:
            score += 3.0

        for token in self._intent_tokens(playbook):
            if token in q and token not in matched_terms:
                matched_terms.append(token)
                score += 1.0

        query_type = str(playbook.get("query_type") or "")
        if query_type.endswith("_trend") and any(token in q for token in trend_tokens):
            score += 3.0
        if query_type.endswith("_trend") and any(token in q for token in overview_tokens):
            score += 0.5
        if query_type.endswith("_overview") and any(token in q for token in overview_tokens):
            score += 3.0
        if query_type.endswith("_overview") and any(token in q for token in trend_tokens):
            score -= 4.0
        if query_type.endswith("_top") and any(token in q for token in ["哪里", "哪儿", "地方", "地区", "最厉害", "最严重", "最多"]):
            score += 2.0
        if query_type == "joint_risk":
            if any(token in q for token in ["而且", "同时", "又", "叠加", "联合"]):
                score += 3.0
            if "虫" in q and any(token in q for token in ["缺水", "低墒", "干旱", "太干"]):
                score += 3.0

        domain = str(context.get("domain") or "")
        if domain and domain == playbook.get("domain"):
            score += 2.0

        return score, matched_terms

    @staticmethod
    def _matched_terms_for_question(question: str, playbook: dict) -> list[str]:
        """提取问题中命中的 cue 词。"""
        q = question or ""
        matched: list[str] = []
        for cue in playbook.get("cues", []):
            if cue and cue in q and cue not in matched:
                matched.append(cue)
        return matched

    @staticmethod
    def _has_domain_signal(question: str, playbook: dict, context: dict | None = None, matched_terms: list[str] | None = None) -> bool:
        """判断问题与 playbook 领域是否一致。"""
        q = question or ""
        context = dict(context or {})
        matched_terms = list(matched_terms or [])
        domain = str(playbook.get("domain") or "")

        if context.get("domain") in {"pest", "soil", "mixed"} and context.get("domain") == domain:
            return True

        if domain == "pest":
            return any(token in q for token in ["虫情", "虫害", "害虫", "虫子"]) or any(
                any(token in term for token in ["虫", "害虫"]) for term in matched_terms
            )
        if domain == "soil":
            return any(token in q for token in ["墒情", "低墒", "高墒", "缺水", "干旱", "土壤", "含水"]) or any(
                any(token in term for token in ["墒", "缺水", "干旱", "土壤", "含水"]) for term in matched_terms
            )
        if domain == "mixed":
            has_pest = any(token in q for token in ["虫情", "虫害", "害虫", "虫子"])
            has_soil = any(token in q for token in ["墒情", "低墒", "高墒", "缺水", "干旱", "土壤", "含水"])
            return has_pest and has_soil
        return False

    @staticmethod
    def _intent_tokens(playbook: dict) -> list[str]:
        """从 playbook 文本中抽取可辅助打分的意图词。"""
        tokens: list[str] = []
        for text in [playbook.get("title"), playbook.get("description"), *(playbook.get("examples") or [])]:
            if not isinstance(text, str):
                continue
            for token in [
                "虫情",
                "虫害",
                "害虫",
                "虫子",
                "墒情",
                "低墒",
                "高墒",
                "缺水",
                "干旱",
                "走势",
                "波动",
                "变化",
                "趋势",
                "联合风险",
            ]:
                if token in text and token not in tokens:
                    tokens.append(token)
        return tokens


@dataclass
class LlamaIndexQueryPlaybookRouter:
    """向量检索优先、静态路由兜底的混合路由器。"""

    backend: QueryPlaybookBackend | None = None
    fallback: StaticQueryPlaybookRouter = field(default_factory=StaticQueryPlaybookRouter)

    def search(self, question: str, limit: int = 1, context: dict | None = None) -> List[dict]:
        """优先尝试后端检索，失败时回退到静态路由。"""
        fallback_results = self._fallback_results(question, limit=limit, context=context)
        if self.backend is None:
            return fallback_results
        try:
            recall_limit = max(limit * 3, 5)
            results = self.backend.search(question, limit=recall_limit, context=context)
            if results:
                reranked = self._rerank_results(question, results, limit=limit, context=context)
                top_score = max(float(item.get("score") or 0.0) for item in results)
                if top_score >= 0.35:
                    guarded = self._apply_guardrails(question, reranked, fallback_results, context=context)
                    if guarded:
                        return guarded[:limit]
        except Exception:
            pass
        return fallback_results

    def route(self, question: str, context: dict | None = None) -> dict:
        """便捷接口：仅返回最佳单条结果。"""
        results = self.search(question, limit=1, context=context)
        return results[0] if results else {}

    def _fallback_results(self, question: str, limit: int, context: dict | None) -> List[dict]:
        """给静态兜底结果打上来源标记。"""
        results = self.fallback.search(question, limit=limit, context=context)
        return [self._mark_fallback(item) for item in results]

    def _rerank_results(self, question: str, results: List[dict], limit: int, context: dict | None = None) -> List[dict]:
        """把向量召回的多个候选再按查询相关性重排。"""
        reranked: list[dict] = []
        for recall_rank, item in enumerate(results, start=1):
            candidate = dict(item)
            static_score, matched_terms = self.fallback._score_playbook(question, candidate, context=context)
            prior_score = min(max(float(candidate.get("score") or 0.0), 0.0), 1.0) * 4.0
            candidate["matched_terms"] = self._dedupe_terms(
                [term for term in candidate.get("matched_terms", []) or [] if isinstance(term, str)] + matched_terms
            )
            candidate["recall_rank"] = int(candidate.get("retrieval_rank") or recall_rank)
            candidate["rerank_score"] = round(static_score + prior_score, 4)
            candidate["retrieval_reranked"] = True
            reranked.append(candidate)

        reranked.sort(
            key=lambda item: (
                -float(item.get("rerank_score") or 0.0),
                -float(item.get("score") or 0.0),
                int(item.get("recall_rank") or 0),
            )
        )
        for retrieval_rank, item in enumerate(reranked[:limit], start=1):
            item["retrieval_rank"] = retrieval_rank
        return reranked[:limit]

    def _apply_guardrails(
        self,
        question: str,
        backend_results: List[dict],
        fallback_results: List[dict],
        context: dict | None = None,
    ) -> List[dict]:
        """对向量检索结果做安全校正，必要时回退静态结果。"""
        if not backend_results:
            return fallback_results

        best_backend = dict(backend_results[0])
        best_fallback = dict(fallback_results[0]) if fallback_results else {}

        if not StaticQueryPlaybookRouter._has_domain_signal(
            question,
            best_backend,
            context=context,
            matched_terms=best_backend.get("matched_terms"),
        ):
            # 若领域不一致，优先选择保守的静态结果。
            return fallback_results

        if self._is_mixed_domain_question(question):
            if best_backend.get("query_type") != "joint_risk" and best_fallback.get("query_type") == "joint_risk":
                return fallback_results

        backend_specificity = self._query_specificity(str(best_backend.get("query_type") or ""))
        fallback_specificity = self._query_specificity(str(best_fallback.get("query_type") or "")) if best_fallback else 0
        if best_fallback and fallback_specificity > backend_specificity:
            return fallback_results

        return backend_results

    @staticmethod
    def _is_mixed_domain_question(question: str) -> bool:
        """识别“虫情+墒情”联合问题。"""
        q = question or ""
        has_pest = any(token in q for token in ["虫情", "虫害", "害虫", "虫子"])
        has_soil = any(token in q for token in ["墒情", "低墒", "高墒", "缺水", "干旱", "土壤", "含水"])
        return has_pest and has_soil

    @staticmethod
    def _query_specificity(query_type: str) -> int:
        """估计 query_type 粒度，数值越大越具体。"""
        if query_type == "joint_risk":
            return 4
        if query_type.endswith("_trend"):
            return 3
        if query_type.endswith("_overview"):
            return 3
        if query_type.endswith("_top"):
            return 2
        if query_type == "structured_agri":
            return 1
        return 0

    @staticmethod
    def _mark_fallback(item: dict) -> dict:
        """标记结果来自静态回退链路。"""
        enriched = dict(item)
        enriched["retrieval_engine"] = "static-fallback"
        return enriched

    @staticmethod
    def _dedupe_terms(terms: list[str]) -> list[str]:
        """保持 matched_terms 顺序稳定，同时避免重复。"""
        deduped: list[str] = []
        for term in terms:
            normalized = str(term or "").strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped


class LlamaIndexQueryPlaybookBackend:
    """LlamaIndex 向量检索后端。"""

    def __init__(
        self,
        playbooks: List[dict],
        openai_api_key: str,
        embedding_model: str = "text-embedding-3-small",
    ):
        from llama_index.core import VectorStoreIndex
        from llama_index.core.schema import TextNode
        from llama_index.embeddings.openai import OpenAIEmbedding

        self._playbooks = [dict(item) for item in playbooks]
        self._lookup = {
            self._node_id_for(index, item): dict(item)
            for index, item in enumerate(self._playbooks)
        }

        nodes: list[TextNode] = []
        for index, playbook in enumerate(self._playbooks):
            node_id = self._node_id_for(index, playbook)
            nodes.append(
                TextNode(
                    id_=node_id,
                    text=self._node_text(playbook),
                    metadata={
                        "query_type": playbook.get("query_type", ""),
                        "domain": playbook.get("domain", ""),
                        "title": playbook.get("title", ""),
                    },
                )
            )

        embed_model = OpenAIEmbedding(api_key=openai_api_key, model=embedding_model)
        self._index = VectorStoreIndex(nodes, embed_model=embed_model)

    def search(self, question: str, limit: int = 1, context: dict | None = None) -> List[dict]:
        """执行向量检索并组装标准化结果。"""
        query = self._build_query(question, context=context)
        retriever = self._index.as_retriever(similarity_top_k=max(limit, 1))
        nodes = retriever.retrieve(query)
        results: list[dict] = []
        for rank, node in enumerate(nodes, start=1):
            playbook = dict(self._lookup.get(node.node.node_id, {}))
            if not playbook:
                continue
            playbook["intent"] = "data_query"
            playbook["reason"] = playbook.get("title") or playbook.get("query_type")
            playbook["retrieval_engine"] = "llamaindex"
            playbook["score"] = round(float(getattr(node, "score", 0.0) or 0.0), 4)
            playbook["retrieval_rank"] = rank
            playbook["matched_terms"] = StaticQueryPlaybookRouter._matched_terms_for_question(question, playbook)
            results.append(playbook)
        return results

    @staticmethod
    def _node_id_for(index: int, playbook: dict) -> str:
        """构造稳定节点 ID，方便检索结果回查。"""
        return f"playbook::{index}::{playbook.get('query_type', f'unknown-{index}')}"

    @staticmethod
    def _node_text(playbook: dict) -> str:
        """把 playbook 拼成向量化文本。"""
        cues = " ".join(playbook.get("cues", []) or [])
        examples = "\n".join(playbook.get("examples", []) or [])
        return "\n".join(
            [
                f"类型: {playbook.get('query_type', '')}",
                f"标题: {playbook.get('title', '')}",
                f"领域: {playbook.get('domain', '')}",
                f"说明: {playbook.get('description', '')}",
                f"线索: {cues}",
                f"示例:\n{examples}",
            ]
        )

    @staticmethod
    def _build_query(question: str, context: dict | None = None) -> str:
        """构造检索 query，附带领域与地区上下文。"""
        context = dict(context or {})
        domain = str(context.get("domain") or "")
        region = str(context.get("region_name") or "")
        parts = [question]
        if domain:
            parts.append(f"领域: {domain}")
        if region:
            parts.append(f"地区: {region}")
        parts.append("请匹配最适合的农业历史查询类型。")
        return "\n".join(part for part in parts if part)


def create_query_playbook_router(
    backend: str = "llamaindex",
    openai_api_key: str = "",
    embedding_model: str = "text-embedding-3-small",
) -> StaticQueryPlaybookRouter | LlamaIndexQueryPlaybookRouter:
    """按配置创建 playbook 路由器实例。"""
    normalized_backend = str(backend or "llamaindex").strip().lower()
    if normalized_backend != "llamaindex":
        return StaticQueryPlaybookRouter()

    retrieval_backend: QueryPlaybookBackend | None = None
    if openai_api_key:
        try:
            retrieval_backend = LlamaIndexQueryPlaybookBackend(
                playbooks=[dict(item) for item in DEFAULT_QUERY_PLAYBOOKS],
                openai_api_key=openai_api_key,
                embedding_model=embedding_model,
            )
        except Exception:
            retrieval_backend = None
    return LlamaIndexQueryPlaybookRouter(backend=retrieval_backend)
