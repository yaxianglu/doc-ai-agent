from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass


@dataclass
class OpenAIClient:
    api_key: str
    base_url: str
    timeout_seconds: int = 30

    def _chat(self, model: str, system_prompt: str, user_prompt: str, response_format: dict | None = None) -> str:
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
        content = self._chat(
            model,
            system_prompt,
            user_prompt,
            response_format={"type": "json_object"},
        )
        return json.loads(content)

    def complete_text(self, model: str, system_prompt: str, user_prompt: str) -> str:
        return self._chat(model, system_prompt, user_prompt)
