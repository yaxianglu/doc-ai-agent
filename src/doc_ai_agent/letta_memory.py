from __future__ import annotations

import json
import os
from typing import Protocol


def normalize_memory_snapshot(snapshot: dict | None) -> dict:
    payload = dict(snapshot or {})
    return {
        "memory_version": int(payload.get("memory_version") or 2),
        "domain": str(payload.get("domain") or ""),
        "region_name": str(payload.get("region_name") or ""),
        "query_type": str(payload.get("query_type") or ""),
        "window": dict(payload.get("window") or {}),
        "route": dict(payload.get("route") or {}),
        "forecast": dict(payload.get("forecast") or {}),
        "last_question": str(payload.get("last_question") or ""),
        "last_answer": str(payload.get("last_answer") or ""),
        "last_verified_answer": str(payload.get("last_verified_answer") or payload.get("last_answer") or ""),
        "pending_user_question": payload.get("pending_user_question"),
        "pending_clarification": payload.get("pending_clarification"),
        "user_preferences": dict(payload.get("user_preferences") or {}),
        "conversation_state": {
            "last_intent": str((payload.get("conversation_state") or {}).get("last_intent") or payload.get("intent") or ""),
            "last_answer_mode": str((payload.get("conversation_state") or {}).get("last_answer_mode") or payload.get("answer_mode") or ""),
            "last_clarification_reason": str((payload.get("conversation_state") or {}).get("last_clarification_reason") or payload.get("pending_clarification") or ""),
        },
    }


class MemoryStore(Protocol):
    def load(self, thread_id: str) -> dict:
        ...

    def remember(self, thread_id: str, snapshot: dict) -> None:
        ...

    def backend_label(self) -> str:
        ...


class LocalMemoryStore:
    def __init__(self, path: str):
        self.path = path

    def _load_all(self) -> dict:
        if not self.path or not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_all(self, data: dict) -> None:
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)

    def load(self, thread_id: str) -> dict:
        if not thread_id:
            return normalize_memory_snapshot({})
        return normalize_memory_snapshot(self._load_all().get(thread_id) or {})

    def remember(self, thread_id: str, snapshot: dict) -> None:
        if not thread_id:
            return
        data = self._load_all()
        data[thread_id] = normalize_memory_snapshot(snapshot)
        self._write_all(data)

    def backend_label(self) -> str:
        return "LocalMemory"


class LettaMemoryStore:
    def __init__(self, client, block_prefix: str = "doc-cloud-thread"):
        self.client = client
        self.block_prefix = block_prefix

    def _label(self, thread_id: str) -> str:
        return f"{self.block_prefix}:{thread_id}"

    def _find_block(self, thread_id: str):
        blocks = self.client.blocks.list(label=self._label(thread_id), limit=1)
        if not blocks:
            return None
        return list(blocks)[0]

    def load(self, thread_id: str) -> dict:
        if not thread_id:
            return normalize_memory_snapshot({})
        block = self._find_block(thread_id)
        if block is None:
            return normalize_memory_snapshot({})
        try:
            payload = json.loads(block.value or "{}")
        except json.JSONDecodeError:
            payload = {}
        return normalize_memory_snapshot(payload)

    def remember(self, thread_id: str, snapshot: dict) -> None:
        if not thread_id:
            return
        normalized = normalize_memory_snapshot(snapshot)
        payload = json.dumps(normalized, ensure_ascii=False)
        block = self._find_block(thread_id)
        if block is None:
            self.client.blocks.create(
                label=self._label(thread_id),
                value=payload,
                metadata={"thread_id": thread_id, "source": "doc-ai-agent"},
            )
            return
        self.client.blocks.update(block.id, value=payload)

    def backend_label(self) -> str:
        return "Letta"


class ResilientMemoryStore:
    def __init__(self, primary: MemoryStore | None, fallback: MemoryStore):
        self.primary = primary
        self.fallback = fallback
        self._last_backend = fallback.backend_label()

    def load(self, thread_id: str) -> dict:
        if self.primary is not None:
            try:
                snapshot = self.primary.load(thread_id)
                if snapshot:
                    self._last_backend = self.primary.backend_label()
                    return normalize_memory_snapshot(snapshot)
            except Exception:
                pass
        self._last_backend = self.fallback.backend_label()
        return normalize_memory_snapshot(self.fallback.load(thread_id))

    def remember(self, thread_id: str, snapshot: dict) -> None:
        normalized = normalize_memory_snapshot(snapshot)
        primary_ok = False
        if self.primary is not None:
            try:
                self.primary.remember(thread_id, normalized)
                primary_ok = True
            except Exception:
                primary_ok = False
        self.fallback.remember(thread_id, normalized)
        self._last_backend = self.primary.backend_label() if primary_ok and self.primary is not None else self.fallback.backend_label()

    def backend_label(self) -> str:
        return self._last_backend
