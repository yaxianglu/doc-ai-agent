from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional

from .repository import AlertRepository


@dataclass
class QueryResult:
    answer: str
    data: list
    evidence: Dict[str, str]


class QueryEngine:
    def __init__(self, repo: AlertRepository):
        self.repo = repo

    def _extract_since(self, question: str) -> str:
        m = re.search(r"(20\d{2})年以?来", question)
        if m:
            year = m.group(1)
            return f"{year}-01-01 00:00:00"
        return "1970-01-01 00:00:00"

    def answer(self, question: str, plan: Optional[dict] = None) -> QueryResult:
        plan = plan or {}
        since = str(plan.get("since") or self._extract_since(question))

        query_type = str(plan.get("query_type", "")).lower()
        is_top = query_type == "top" or "top" in question.lower() or "前5" in question or "top5" in question.lower()
        if is_top:
            field = str(plan.get("field", "")).strip()
            if field not in {"city", "county", "alert_type", "alert_level"}:
                if "市" in question:
                    field = "city"
                elif "区县" in question or "县" in question:
                    field = "county"
                elif "类型" in question:
                    field = "alert_type"
                else:
                    field = "alert_level"

            top_n = int(plan.get("top_n") or 5)
            top_n = max(1, min(top_n, 20))
            label_map = {"city": "市", "county": "区县", "alert_type": "类型", "alert_level": "等级"}
            label = label_map[field]

            data = self.repo.top_n(field, top_n, since)
            answer = f"自{since[:10]}以来，Top{top_n}{label}为：" + "；".join(
                [f"{i+1}.{r['name']}({r['count']})" for i, r in enumerate(data)]
            )
            return QueryResult(
                answer=answer,
                data=data,
                evidence={
                    "sql": f"SELECT {field}, COUNT(*) FROM alerts WHERE alert_time >= ? GROUP BY {field} ORDER BY COUNT(*) DESC LIMIT {top_n}",
                    "since": since,
                    "samples": self.repo.sample_alerts(since, 3),
                },
            )

        count = self.repo.count_since(since)
        return QueryResult(
            answer=f"自{since[:10]}以来，预警信息共 {count} 条。",
            data=[{"count": count}],
            evidence={
                "sql": "SELECT COUNT(*) FROM alerts WHERE alert_time >= ?",
                "since": since,
                "samples": self.repo.sample_alerts(since, 3),
            },
        )
