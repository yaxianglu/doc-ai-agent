from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Protocol


class RetrievalBackend(Protocol):
    def search(self, question: str, limit: int = 3, context: dict | None = None) -> List[dict]:
        ...


def _enrich_result(item: dict, *, engine: str, backend: str, strategy: str) -> dict:
    enriched = dict(item)
    enriched["retrieval_engine"] = engine
    enriched["retrieval_backend"] = backend
    enriched["retrieval_strategy"] = strategy
    return enriched


@dataclass
class StaticSourceProvider:
    items: List[dict]

    def search(self, question: str, limit: int = 3, context: dict | None = None) -> List[dict]:
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
        return [_enrich_result(result, engine="static", backend="static", strategy="keyword-match") for _, result in scored[:limit]]

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
    items: List[dict]
    backend: RetrievalBackend | None = None

    def __post_init__(self) -> None:
        self._fallback = StaticSourceProvider(self.items)

    def search(self, question: str, limit: int = 3, context: dict | None = None) -> List[dict]:
        if self.backend is None:
            return self._fallback_results(question, limit=limit, context=context)
        try:
            result = self.backend.search(question, limit=limit, context=context)
            if result:
                return result[:limit]
        except Exception:
            pass
        return self._fallback_results(question, limit=limit, context=context)

    def _fallback_results(self, question: str, limit: int, context: dict | None) -> List[dict]:
        results = self._fallback.search(question, limit=limit, context=context)
        return [_enrich_result(item, engine="static-fallback", backend="llamaindex-fallback", strategy="keyword-fallback") for item in results]


@dataclass
class QdrantSourceProvider:
    items: List[dict]
    backend: RetrievalBackend | None = None

    def __post_init__(self) -> None:
        self._fallback = StaticSourceProvider(self.items)

    def search(self, question: str, limit: int = 3, context: dict | None = None) -> List[dict]:
        if self.backend is None:
            return self._fallback_results(question, limit=limit, context=context)
        try:
            result = self.backend.search(question, limit=limit, context=context)
            if result:
                return [
                    _enrich_result(
                        item,
                        engine=str(item.get("retrieval_engine") or "qdrant"),
                        backend=str(item.get("retrieval_backend") or "qdrant"),
                        strategy=str(item.get("retrieval_strategy") or "semantic-vector"),
                    )
                    for item in result[:limit]
                ]
        except Exception:
            pass
        return self._fallback_results(question, limit=limit, context=context)

    def _fallback_results(self, question: str, limit: int, context: dict | None) -> List[dict]:
        results = self._fallback.search(question, limit=limit, context=context)
        return [_enrich_result(item, engine="static-fallback", backend="qdrant-fallback", strategy="keyword-fallback") for item in results]


class LlamaIndexRetrievalBackend:
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
    static_provider = load_static_sources(path)
    return create_source_provider(
        static_provider.items,
        backend=backend,
        openai_api_key=openai_api_key,
        embedding_model=embedding_model,
        qdrant_path=qdrant_path,
        qdrant_collection=qdrant_collection,
    )
