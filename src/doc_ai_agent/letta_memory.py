from __future__ import annotations

import json
import os
from typing import Protocol


def _time_range_slot_value_from_window(window: dict | None) -> dict:
    payload = dict(window or {})
    window_type = str(payload.get("window_type") or "")
    window_value = payload.get("window_value")
    if window_type in {"months", "weeks", "days"} and window_value not in {None, ""}:
        return {"mode": "relative", "value": f"{window_value}_{window_type}"}
    return {"mode": "none", "value": None}


def _window_from_time_range_slot(value: object) -> dict:
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
    if source in {"explicit", "carried"}:
        return 4
    if source == "system":
        return 2
    if source in {"inferred", "legacy"}:
        return 2
    return 0


def _slot_has_value(value: object) -> bool:
    if value == "" or value is None:
        return False
    if isinstance(value, dict):
        if not value:
            return False
        if set(value.keys()) == {"mode", "value"} and str(value.get("mode") or "") == "none" and value.get("value") is None:
            return False
        return True
    return True


def _normalize_slot(slot_name: str, slot_payload: object, fallback_value: object, turn_count: int) -> dict:
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
    }


def normalize_memory_snapshot(snapshot: dict | None) -> dict:
    payload = dict(snapshot or {})
    existing_slots = dict(payload.get("slots") or {})
    existing_turns = [
        int(slot.get("updated_at_turn") or 0)
        for slot in existing_slots.values()
        if isinstance(slot, dict)
    ]
    turn_count = int(payload.get("turn_count") or max(existing_turns or [0]))
    slots = _build_slots(payload, turn_count)
    time_range_window = _window_from_time_range_slot(slots["time_range"]["value"])
    return {
        "memory_version": int(payload.get("memory_version") or 2),
        "turn_count": turn_count,
        "domain": str(payload.get("domain") or slots["domain"]["value"] or ""),
        "region_name": str(payload.get("region_name") or slots["region"]["value"] or ""),
        "query_type": str(payload.get("query_type") or ""),
        "window": dict(payload.get("window") or time_range_window),
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
        "slots": slots,
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
