"""OpenAI HTTP 客户端：提供最小化文本与 JSON 补全能力。"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass


@dataclass
class OpenAIClient:
    """最小 OpenAI 客户端：封装 chat/completions 调用。"""
    api_key: str
    base_url: str
    timeout_seconds: int = 30

    @staticmethod
    def normalize_rerank_order(raw_order: object, candidate_count: int) -> list[int]:
        """规范化模型返回的 rerank 顺序，仅保留有效且不重复的索引。"""
        if candidate_count <= 0:
            return []
        if isinstance(raw_order, dict):
            raw_order = raw_order.get("order") or raw_order.get("indices") or []
        if not isinstance(raw_order, list):
            return list(range(candidate_count))
        normalized: list[int] = []
        for item in raw_order:
            if isinstance(item, bool):
                continue
            if not isinstance(item, int):
                continue
            if item < 0 or item >= candidate_count:
                continue
            if item in normalized:
                continue
            normalized.append(item)
        for index in range(candidate_count):
            if index not in normalized:
                normalized.append(index)
        return normalized

    def _chat(self, model: str, system_prompt: str, user_prompt: str, response_format: dict | None = None) -> str:
        """发送一次聊天补全请求并返回文本内容。"""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        req = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    def complete_json(self, model: str, system_prompt: str, user_prompt: str) -> dict:
        """请求 JSON 对象响应，并在本地完成反序列化。"""
        content = self._chat(
            model,
            system_prompt,
            user_prompt,
            response_format={"type": "json_object"},
        )
        return json.loads(content)

    def complete_text(self, model: str, system_prompt: str, user_prompt: str) -> str:
        """请求纯文本响应。"""
        return self._chat(model, system_prompt, user_prompt)
