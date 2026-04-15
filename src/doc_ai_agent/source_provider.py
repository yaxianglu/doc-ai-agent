"""知识源检索层：支持静态、LlamaIndex 与 Qdrant 多后端检索。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Protocol

EXPLANATION_QUERY_TERMS = ("为什么", "原因", "依据", "为何")
ADVICE_QUERY_TERMS = ("建议", "怎么", "如何", "处置", "处理", "防治", "防控", "怎么办")
FORECAST_QUERY_TERMS = ("未来", "预测", "趋势", "下周", "接下来")
EXPLANATION_SOURCE_TERMS = ("原因", "依据", "诱因", "成因", "监测", "复核")
ADVICE_SOURCE_TERMS = ("建议", "处置", "处理", "防控", "防治", "措施", "排水", "补灌", "巡查")
FORECAST_SOURCE_TERMS = ("趋势", "预测", "未来", "预警")


class RetrievalBackend(Protocol):
    """检索后端协议：统一 search 接口，便于替换底层实现。"""
    def search(self, question: str, limit: int = 3, context: dict | None = None) -> List[dict]:
        """根据问题与上下文返回候选知识源。"""
        ...


def _enrich_result(item: dict, *, engine: str, backend: str, strategy: str) -> dict:
    """为检索结果补充后端、策略和引擎元信息。"""
    enriched = dict(item)
    enriched["retrieval_engine"] = engine
    enriched["retrieval_backend"] = backend
    enriched["retrieval_strategy"] = strategy
    return enriched


def _dedupe_terms(terms: list[str]) -> list[str]:
    """按首次出现顺序去重，保持匹配词稳定输出。"""
    seen: list[str] = []
    for term in terms:
        normalized = str(term or "").strip()
        if normalized and normalized not in seen:
            seen.append(normalized)
    return seen


def _task_hints(question: str) -> dict:
    """从问题中提取解释/建议/预测等检索意图提示。"""
    text = str(question or "")
    return {
        "explanation": any(term in text for term in EXPLANATION_QUERY_TERMS),
        "advice": any(term in text for term in ADVICE_QUERY_TERMS),
        "forecast": any(term in text for term in FORECAST_QUERY_TERMS),
    }


def _context_terms(context: dict | None) -> list[str]:
    """提取上下文字段中的稳定检索词，例如地区名称。"""
    context = dict(context or {})
    region_name = str(context.get("region_name") or "").strip()
    if not region_name:
        return []
    terms = [region_name]
    shortened = region_name.rstrip("市县区镇乡旗盟")
    if len(shortened) >= 2:
        terms.append(shortened)
    return _dedupe_terms(terms)


def _match_terms_in_item(item: dict, keywords: list[str]) -> list[str]:
    """重新计算候选文档与问题关键词的命中情况。"""
    title = f"{item.get('title', '')}"
    snippet = f"{item.get('snippet', '')}"
    tags = " ".join(item.get("tags", []) or [])
    haystack = f"{title} {snippet} {tags}"
    existing = [term for term in item.get("matched_terms", []) or [] if isinstance(term, str)]
    return _dedupe_terms(existing + [keyword for keyword in keywords if keyword in haystack])


def _rerank_score(item: dict, *, question: str, context: dict | None, recall_rank: int) -> float:
    """基于查询相关性重算候选得分，用于召回后的稳定 rerank。"""
    context = dict(context or {})
    keywords = _dedupe_terms(StaticSourceProvider._keywords(question, context=context) + _context_terms(context))
    hints = _task_hints(question)
    title = f"{item.get('title', '')}"
    snippet = f"{item.get('snippet', '')}"
    tags = " ".join(item.get("tags", []) or [])
    haystack = f"{title} {snippet} {tags}"

    title_hits = sum(1 for keyword in keywords if keyword in title)
    body_hits = sum(1 for keyword in keywords if keyword in snippet)
    tag_hits = sum(1 for keyword in keywords if keyword in tags)

    domain = str(context.get("domain") or "")
    item_domain = str(item.get("domain") or "")
    domain_score = 0.0
    if domain:
        if item_domain == domain:
            domain_score = 4.0
        elif item_domain:
            domain_score = -3.0

    explanation_score = 0.0
    if hints["explanation"]:
        explanation_score += 3.0 if any(term in haystack for term in EXPLANATION_SOURCE_TERMS) else 0.0
        explanation_score += 1.0 if any(term in title for term in EXPLANATION_SOURCE_TERMS) else 0.0

    advice_score = 0.0
    if hints["advice"]:
        advice_score += 3.0 if any(term in haystack for term in ADVICE_SOURCE_TERMS) else 0.0
        advice_score += 1.0 if any(term in title for term in ADVICE_SOURCE_TERMS) else 0.0

    forecast_score = 0.0
    if hints["forecast"]:
        forecast_score += 2.0 if any(term in haystack for term in FORECAST_SOURCE_TERMS) else 0.0
        forecast_score += 1.0 if any(term in title for term in FORECAST_SOURCE_TERMS) else 0.0

    prior_score = min(max(float(item.get("score") or 0.0), 0.0), 20.0) * 0.45
    recall_prior = max(0.0, 1.2 - (max(recall_rank, 1) - 1) * 0.15)

    return round(
        title_hits * 2.5
        + body_hits * 1.5
        + tag_hits * 1.0
        + domain_score
        + explanation_score
        + advice_score
        + forecast_score
        + prior_score
        + recall_prior,
        4,
    )


def _rerank_results(results: list[dict], *, question: str, limit: int, context: dict | None) -> list[dict]:
    """对召回结果做二次排序，并补充 rerank 元信息。"""
    if not results:
        return []
    keywords = _dedupe_terms(StaticSourceProvider._keywords(question, context=context) + _context_terms(context))
    reranked: list[dict] = []
    for recall_rank, item in enumerate(results, start=1):
        enriched = dict(item)
        matched_terms = _match_terms_in_item(enriched, keywords)
        enriched["matched_terms"] = matched_terms
        enriched["recall_rank"] = int(enriched.get("retrieval_rank") or recall_rank)
        enriched["rerank_score"] = _rerank_score(enriched, question=question, context=context, recall_rank=enriched["recall_rank"])
        enriched["retrieval_reranked"] = True
        reranked.append(enriched)

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


@dataclass
class StaticSourceProvider:
    """静态关键词检索实现，适合作为零依赖默认后端。"""
    items: List[dict]

    def backend_label(self) -> str:
        return "Static"

    def search(self, question: str, limit: int = 3, context: dict | None = None) -> List[dict]:
        """执行静态关键词检索，并按匹配得分排序。"""
        keywords = self._keywords(question, context=context)
        domain = str((context or {}).get("domain") or "")
        if not keywords:
            return [_enrich_result(dict(item), engine="static", backend="static", strategy="keyword-match") for item in self.items[:limit]]

        scored = []
        for item in self.items:
            title = f"{item.get('title', '')}"
            snippet = f"{item.get('snippet', '')}"
            tags = " ".join(item.get("tags", []) or [])
            haystack = f"{title} {snippet} {tags}"
            matched_terms = [keyword for keyword in keywords if keyword in haystack]
            score = 0
            for term in matched_terms:
                if term in title:
                    score += 3
                elif term in tags:
                    score += 2
                else:
                    score += 1
            if domain and item.get("domain") == domain:
                score += 4
            if score > 0:
                enriched = dict(item)
                enriched["matched_terms"] = matched_terms
                enriched["score"] = score
                scored.append((score, enriched))

        scored.sort(key=lambda item: item[0], reverse=True)
        reranked = _rerank_results([result for _, result in scored], question=question, limit=limit, context=context)
        return [_enrich_result(result, engine="static", backend="static", strategy="keyword-match") for result in reranked]

    @staticmethod
    def _keywords(text: str, context: dict | None = None) -> List[str]:
        vocab = ["台风", "小麦", "虫情", "暴雨", "排水", "病害", "预警", "处置"]
        if context and context.get("domain") == "soil":
            vocab.extend(["墒情", "补灌", "低墒", "高墒"])
        if context and context.get("domain") == "pest":
            vocab.extend(["防控", "阈值", "迁飞", "虫害", "防治"])
        seen = []
        for word in vocab:
            if word in text and word not in seen:
                seen.append(word)
        chinese_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        for chunk in chinese_chunks:
            for index in range(0, len(chunk) - 1):
                token = chunk[index : index + 2]
                if token not in seen:
                    seen.append(token)
                if len(seen) >= 12:
                    return seen
        return seen


@dataclass
class LlamaIndexSourceProvider:
    """LlamaIndex 外层包装：失败时自动回退到静态检索。"""
    items: List[dict]
    backend: RetrievalBackend | None = None

    def __post_init__(self) -> None:
        self._fallback = StaticSourceProvider(self.items)

    def backend_label(self) -> str:
        return "LlamaIndex" if self.backend is not None else "StaticFallback"

    def search(self, question: str, limit: int = 3, context: dict | None = None) -> List[dict]:
        """优先调用 LlamaIndex 检索，失败时回退静态检索。"""
        if self.backend is None:
            return self._fallback_results(question, limit=limit, context=context)
        try:
            # 向量检索失败时不要中断主流程，直接降级到静态检索。
            recall_limit = max(limit * 3, 5)
            result = self.backend.search(question, limit=recall_limit, context=context)
            if result:
                return _rerank_results(result, question=question, limit=limit, context=context)
        except Exception:
            pass
        return self._fallback_results(question, limit=limit, context=context)

    def _fallback_results(self, question: str, limit: int, context: dict | None) -> List[dict]:
        results = self._fallback.search(question, limit=limit, context=context)
        return [_enrich_result(item, engine="static-fallback", backend="llamaindex-fallback", strategy="keyword-fallback") for item in results]


@dataclass
class QdrantSourceProvider:
    """Qdrant 外层包装：优先语义检索，失败时关键词兜底。"""
    items: List[dict]
    backend: RetrievalBackend | None = None

    def __post_init__(self) -> None:
        self._fallback = StaticSourceProvider(self.items)

    def backend_label(self) -> str:
        return "Qdrant" if self.backend is not None else "StaticFallback"

    def search(self, question: str, limit: int = 3, context: dict | None = None) -> List[dict]:
        """优先调用 Qdrant 语义检索，失败时回退静态检索。"""
        if self.backend is None:
            return self._fallback_results(question, limit=limit, context=context)
        try:
            recall_limit = max(limit * 3, 5)
            result = self.backend.search(question, limit=recall_limit, context=context)
            if result:
                return [
                    _enrich_result(
                        item,
                        engine=str(item.get("retrieval_engine") or "qdrant"),
                        backend=str(item.get("retrieval_backend") or "qdrant"),
                        strategy=str(item.get("retrieval_strategy") or "semantic-vector"),
                    )
                    for item in _rerank_results(result, question=question, limit=limit, context=context)
                ]
        except Exception:
            pass
        return self._fallback_results(question, limit=limit, context=context)

    def _fallback_results(self, question: str, limit: int, context: dict | None) -> List[dict]:
        results = self._fallback.search(question, limit=limit, context=context)
        return [_enrich_result(item, engine="static-fallback", backend="qdrant-fallback", strategy="keyword-fallback") for item in results]


class LlamaIndexRetrievalBackend:
    """LlamaIndex 向量检索后端。"""
    def __init__(self, items: List[dict], openai_api_key: str, embedding_model: str = "text-embedding-3-small"):
        from llama_index.core import VectorStoreIndex
        from llama_index.core.schema import TextNode
        from llama_index.embeddings.openai import OpenAIEmbedding

        self._items = [dict(item) for item in items]
        self._lookup = {self._node_id_for(index, item): dict(item) for index, item in enumerate(self._items)}

        nodes: list[TextNode] = []
        for index, item in enumerate(self._items):
            node_id = self._node_id_for(index, item)
            content = self._node_text(item)
            nodes.append(
                TextNode(
                    id_=node_id,
                    text=content,
                    metadata={
                        "title": item.get("title", ""),
                        "domain": item.get("domain", ""),
                        "url": item.get("url", ""),
                    },
                )
            )

        embed_model = OpenAIEmbedding(api_key=openai_api_key, model=embedding_model)
        self._index = VectorStoreIndex(nodes, embed_model=embed_model)

    def search(self, question: str, limit: int = 3, context: dict | None = None) -> List[dict]:
        """执行 LlamaIndex 检索并补充统一结果元信息。"""
        query = self._build_query(question, context=context)
        retriever = self._index.as_retriever(similarity_top_k=max(limit, 1))
        nodes = retriever.retrieve(query)
        results: list[dict] = []
        for rank, node in enumerate(nodes, start=1):
            source = dict(self._lookup.get(node.node.node_id, {}))
            if not source:
                continue
            source["retrieval_engine"] = "llamaindex"
            source["retrieval_backend"] = "llamaindex"
            source["retrieval_strategy"] = "semantic-vector"
            source["score"] = round(float(getattr(node, "score", 0.0) or 0.0), 4)
            source["matched_terms"] = StaticSourceProvider._keywords(query, context=context)
            source["retrieval_rank"] = rank
            results.append(source)
        return results

    @staticmethod
    def _node_id_for(index: int, item: dict) -> str:
        title = str(item.get("title") or f"source-{index}")
        return f"source::{index}::{title}"

    @staticmethod
    def _node_text(item: dict) -> str:
        tags = " ".join(item.get("tags", []) or [])
        return "\n".join(
            [
                f"标题: {item.get('title', '')}",
                f"领域: {item.get('domain', '')}",
                f"摘要: {item.get('snippet', '')}",
                f"标签: {tags}",
                f"链接: {item.get('url', '')}",
            ]
        )

    @staticmethod
    def _build_query(question: str, context: dict | None = None) -> str:
        context = dict(context or {})
        domain = str(context.get("domain") or "")
        region = str(context.get("region_name") or "")
        parts = [question]
        if domain:
            parts.append(f"领域: {domain}")
        if region:
            parts.append(f"地区: {region}")
        return "\n".join(part for part in parts if part)


class QdrantRetrievalBackend:
    """Qdrant 向量检索后端。"""
    def __init__(
        self,
        items: List[dict],
        openai_api_key: str,
        embedding_model: str = "text-embedding-3-small",
        path: str = "./data/qdrant",
        collection_name: str = "knowledge_sources",
    ):
        from openai import OpenAI
        from qdrant_client import QdrantClient
        from qdrant_client.http import models

        self._items = [dict(item) for item in items]
        self._lookup: dict[int, dict] = {}
        self._client = QdrantClient(path=path)
        self._models = models
        self._collection_name = collection_name
        self._openai = OpenAI(api_key=openai_api_key)
        self._embedding_model = embedding_model

        if not self._items:
            return

        documents = [self._node_text(item) for item in self._items]
        embeddings = self._embed_texts(documents)
        if not embeddings:
            return

        vector_size = len(embeddings[0])
        existing_collections = {item.name for item in self._client.get_collections().collections}
        if collection_name not in existing_collections:
            self._client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            )

        points = []
        for index, (item, vector) in enumerate(zip(self._items, embeddings), start=1):
            self._lookup[index] = dict(item)
            points.append(
                models.PointStruct(
                    id=index,
                    vector=vector,
                    payload={
                        "title": item.get("title", ""),
                        "domain": item.get("domain", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("snippet", ""),
                    },
                )
            )
        self._client.upsert(collection_name=collection_name, points=points)

    def _embed_texts(self, texts: List[str]) -> List[list[float]]:
        if not texts:
            return []
        response = self._openai.embeddings.create(model=self._embedding_model, input=texts)
        return [list(item.embedding) for item in response.data]

    def search(self, question: str, limit: int = 3, context: dict | None = None) -> List[dict]:
        """执行 Qdrant 检索并返回标准化知识源列表。"""
        if not self._items:
            return []
        query = self._build_query(question, context=context)
        embedding = self._embed_texts([query])[0]
        response = self._client.query_points(collection_name=self._collection_name, query=embedding, limit=max(limit, 1))
        points = getattr(response, "points", []) or []
        results: list[dict] = []
        for rank, point in enumerate(points, start=1):
            source = dict(self._lookup.get(int(getattr(point, "id", 0) or 0), {}))
            if not source:
                continue
            source["retrieval_engine"] = "qdrant"
            source["retrieval_backend"] = "qdrant"
            source["retrieval_strategy"] = "semantic-vector"
            source["score"] = round(float(getattr(point, "score", 0.0) or 0.0), 4)
            source["matched_terms"] = StaticSourceProvider._keywords(query, context=context)
            source["retrieval_rank"] = rank
            results.append(source)
        return results

    @staticmethod
    def _node_text(item: dict) -> str:
        tags = " ".join(item.get("tags", []) or [])
        return "\n".join(
            [
                f"标题: {item.get('title', '')}",
                f"领域: {item.get('domain', '')}",
                f"摘要: {item.get('snippet', '')}",
                f"标签: {tags}",
                f"链接: {item.get('url', '')}",
            ]
        )

    @staticmethod
    def _build_query(question: str, context: dict | None = None) -> str:
        context = dict(context or {})
        domain = str(context.get("domain") or "")
        region = str(context.get("region_name") or "")
        parts = [question]
        if domain:
            parts.append(f"领域: {domain}")
        if region:
            parts.append(f"地区: {region}")
        return "\n".join(part for part in parts if part)


def create_source_provider(
    items: List[dict],
    backend: str = "static",
    openai_api_key: str = "",
    embedding_model: str = "text-embedding-3-small",
    qdrant_path: str = "./data/qdrant",
    qdrant_collection: str = "knowledge_sources",
) -> StaticSourceProvider | LlamaIndexSourceProvider | QdrantSourceProvider:
    """按配置创建检索 Provider（static/llamaindex/qdrant）。"""
    normalized_backend = str(backend or "static").strip().lower()
    if normalized_backend not in {"llamaindex", "qdrant"}:
        return StaticSourceProvider(items)

    retrieval_backend: RetrievalBackend | None = None
    if openai_api_key:
        try:
            if normalized_backend == "llamaindex":
                retrieval_backend = LlamaIndexRetrievalBackend(
                    items=items,
                    openai_api_key=openai_api_key,
                    embedding_model=embedding_model,
                )
            else:
                retrieval_backend = QdrantRetrievalBackend(
                    items=items,
                    openai_api_key=openai_api_key,
                    embedding_model=embedding_model,
                    path=qdrant_path,
                    collection_name=qdrant_collection,
                )
        except Exception:
            retrieval_backend = None

    if normalized_backend == "qdrant":
        return QdrantSourceProvider(items=items, backend=retrieval_backend)
    return LlamaIndexSourceProvider(items=items, backend=retrieval_backend)


def load_static_sources(path: str) -> StaticSourceProvider:
    """从 JSON 文件加载静态知识源列表。"""
    p = Path(path)
    if not p.exists():
        return StaticSourceProvider([])
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return StaticSourceProvider([])
    return StaticSourceProvider([item for item in data if isinstance(item, dict)])


def load_source_provider(
    path: str,
    backend: str = "static",
    openai_api_key: str = "",
    embedding_model: str = "text-embedding-3-small",
    qdrant_path: str = "./data/qdrant",
    qdrant_collection: str = "knowledge_sources",
) -> StaticSourceProvider | LlamaIndexSourceProvider | QdrantSourceProvider:
    """从目录与配置加载知识源 Provider。"""
    static_provider = load_static_sources(path)
    return create_source_provider(
        static_provider.items,
        backend=backend,
        openai_api_key=openai_api_key,
        embedding_model=embedding_model,
        qdrant_path=qdrant_path,
        qdrant_collection=qdrant_collection,
    )
