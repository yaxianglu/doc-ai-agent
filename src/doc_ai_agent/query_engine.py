from __future__ import annotations

import re
from datetime import datetime, timedelta
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

    def _extract_day_range(self, question: str) -> tuple[Optional[str], Optional[str]]:
        m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", question)
        if not m:
            return None, None
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        start = datetime(year, month, day)
        end = start + timedelta(days=1)
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")

    def _extract_city(self, question: str) -> Optional[str]:
        m = re.search(r"([\u4e00-\u9fa5]{2,12}市)", question)
        if m:
            return m.group(1)
        return None

    def _extract_level(self, question: str) -> Optional[str]:
        for level in ["涝渍", "重旱", "中旱", "轻旱"]:
            if level in question:
                return level
        return None

    def _extract_threshold(self, question: str) -> Optional[float]:
        m = re.search(r"(?:超过|>|大于)\s*(\d+(?:\.\d+)?)", question)
        if m:
            return float(m.group(1))
        return None

    def _infer_query_type(self, question: str, plan: dict) -> str:
        query_type = str(plan.get("query_type", "")).lower()
        if query_type in {
            "count",
            "top",
            "avg_by_level",
            "consecutive_devices",
            "highest_values",
            "threshold_summary",
            "latest_device",
            "region_disposal",
            "sms_empty",
            "subtype_ratio",
            "city_day_change",
        }:
            return query_type

        if "最近一次" in question and "设备" in question:
            return "latest_device"
        if "处置建议" in question and ("镇" in question or "街道" in question):
            return "region_disposal"
        if "sms_content" in question and "为空" in question:
            return "sms_empty"
        if "占比" in question and "子类型" in question:
            return "subtype_ratio"
        if "变化了多少" in question and "到" in question and "市" in question:
            return "city_day_change"
        if "最高" in question and "告警值" in question:
            return "highest_values"
        if "超过" in question and "告警值" in question:
            return "threshold_summary"
        if "连续两天" in question and "设备" in question:
            return "consecutive_devices"
        if ("平均" in question and "告警值" in question) or ("按告警等级分组" in question and "平均" in question):
            return "avg_by_level"
        if "top" in question.lower() or "Top" in question or "前5" in question or "最多" in question:
            return "top"
        return "count"

    def answer(self, question: str, plan: Optional[dict] = None) -> QueryResult:
        plan = plan or {}
        since = str(plan.get("since") or self._extract_since(question))
        query_type = self._infer_query_type(question, plan)

        if query_type == "top":
            field = str(plan.get("field", "")).strip()
            if field not in {"city", "county", "alert_type", "alert_level"}:
                if "区县" in question or "县" in question:
                    field = "county"
                elif "市" in question:
                    field = "city"
                elif "类型" in question:
                    field = "alert_type"
                else:
                    field = "alert_level"

            top_n = int(plan.get("top_n") or 5)
            top_n = max(1, min(top_n, 20))
            label_map = {"city": "市", "county": "区县", "alert_type": "类型", "alert_level": "等级"}
            label = label_map[field]
            day_start, day_end = self._extract_day_range(question)
            if day_start:
                since = day_start
            data = self.repo.top_n_filtered(field, top_n, since, until=day_end)
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

        if query_type == "highest_values":
            m = re.search(r"最高的(\d+)条", question)
            limit = int(m.group(1)) if m else 10
            data = self.repo.highest_alert_values(limit=limit)
            answer = f"告警值最高的{limit}条记录已列出。"
            return QueryResult(
                answer=answer,
                data=data,
                evidence={
                    "sql": "SELECT ... ORDER BY CAST(alert_value AS REAL) DESC LIMIT ?",
                    "limit": limit,
                    "samples": data[:3],
                },
            )

        if query_type == "threshold_summary":
            threshold = self._extract_threshold(question) or 150.0
            day_start, day_end = self._extract_day_range(question)
            if day_start:
                since = day_start
            count = self.repo.count_filtered(since, until=day_end)
            data = self.repo.top_n_filtered("city", 5, since, until=day_end, min_alert_value=threshold)
            above_count = self.repo.count_alert_value_above(threshold, since, day_end)
            city_summary = "；".join([f"{r['name']}({r['count']})" for r in data]) if data else "无"
            answer = (
                f"自{since[:10]}以来，告警值超过{threshold:g}的预警共{above_count}条，"
                f"主要集中在：{city_summary}"
            )
            return QueryResult(
                answer=answer,
                data={"total_count_since": count, "above_threshold_count": above_count, "top_cities": data},
                evidence={
                    "sql": "SELECT city, COUNT(*) FROM alerts WHERE CAST(alert_value AS REAL) > ? GROUP BY city",
                    "threshold": threshold,
                    "since": since,
                    "until": day_end,
                },
            )

        if query_type == "avg_by_level":
            data = self.repo.avg_alert_value_by_level(since)
            if data:
                details = "；".join([f"{r['level']}={r['avg_alert_value']}" for r in data])
                answer = f"自{since[:10]}以来，各告警等级平均告警值为：{details}。"
            else:
                answer = f"自{since[:10]}以来，没有可用于计算平均告警值的数据。"
            return QueryResult(
                answer=answer,
                data=data,
                evidence={
                    "sql": "SELECT alert_level, AVG(CAST(alert_value AS REAL)) FROM alerts WHERE alert_time >= ? GROUP BY alert_level",
                    "since": since,
                    "samples": self.repo.sample_alerts(since, 3),
                },
            )

        if query_type == "consecutive_devices":
            min_days = int(plan.get("min_days") or 2)
            data = self.repo.devices_triggered_on_multiple_days(since, min_days=min_days)
            if data:
                details = "；".join([f"{r['device_code']}({r['active_days']}天)" for r in data[:10]])
                answer = f"自{since[:10]}以来，连续至少{min_days}天触发预警的设备有：{details}。"
            else:
                answer = f"自{since[:10]}以来，未发现连续至少{min_days}天触发预警的设备。"
            return QueryResult(
                answer=answer,
                data=data,
                evidence={
                    "sql": "SELECT device_code, COUNT(DISTINCT SUBSTR(alert_time,1,10)) FROM alerts WHERE alert_time >= ? GROUP BY device_code HAVING COUNT(DISTINCT SUBSTR(alert_time,1,10)) >= ?",
                    "since": since,
                    "min_days": min_days,
                    "samples": self.repo.sample_alerts(since, 3),
                },
            )

        if query_type == "latest_device":
            m = re.search(r"(SNS\d+)", question)
            if not m:
                return QueryResult(answer="未识别到设备编码。", data=[], evidence={"sql": ""})
            device_code = m.group(1)
            row = self.repo.latest_by_device(device_code)
            if row is None:
                return QueryResult(
                    answer=f"未找到设备{device_code}的预警记录。",
                    data=[],
                    evidence={"sql": "SELECT ... WHERE device_code = ?"},
                )
            return QueryResult(
                answer=f"设备{device_code}最近一次预警时间{row['alert_time']}，等级{row['alert_level']}。",
                data=[row],
                evidence={"sql": "SELECT ... WHERE device_code = ? ORDER BY alert_time DESC LIMIT 1"},
            )

        if query_type == "region_disposal":
            city = self._extract_city(question)
            m = re.search(r"([\u4e00-\u9fa5]{1,12}(?:镇|街道))", question)
            region = m.group(1) if m else ""
            if city and region.startswith(city):
                region = region[len(city) :]
            if not city or not region:
                return QueryResult(answer="未识别到城市或乡镇信息。", data=[], evidence={"sql": ""})
            row = self.repo.latest_by_region_keyword(city, region)
            if row is None:
                return QueryResult(
                    answer=f"未找到{city}{region}相关预警记录。",
                    data=[],
                    evidence={"sql": "SELECT ... WHERE city = ? AND region_name LIKE ?"},
                )
            return QueryResult(
                answer=f"{city}{region}最近一条处置建议：{row['disposal_suggestion']}",
                data=[row],
                evidence={"sql": "SELECT ... WHERE city = ? AND region_name LIKE ? ORDER BY alert_time DESC LIMIT 1"},
            )

        if query_type == "sms_empty":
            m = re.search(r"([\u4e00-\u9fa5]{1,12}(?:县|区))", question)
            county = m.group(1) if m else ""
            rows = self.repo.sms_empty_records(county)
            answer = f"{county}中sms_content为空的记录共{len(rows)}条。"
            return QueryResult(
                answer=answer,
                data=rows,
                evidence={"sql": "SELECT ... WHERE county = ? AND sms_content IS NULL/empty"},
            )

        if query_type == "subtype_ratio":
            since = self._extract_since(question)
            ratio = self.repo.subtype_ratio("土壤墒情仪", "墒情预警", since)
            answer = (
                f"自{since[:10]}以来，土壤墒情仪类型中墒情预警占比"
                f"{ratio['ratio_percent']}%（{ratio['subtype_count']}/{ratio['type_count']}）。"
            )
            return QueryResult(
                answer=answer,
                data=[ratio],
                evidence={"sql": "SELECT COUNT(*) ... alert_type/alert_subtype"},
            )

        if query_type == "city_day_change":
            city = self._extract_city(question) or ""
            m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日到(\d{1,2})月(\d{1,2})日", question)
            if not city or not m:
                return QueryResult(answer="未识别到城市或日期区间。", data=[], evidence={"sql": ""})
            year, m1, d1, m2, d2 = map(int, m.groups())
            day1 = datetime(year, m1, d1)
            day2 = datetime(year, m2, d2)
            c1 = self.repo.count_filtered(day1.strftime("%Y-%m-%d 00:00:00"), (day1 + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00"), city=city)
            c2 = self.repo.count_filtered(day2.strftime("%Y-%m-%d 00:00:00"), (day2 + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00"), city=city)
            diff = c2 - c1
            answer = f"{city}{day1.strftime('%m月%d日')}到{day2.strftime('%m月%d日')}预警数量变化{diff:+d}（{c1}->{c2}）。"
            return QueryResult(
                answer=answer,
                data=[{"city": city, "day1_count": c1, "day2_count": c2, "diff": diff}],
                evidence={"sql": "SELECT COUNT(*) ... city + day range"},
            )

        day_start, day_end = self._extract_day_range(question)
        if day_start:
            since = day_start
        city = self._extract_city(question)
        level = self._extract_level(question)
        count = self.repo.count_filtered(since, until=day_end, city=city, level=level)
        scope = ""
        if city:
            scope += city
        if level:
            scope += f"{level}等级"
        return QueryResult(
            answer=f"自{since[:10]}以来，{scope}预警信息共 {count} 条。",
            data=[{"count": count}],
            evidence={
                "sql": "SELECT COUNT(*) FROM alerts WHERE alert_time >= ?",
                "since": since,
                "until": day_end,
                "city": city,
                "alert_level": level,
                "samples": self.repo.sample_alerts(since, 3),
            },
        )
