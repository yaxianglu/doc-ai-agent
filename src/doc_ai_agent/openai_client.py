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
