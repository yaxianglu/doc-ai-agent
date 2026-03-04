from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class StaticSourceProvider:
    items: List[dict]

    def search(self, question: str, limit: int = 3) -> List[dict]:
        keywords = self._keywords(question)
        if not keywords:
            return self.items[:limit]

        scored = []
        for item in self.items:
            haystack = f"{item.get('title','')} {item.get('snippet','')}"
            score = sum(1 for k in keywords if k in haystack)
            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [it for _, it in scored[:limit]]

    @staticmethod
    def _keywords(text: str) -> List[str]:
        vocab = ["台风", "小麦", "虫情", "暴雨", "排水", "病害", "预警", "处置"]
        seen = []
        for word in vocab:
            if word in text and word not in seen:
                seen.append(word)
        chinese_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        for chunk in chinese_chunks:
            for i in range(0, len(chunk) - 1):
                token = chunk[i : i + 2]
                if token not in seen:
                    seen.append(token)
                if len(seen) >= 12:
                    return seen
        return seen


def load_static_sources(path: str) -> StaticSourceProvider:
    p = Path(path)
    if not p.exists():
        return StaticSourceProvider([])
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return StaticSourceProvider([])
    return StaticSourceProvider([x for x in data if isinstance(x, dict)])
