"""Letta/本地双存储记忆层：规范化快照并提供弹性读写。"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Protocol

from .agent_memory import query_family_from_type


def _time_range_slot_value_from_window(window: dict | None) -> dict:
    """把 window 结构压缩成 time_range 槽位值。"""
    payload = dict(window or {})
    window_type = str(payload.get("window_type") or "")
    window_value = payload.get("window_value")
    if window_type in {"months", "weeks", "days"} and window_value not in {None, ""}:
        return {"mode": "relative", "value": f"{window_value}_{window_type}"}
    return {"mode": "none", "value": None}


def _window_from_time_range_slot(value: object) -> dict:
    """把 time_range 槽位值还原为 window 结构。"""
    if not isinstance(value, dict):
        return {}
    if str(value.get("mode") or "") != "relative":
        return {}
    raw_value = str(value.get("value") or "")
    if "_" not in raw_value:
        return {}
    amount, unit = raw_value.split("_", 1)
    if unit not in {"months", "weeks", "days"}:
        return {}
    try:
        parsed_amount = int(amount)
    except ValueError:
        return {}
    return {"window_type": unit, "window_value": parsed_amount}


def _slot_priority(source: str) -> int:
    """根据槽位来源计算优先级。"""
    if source == "explicit":
        return 100
    if source == "carried":
        return 90
    if source == "system":
        return 80
    if source == "inferred":
        return 60
    if source == "legacy":
        return 50
    return 0


def _slot_ttl(source: str) -> int:
    """根据槽位来源计算保留轮次。"""
    if source in {"explicit", "carried"}:
        return 4
    if source == "system":
        return 2
    if source in {"inferred", "legacy"}:
        return 2
    return 0


def _slot_has_value(value: object) -> bool:
    """判断槽位值是否真的携带了有效信息。"""
    if value == "" or value is None:
        return False
    if isinstance(value, dict):
        if not value:
            return False
        if set(value.keys()) == {"mode", "value"} and str(value.get("mode") or "") == "none" and value.get("value") is None:
            return False
        return True
    return True


def _slot_is_fresh(slot: dict, turn_count: int) -> bool:
    """判断槽位在当前轮次下是否仍然有效。"""
    ttl = int(slot.get("ttl") or 0)
    updated_at_turn = int(slot.get("updated_at_turn") or 0)
    if ttl <= 0:
        return False
    if not _slot_has_value(slot.get("value")):
        return False
    return max(turn_count - updated_at_turn, 0) < ttl


def _query_type_from_family(domain: str, family: str) -> str:
    if domain not in {"pest", "soil"}:
        return ""
    if family == "ranking":
        return f"{domain}_top"
    if family == "trend":
        return f"{domain}_trend"
    if family == "detail":
        return f"{domain}_detail"
    if family == "overview":
        return f"{domain}_overview"
    if family == "forecast":
        return f"{domain}_forecast"
    return ""


def _normalize_slot(slot_name: str, slot_payload: object, fallback_value: object, turn_count: int) -> dict:
    """把任意形态的槽位规整成统一内部结构。"""
    payload = dict(slot_payload or {})
    if slot_name == "time_range":
        raw_value = payload.get("value") if "value" in payload else fallback_value
        if isinstance(raw_value, dict):
            if "mode" in raw_value:
                value = {
                    "mode": str(raw_value.get("mode") or "none"),
                    "value": raw_value.get("value"),
                }
            else:
                value = _time_range_slot_value_from_window(raw_value)
        else:
            value = _time_range_slot_value_from_window(fallback_value if isinstance(fallback_value, dict) else {})
    else:
        value = payload.get("value") if "value" in payload else fallback_value
        if value is None:
            value = ""
        value = str(value) if not isinstance(value, dict) else dict(value)

    source = str(payload.get("source") or ("legacy" if _slot_has_value(value) else "empty"))
    priority = int(payload.get("priority") if isinstance(payload.get("priority"), int) else _slot_priority(source))
    ttl = int(payload.get("ttl") if isinstance(payload.get("ttl"), int) else _slot_ttl(source))
    updated_at_turn = int(payload.get("updated_at_turn") if isinstance(payload.get("updated_at_turn"), int) else turn_count)
    return {
        "value": value,
        "source": source,
        "priority": priority,
        "ttl": ttl,
        "updated_at_turn": updated_at_turn,
    }


def _build_slots(payload: dict, turn_count: int) -> dict:
    """从旧快照和当前字段构建标准化槽位集合。"""
    existing_slots = dict(payload.get("slots") or {})
    intent_value = (
        (existing_slots.get("intent") or {}).get("value")
        or (payload.get("conversation_state") or {}).get("last_intent")
        or payload.get("intent")
        or ""
    )
    return {
        "domain": _normalize_slot("domain", existing_slots.get("domain"), payload.get("domain") or "", turn_count),
        "region": _normalize_slot("region", existing_slots.get("region"), payload.get("region_name") or "", turn_count),
        "time_range": _normalize_slot("time_range", existing_slots.get("time_range"), payload.get("window") or {}, turn_count),
        "intent": _normalize_slot("intent", existing_slots.get("intent"), intent_value, turn_count),
        "answer_form": _normalize_slot(
            "answer_form",
            existing_slots.get("answer_form"),
            payload.get("answer_form")
            or (payload.get("conversation_state") or {}).get("last_answer_form")
            or "",
            turn_count,
        ),
        "region_level": _normalize_slot(
            "region_level",
            existing_slots.get("region_level"),
            (payload.get("route") or {}).get("region_level")
            or (payload.get("conversation_state") or {}).get("last_region_level")
            or "",
            turn_count,
        ),
    }


def normalize_memory_snapshot(snapshot: dict | None) -> dict:
    """把任意版本的记忆快照规整到统一结构。"""
    payload = dict(snapshot or {})
    existing_slots = dict(payload.get("slots") or {})
    existing_turns = [
        int(slot.get("updated_at_turn") or 0)
        for slot in existing_slots.values()
        if isinstance(slot, dict)
    ]
    turn_count = int(payload.get("turn_count") or max(existing_turns or [0]))
    slots = _build_slots(payload, turn_count)
    effective_domain = str(slots["domain"]["value"] or "") if _slot_is_fresh(slots["domain"], turn_count) else ""
    effective_region = str(slots["region"]["value"] or "") if _slot_is_fresh(slots["region"], turn_count) else ""
    effective_answer_form = str(slots["answer_form"]["value"] or "") if _slot_is_fresh(slots["answer_form"], turn_count) else ""
    effective_region_level = str(slots["region_level"]["value"] or "") if _slot_is_fresh(slots["region_level"], turn_count) else ""
    time_range_window = _window_from_time_range_slot(slots["time_range"]["value"]) if _slot_is_fresh(slots["time_range"], turn_count) else {}
    route = dict(payload.get("route") or {})
    last_query_family = str((payload.get("conversation_state") or {}).get("last_query_family") or "")
    if not effective_region:
        route["city"] = None
        route["county"] = None
    if not time_range_window:
        route["window"] = {}
    if effective_region_level:
        route["region_level"] = effective_region_level
    query_type = str(payload.get("query_type") or route.get("query_type") or "")
    if not query_type and effective_domain and last_query_family:
        query_type = _query_type_from_family(effective_domain, last_query_family)
        route["query_type"] = query_type
    if not effective_domain and query_type.startswith(("pest_", "soil_")):
        query_type = ""
        route["query_type"] = ""
    time_range_value = slots["time_range"]["value"]
    existing_layers = dict(payload.get("memory_layers") or {})
    session_context = dict(existing_layers.get("session_context") or {})
    task_context = dict(existing_layers.get("task_context") or {})
    user_context = dict(existing_layers.get("user_context") or payload.get("user_preferences") or {})
    memory_layers = {
        "session_context": {
            "domain": str(session_context.get("domain") or effective_domain),
            "region_name": str(session_context.get("region_name") or effective_region),
            "route": dict(session_context.get("route") or route),
            "forecast": dict(session_context.get("forecast") or payload.get("forecast") or {}),
            "last_question": str(session_context.get("last_question") or payload.get("last_question") or ""),
            "turn_count": int(session_context.get("turn_count") or turn_count),
        },
        "task_context": {
            "query_type": str(task_context.get("query_type") or query_type),
            "query_family": str(task_context.get("query_family") or last_query_family or query_family_from_type(query_type)),
            "intent": str(task_context.get("intent") or (payload.get("conversation_state") or {}).get("last_intent") or payload.get("intent") or ""),
            "answer_form": str(task_context.get("answer_form") or effective_answer_form),
            "region_level": str(task_context.get("region_level") or effective_region_level or route.get("region_level") or ""),
            "time_range": dict(task_context.get("time_range") or time_range_value) if isinstance(task_context.get("time_range") or time_range_value, dict) else {"mode": "none", "value": None},
            "pending_clarification": task_context.get("pending_clarification") or payload.get("pending_clarification"),
        },
        "user_context": dict(user_context),
    }
    return {
        "memory_version": int(payload.get("memory_version") or 2),
        "turn_count": turn_count,
        "domain": effective_domain,
        "region_name": effective_region,
        "answer_form": effective_answer_form,
        "query_type": query_type,
        "window": dict(time_range_window),
        "route": route,
        "forecast": dict(payload.get("forecast") or {}),
        "last_question": str(payload.get("last_question") or ""),
        "last_answer": str(payload.get("last_answer") or ""),
        "last_verified_answer": str(payload.get("last_verified_answer") or payload.get("last_answer") or ""),
        "pending_user_question": payload.get("pending_user_question"),
        "pending_clarification": payload.get("pending_clarification"),
        "user_preferences": dict(payload.get("user_preferences") or {}),
        "memory_layers": memory_layers,
        "conversation_state": {
            "last_intent": str((payload.get("conversation_state") or {}).get("last_intent") or payload.get("intent") or ""),
            "last_answer_mode": str((payload.get("conversation_state") or {}).get("last_answer_mode") or payload.get("answer_mode") or ""),
            "last_clarification_reason": str((payload.get("conversation_state") or {}).get("last_clarification_reason") or payload.get("pending_clarification") or ""),
            "last_query_family": str(last_query_family or query_family_from_type(query_type)),
            "last_region_level": str((payload.get("conversation_state") or {}).get("last_region_level") or effective_region_level or route.get("region_level") or ""),
            "last_answer_form": str((payload.get("conversation_state") or {}).get("last_answer_form") or effective_answer_form or ""),
        },
        "slots": slots,
    }


class MemoryStore(Protocol):
    """记忆存储协议：约束 load/remember/backend_label 三个核心能力。"""
    def load(self, thread_id: str) -> dict:
        """读取指定线程的记忆快照。"""
        ...

    def remember(self, thread_id: str, snapshot: dict) -> None:
        """持久化指定线程的记忆快照。"""
        ...

    def backend_label(self) -> str:
        """返回当前存储后端名称。"""
        ...


class LocalMemoryStore:
    """本地 JSON 记忆存储实现。"""
    def __init__(self, path: str):
        self.path = path

    def _backup_corrupted_store(self) -> None:
        """为损坏的记忆文件留一份备份，避免静默丢失原始内容。"""
        if not self.path or not os.path.exists(self.path):
            return
        backup_path = f"{self.path}.corrupt-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        try:
            shutil.copy2(self.path, backup_path)
        except OSError:
            return

    def _load_all(self) -> dict:
        if not self.path or not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (UnicodeDecodeError, json.JSONDecodeError, OSError):
            # 线上文件一旦被非 UTF-8 内容污染，后续对话不应该整体 500。
            self._backup_corrupted_store()
            return {}
        return data if isinstance(data, dict) else {}

    def _write_all(self, data: dict) -> None:
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)

    def load(self, thread_id: str) -> dict:
        """从本地 JSON 文件读取线程记忆。"""
        if not thread_id:
            return normalize_memory_snapshot({})
        return normalize_memory_snapshot(self._load_all().get(thread_id) or {})

    def remember(self, thread_id: str, snapshot: dict) -> None:
        """把线程记忆写回本地 JSON 文件。"""
        if not thread_id:
            return
        data = self._load_all()
        data[thread_id] = normalize_memory_snapshot(snapshot)
        self._write_all(data)

    def backend_label(self) -> str:
        """返回本地记忆后端名称。"""
        return "LocalMemory"


class LettaMemoryStore:
    """Letta 远端记忆存储实现。"""
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
        """从 Letta block 中读取线程记忆。"""
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
        """把线程记忆写入或更新到 Letta block。"""
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
        """返回 Letta 记忆后端名称。"""
        return "Letta"


class ResilientMemoryStore:
    """弹性记忆存储：优先主存储，失败自动回退本地存储。"""
    def __init__(self, primary: MemoryStore | None, fallback: MemoryStore):
        self.primary = primary
        self.fallback = fallback
        self._last_backend = fallback.backend_label()

    def load(self, thread_id: str) -> dict:
        """优先从主存储读取，失败时回退到本地存储。"""
        if self.primary is not None:
            # 先尝试主存储（通常是 Letta），失败再平滑回退。
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
        """同时写入主/备存储，并记录本轮实际可用后端。"""
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
        """返回最近一次成功使用的记忆后端名称。"""
        return self._last_backend
