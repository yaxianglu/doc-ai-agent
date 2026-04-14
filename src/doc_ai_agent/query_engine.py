"""查询执行引擎：把路由计划转换为结构化数据查询与中文回答。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional

from .query_extractors import extract_city as shared_extract_city
from .query_extractors import extract_day_range as shared_extract_day_range


@dataclass
class QueryResult:
    """查询执行结果：包含回答文本、原始数据与证据元信息。"""
    answer: str
    data: list | dict
    evidence: Dict[str, object]


class QueryEngine:
    """面向查询计划的执行器，负责路由到不同数据查询分支。"""
    def __init__(self, repo):
        self.repo = repo

    def _parse_timestamp(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                return datetime.fromisoformat(str(value))
            except ValueError:
                return None

    def _window_outside_available_range(self, since: str, until: Optional[str], time_range: Optional[dict]) -> bool:
        if not time_range:
            return False
        request_start = self._parse_timestamp(since)
        request_end = self._parse_timestamp(until) if until else None
        available_start = self._parse_timestamp(str(time_range.get("min_time") or ""))
        available_end = self._parse_timestamp(str(time_range.get("max_time") or ""))
        if not request_start or not available_start or not available_end:
            return False
        if request_start > available_end:
            return True
        if request_end and request_end < available_start:
            return True
        return False

    def _build_available_range_item(self, source: str, label: str, time_range: Optional[dict]) -> Optional[dict]:
        if not time_range:
            return None
        min_time = time_range.get("min_time")
        max_time = time_range.get("max_time")
        if not min_time or not max_time:
            return None
        return {
            "source": source,
            "label": label,
            "min_time": str(min_time),
            "max_time": str(max_time),
        }

    def _format_time_range_suffix(self, label: str, time_range: Optional[dict]) -> str:
        if not time_range:
            return ""
        min_time = self._format_short_date(time_range.get("min_time"))
        max_time = self._format_short_date(time_range.get("max_time"))
        if not min_time or not max_time:
            return ""
        return f"当前可用{label}范围为 {min_time} 至 {max_time}。"

    def _format_short_date(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return str(value)[:10]

    def _format_available_window(self, time_range: Optional[dict]) -> Optional[str]:
        if not time_range:
            return None
        min_time = self._format_short_date(time_range.get("min_time"))
        max_time = self._format_short_date(time_range.get("max_time"))
        if not min_time or not max_time:
            return None
        return f"{min_time} 至 {max_time}"

    def _time_phrase_from_range(self, source: str, time_range: Optional[dict]) -> str:
        if not time_range:
            return "最近一段时间"
        start = self._parse_timestamp(str(time_range.get("min_time") or ""))
        end = self._parse_timestamp(str(time_range.get("max_time") or ""))
        if not start or not end or end < start:
            return "最近一段时间"
        if source == "alerts":
            return f"{start.year}年{start.month}月以来"
        days = max((end - start).days + 1, 1)
        if days >= 75:
            months = max(round(days / 30), 1)
            return f"过去{months}个月"
        if days >= 14:
            weeks = max(round(days / 7), 1)
            return f"近{weeks}周"
        return f"近{days}天"

    def _suggested_question(
        self,
        *,
        query_type: str,
        time_phrase: str,
        region_name: str = "",
        top_n: int = 5,
        field: str = "city",
        anomaly_direction: Optional[str] = None,
    ) -> str:
        if query_type == "pest_top":
            return f"{time_phrase}虫情最严重的地方是哪里？"
        if query_type == "soil_top":
            if anomaly_direction == "high":
                return f"{time_phrase}墒情偏高最明显的地方是哪里？"
            return f"{time_phrase}缺水最厉害的地方是哪里？"
        if query_type == "pest_trend":
            return f"{region_name}{time_phrase}虫害走势怎么样？" if region_name else f"{time_phrase}虫情最严重的地方是哪里？"
        if query_type == "pest_detail":
            return f"{region_name}{time_phrase}虫害具体数据是什么？" if region_name else f"{time_phrase}虫情具体数据是什么？"
        if query_type == "soil_trend":
            return f"{region_name}{time_phrase}墒情走势怎么样？" if region_name else f"{time_phrase}缺水最厉害的地方是哪里？"
        if query_type == "soil_detail":
            return f"{region_name}{time_phrase}墒情具体数据是什么？" if region_name else f"{time_phrase}墒情具体数据是什么？"
        if query_type == "joint_risk":
            return f"{time_phrase}哪些地方虫情高而且缺水更明显？"
        if query_type == "top":
            place = "区县" if field == "county" else "市"
            return f"{time_phrase}top{top_n}的是哪几个{place}？"
        if query_type == "count":
            return f"{time_phrase}指挥调度平台发生了多少预警信息？"
        return f"{time_phrase}有哪些值得关注的数据？"

    def _build_recovery_suggestions(
        self,
        *,
        question: str,
        query_type: str,
        no_data_reason: dict,
        time_ranges: list[dict],
        region_name: str = "",
        top_n: int = 5,
        field: str = "city",
        anomaly_direction: Optional[str] = None,
    ) -> list[dict]:
        """根据无数据原因生成可执行的重试建议。"""
        code = str(no_data_reason.get("code") or "")
        primary_range = time_ranges[0] if time_ranges else None
        if code in {"outside_available_window", "no_matching_records"}:
            time_phrase = self._time_phrase_from_range(str(no_data_reason.get("source") or ""), primary_range)
            available_window = self._format_available_window(primary_range)
            message = "建议改用当前可用时间窗重试。"
            if available_window:
                message = f"当前数据覆盖 {available_window}，建议改用这个时间窗重试。"
            return [
                {
                    "source": no_data_reason.get("source"),
                    "action": "use_available_window",
                    "title": "改用可用时间窗重试",
                    "message": message,
                    "suggested_question": self._suggested_question(
                        query_type=query_type,
                        time_phrase=time_phrase,
                        region_name=region_name,
                        top_n=top_n,
                        field=field,
                        anomaly_direction=anomaly_direction,
                    ),
                }
            ]
        if code == "no_region_records":
            broaden_query_type = "pest_top" if query_type == "pest_trend" else "soil_top" if query_type == "soil_trend" else query_type
            time_phrase = self._time_phrase_from_range(str(no_data_reason.get("source") or ""), primary_range)
            return [
                {
                    "source": no_data_reason.get("source"),
                    "action": "broaden_region_scope",
                    "title": "先放宽地区范围",
                    "message": f"先去掉{region_name}这样的地区限定，看看同时间窗内整体分布，再决定要不要细查到单个地区。",
                    "suggested_question": self._suggested_question(
                        query_type=broaden_query_type,
                        time_phrase=time_phrase,
                        top_n=top_n,
                        field=field,
                        anomaly_direction=anomaly_direction,
                    ),
                }
            ]
        if code == "no_joint_risk_matches":
            pest_range = next((item for item in time_ranges if item.get("source") == "pest"), primary_range)
            soil_range = next((item for item in time_ranges if item.get("source") == "soil"), primary_range)
            return [
                {
                    "source": no_data_reason.get("source"),
                    "action": "split_joint_risk",
                    "title": "先拆成单域排查",
                    "message": "先分别查看虫情和墒情的高风险地区，再判断有没有必要回到联合风险交叉验证。",
                    "suggested_questions": [
                        self._suggested_question(
                            query_type="pest_top",
                            time_phrase=self._time_phrase_from_range("pest", pest_range),
                        ),
                        self._suggested_question(
                            query_type="soil_top",
                            time_phrase=self._time_phrase_from_range("soil", soil_range),
                            anomaly_direction="low",
                        ),
                    ],
                }
            ]
        if code == "no_data_loaded":
            return [
                {
                    "source": no_data_reason.get("source"),
                    "action": "check_data_import",
                    "title": "先确认数据是否已导入",
                    "message": "当前数据源看起来还没有可用样本，建议先检查导入任务或数据同步状态。",
                }
            ]
        return []

    def _format_since_scope(self, since: str) -> str:
        if since == "1970-01-01 00:00:00":
            return ""
        return f"从{since[:10]}起"

    @staticmethod
    def _scope_prefix(region_name: Optional[str], since_scope: str, overall_label: str = "整体") -> str:
        if region_name:
            return f"{region_name}{since_scope}"
        if since_scope:
            return f"{since_scope}{overall_label}"
        return overall_label

    def _available_alert_range_suffix(self) -> str:
        if not hasattr(self.repo, "available_alert_time_range"):
            return ""
        return self._format_time_range_suffix("告警数据", self.repo.available_alert_time_range())

    def _available_alert_ranges(self) -> list[dict]:
        if not hasattr(self.repo, "available_alert_time_range"):
            return []
        item = self._build_available_range_item("alerts", "告警数据", self.repo.available_alert_time_range())
        return [item] if item else []

    def _build_no_data_reason(
        self,
        *,
        source: str,
        label: str,
        since: str,
        until: Optional[str] = None,
        time_range: Optional[dict] = None,
        region_name: str = "",
        code: Optional[str] = None,
        message: Optional[str] = None,
    ) -> dict:
        if code and message:
            return {"source": source, "code": code, "message": message}
        if not time_range:
            return {
                "source": source,
                "code": "no_data_loaded",
                "message": f"当前还没有加载可用的{label}。",
            }
        if self._window_outside_available_range(since, until, time_range):
            return {
                "source": source,
                "code": "outside_available_window",
                "message": f"请求时间窗超出当前{label}覆盖范围。",
            }
        if region_name:
            return {
                "source": source,
                "code": "no_region_records",
                "message": f"{region_name}在当前时间窗内暂无{label}样本。",
            }
        return {
            "source": source,
            "code": "no_matching_records",
            "message": f"当前筛选条件下暂无{label}样本。",
        }

    def _available_pest_range_suffix(self) -> str:
        if not hasattr(self.repo, "available_pest_time_range"):
            return ""
        return self._format_time_range_suffix("虫情监测数据", self.repo.available_pest_time_range())

    def _available_pest_time_range(self) -> Optional[dict]:
        if not hasattr(self.repo, "available_pest_time_range"):
            return None
        return self.repo.available_pest_time_range()

    def _available_pest_ranges(self) -> list[dict]:
        item = self._build_available_range_item("pest", "虫情监测数据", self._available_pest_time_range())
        return [item] if item else []

    def _available_soil_range_suffix(self, anomaly_direction: Optional[str] = None) -> str:
        if not hasattr(self.repo, "available_soil_time_range"):
            return ""
        try:
            time_range = self.repo.available_soil_time_range(anomaly_direction=anomaly_direction)
        except TypeError:
            time_range = self.repo.available_soil_time_range()
        return self._format_time_range_suffix("墒情监测数据", time_range)

    def _available_soil_ranges(self, anomaly_direction: Optional[str] = None) -> list[dict]:
        if not hasattr(self.repo, "available_soil_time_range"):
            return []
        try:
            time_range = self.repo.available_soil_time_range(anomaly_direction=anomaly_direction)
        except TypeError:
            time_range = self.repo.available_soil_time_range()
        item = self._build_available_range_item("soil", "墒情监测数据", time_range)
        return [item] if item else []

    def _available_soil_time_range(self, anomaly_direction: Optional[str] = None) -> Optional[dict]:
        if not hasattr(self.repo, "available_soil_time_range"):
            return None
        try:
            return self.repo.available_soil_time_range(anomaly_direction=anomaly_direction)
        except TypeError:
            return self.repo.available_soil_time_range()

    def _extract_region(self, question: str, plan: dict) -> tuple[Optional[str], str]:
        county = plan.get("county") or None
        city = plan.get("city") or None
        region_level = str(plan.get("region_level") or "city")
        if county:
            return county, "county"
        if city:
            return city, region_level if region_level in {"city", "county"} else "city"
        return None, region_level

    def _extract_since(self, question: str) -> str:
        if "今年以来" in question:
            return f"{datetime.now().year}-01-01 00:00:00"
        m = re.search(r"(20\d{2})年以?来", question)
        if m:
            year = m.group(1)
            return f"{year}-01-01 00:00:00"
        return "1970-01-01 00:00:00"

    def _extract_day_range(self, question: str) -> tuple[Optional[str], Optional[str]]:
        return shared_extract_day_range(question)

    def _extract_city(self, question: str) -> Optional[str]:
        return shared_extract_city(question)

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

    def _trend_text(self, series: list[dict], value_key: str) -> str:
        if len(series) < 2:
            return "样本不足，暂不判断趋势"
        first = float(series[0].get(value_key) or 0)
        last = float(series[-1].get(value_key) or 0)
        if last > first * 1.15:
            return "整体上升"
        if last < first * 0.85:
            return "整体下降"
        return "整体波动平稳"

    @staticmethod
    def _first_metric(series: list[dict], key: str) -> float:
        if not series:
            return 0.0
        return float(series[0].get(key) or 0)

    @staticmethod
    def _format_recovery_text(recovery_suggestions: list[dict]) -> str:
        if not recovery_suggestions:
            return ""
        suggestion = dict(recovery_suggestions[0] or {})
        message = str(suggestion.get("message") or "").strip()
        suggested_question = str(suggestion.get("suggested_question") or "").strip()
        suggested_questions = suggestion.get("suggested_questions") or []
        if suggested_questions and not suggested_question:
            first_question = next((str(item).strip() for item in suggested_questions if str(item).strip()), "")
            suggested_question = first_question
        if message and suggested_question:
            return f"{message} 可尝试：{suggested_question}"
        return message or suggested_question

    def _compose_no_data_answer(
        self,
        *,
        base_answer: str,
        no_data_reason: dict,
        range_suffix: str,
        recovery_suggestions: list[dict],
    ) -> str:
        answer = base_answer
        reason_message = str(no_data_reason.get("message") or "").strip().rstrip("。")
        if reason_message:
            answer = f"{answer}原因：{reason_message}。"
        if range_suffix:
            answer = f"{answer}{range_suffix}"
        recovery_text = self._format_recovery_text(recovery_suggestions).strip().rstrip("。")
        if recovery_text:
            answer = f"{answer}建议：{recovery_text}。"
        return answer

    @staticmethod
    def _trend_extra_judgment(question: str, *, trend: str, domain: str) -> str:
        normalized_question = str(question or "")
        if domain == "soil" and any(token in normalized_question for token in ["缓解", "好转"]):
            if trend == "整体下降":
                return "有缓解迹象"
            if trend == "整体上升":
                return "暂未缓解，异常还有加重迹象"
            if trend == "整体波动平稳":
                return "暂无明显缓解"
            return "暂无法判断是否缓解"
        return ""

    def _build_trend_answer(
        self,
        *,
        question: str,
        scope_prefix: str,
        topic_label: str,
        trend: str,
        first: float,
        latest: float,
        peak: float,
        coverage_days: int,
        domain: str,
    ) -> str:
        answer = (
            f"{scope_prefix}{topic_label}趋势：{trend}，"
            f"起点{self._format_metric_value(first)}，最近{self._format_metric_value(latest)}，"
            f"峰值{self._format_metric_value(peak)}，共覆盖{coverage_days}个观测日。"
        )
        extra_judgment = self._trend_extra_judgment(question, trend=trend, domain=domain)
        if extra_judgment:
            answer = f"{answer}{extra_judgment}。"
        return answer

    def _answer_pest_top(self, question: str, plan: dict) -> QueryResult:
        since = str(plan.get("since") or "1970-01-01 00:00:00")
        until = plan.get("until") or None
        region_level = str(plan.get("region_level") or "city")
        top_n = max(1, int(plan.get("top_n") or 1))
        city = plan.get("city")
        county = plan.get("county")
        wants_city_then_county = "市" in question and ("再细到县" in question or "细到县" in question or "再细到区县" in question)
        if wants_city_then_county:
            city_rows = self.repo.top_pest_regions(since, until, region_level="city", top_n=min(max(top_n, 3), 5), city=None, county=None)
            county_rows = self.repo.top_pest_regions(since, until, region_level="county", top_n=max(top_n, 5), city=None, county=None)
            since_scope = self._format_since_scope(since)
            prefix = f"{since_scope}，" if since_scope else "历史上，"
            city_text = "；".join(
                f"{idx+1}.{row['region_name']}（严重度{row['severity_score']}，记录{row['record_count']}条）"
                for idx, row in enumerate(city_rows)
            ) if city_rows else "无"
            county_text = "；".join(
                f"{idx+1}.{row['region_name']}（严重度{row['severity_score']}，记录{row['record_count']}条）"
                for idx, row in enumerate(county_rows)
            ) if county_rows else "无"
            return QueryResult(
                answer=f"{prefix}虫情严重度最高的Top{len(city_rows) or min(max(top_n, 3), 5)}市为：{city_text}。再细到县，Top{len(county_rows) or max(top_n, 5)}区县为：{county_text}",
                data={"top_cities": city_rows, "top_counties": county_rows},
                evidence={
                    "rule": "先按市级虫情严重度排行，再细到区县排行",
                    "sql": "top_pest_regions(city+county)",
                    "since": since,
                    "until": until,
                    "region_level": "city_then_county",
                    "city": None,
                    "county": None,
                    "samples": self.repo.sample_pest_records(since, until, 3),
                    "available_data_ranges": [],
                    "no_data_reasons": [],
                },
            )
        data = self.repo.top_pest_regions(since, until, region_level=region_level, top_n=top_n, city=city, county=county)
        scope_label = "区县" if region_level == "county" else "地区"
        if data:
            since_scope = self._format_since_scope(since)
            prefix = f"{since_scope}，" if since_scope else "历史上，"
            answer = f"{prefix}虫情严重度最高的Top{top_n}{scope_label}为："
            answer += "；".join(
                f"{idx+1}.{row['region_name']}（严重度{row['severity_score']}，记录{row['record_count']}条）"
                for idx, row in enumerate(data)
            )
        else:
            answer = "暂无可用虫情严重度数据。"
            suffix = self._available_pest_range_suffix()
            if suffix:
                answer = f"{answer}{suffix}"
        return QueryResult(
            answer=answer,
            data=data,
            evidence={
                "rule": "虫情严重度=可解释记录的 normalized_pest_count 求和；同分按记录数、活跃天数排序",
                "sql": "top_pest_regions",
                "since": since,
                "until": until,
                "region_level": region_level,
                "city": city,
                "county": county,
                "samples": self.repo.sample_pest_records(since, until, 3),
                "available_data_ranges": self._available_pest_ranges() if not data else [],
                "no_data_reasons": [
                    self._build_no_data_reason(
                        source="pest",
                        label="虫情监测数据",
                        since=since,
                        until=until,
                        time_range=self._available_pest_time_range(),
                    )
                ]
                if not data
                else [],
                "recovery_suggestions": self._build_recovery_suggestions(
                    question=question,
                    query_type="pest_top",
                    no_data_reason=self._build_no_data_reason(
                        source="pest",
                        label="虫情监测数据",
                        since=since,
                        until=until,
                        time_range=self._available_pest_time_range(),
                    ),
                    time_ranges=self._available_pest_ranges(),
                    top_n=top_n,
                )
                if not data
                else [],
            },
        )

    def _answer_soil_top(self, question: str, plan: dict) -> QueryResult:
        since = str(plan.get("since") or "1970-01-01 00:00:00")
        until = plan.get("until") or None
        region_level = str(plan.get("region_level") or "city")
        top_n = max(1, int(plan.get("top_n") or 1))
        if any(token in question for token in ["低墒", "偏低", "缺水", "干旱", "太干"]):
            anomaly_direction = "low"
        elif any(token in question for token in ["高墒", "偏高", "偏湿", "过湿", "涝渍"]):
            anomaly_direction = "high"
        else:
            anomaly_direction = None
        city = plan.get("city")
        county = plan.get("county")
        data = self.repo.top_soil_regions(
            since,
            until,
            region_level=region_level,
            top_n=top_n,
            anomaly_direction=anomaly_direction,
            city=city,
            county=county,
        )
        direction_text = "低墒" if anomaly_direction == "low" else ("高墒" if anomaly_direction == "high" else "异常")
        if data:
            since_scope = self._format_since_scope(since)
            prefix = f"{since_scope}，" if since_scope else "历史上，"
            answer = f"{prefix}墒情{direction_text}最多的地区为："
            answer += "；".join(
                f"{idx+1}.{row['region_name']}（异常强度{row['anomaly_score']}，异常{row['abnormal_count']}条，低墒{row['low_count']}，高墒{row['high_count']}）"
                for idx, row in enumerate(data)
            )
        else:
            answer = "暂无可用于地区统计的墒情异常数据。"
            suffix = self._available_soil_range_suffix(anomaly_direction=anomaly_direction)
            if suffix:
                answer = f"{answer}{suffix}"
        return QueryResult(
            answer=answer,
            data=data,
            evidence={
                "rule": "第一版墒情异常：water20cm<50 记低墒，>150 记高墒；异常评分按偏离阈值计算",
                "sql": "top_soil_regions",
                "since": since,
                "until": until,
                "region_level": region_level,
                "city": city,
                "county": county,
                "mapping_notice": "墒情地区字段来自主表或辅助告警映射，未映射设备会落入未知地区",
                "samples": self.repo.sample_soil_records(since, until, 3),
                "available_data_ranges": self._available_soil_ranges(anomaly_direction=anomaly_direction) if not data else [],
                "no_data_reasons": [
                    self._build_no_data_reason(
                        source="soil",
                        label="墒情监测数据",
                        since=since,
                        until=until,
                        time_range=self._available_soil_time_range(anomaly_direction=anomaly_direction),
                    )
                ]
                if not data
                else [],
                "recovery_suggestions": self._build_recovery_suggestions(
                    question=question,
                    query_type="soil_top",
                    no_data_reason=self._build_no_data_reason(
                        source="soil",
                        label="墒情监测数据",
                        since=since,
                        until=until,
                        time_range=self._available_soil_time_range(anomaly_direction=anomaly_direction),
                    ),
                    time_ranges=self._available_soil_ranges(anomaly_direction=anomaly_direction),
                    top_n=top_n,
                    anomaly_direction=anomaly_direction,
                )
                if not data
                else [],
            },
        )

    def _answer_pest_trend(self, question: str, plan: dict) -> QueryResult:
        since = str(plan.get("since") or "1970-01-01 00:00:00")
        until = plan.get("until") or None
        region_name, region_level = self._extract_region(question, plan)
        data = self.repo.pest_trend(since, until, region_name or None, region_level=region_level)
        since_scope = self._format_since_scope(since)
        scope_prefix = self._scope_prefix(region_name, since_scope)
        no_data_reason = self._build_no_data_reason(
            source="pest",
            label="虫情监测数据",
            since=since,
            until=until,
            time_range=self._available_pest_time_range(),
            region_name=region_name,
        )
        recovery_suggestions = self._build_recovery_suggestions(
            question=question,
            query_type="pest_trend",
            no_data_reason=no_data_reason,
            time_ranges=self._available_pest_ranges(),
            region_name=region_name,
        )
        if not data:
            answer = self._compose_no_data_answer(
                base_answer=f"{scope_prefix}暂无可用虫情趋势数据。",
                no_data_reason=no_data_reason,
                range_suffix=self._available_pest_range_suffix(),
                recovery_suggestions=recovery_suggestions,
            )
            return QueryResult(
                answer=answer,
                data=data,
                evidence={
                    "rule": "按日汇总 normalized_pest_count 观察趋势",
                    "sql": "pest_trend",
                    "region_name": region_name,
                    "region_level": region_level,
                    "since": since,
                    "until": until,
                    "available_data_ranges": self._available_pest_ranges(),
                    "no_data_reasons": [no_data_reason],
                    "recovery_suggestions": recovery_suggestions,
                },
            )
        trend = self._trend_text(data, "severity_score")
        answer = self._build_trend_answer(
            question=question,
            scope_prefix=scope_prefix,
            topic_label="虫情",
            trend=trend,
            first=self._first_metric(data, "severity_score"),
            latest=self._latest_metric(data, "severity_score"),
            peak=self._peak_metric(data, "severity_score"),
            coverage_days=len(data),
            domain="pest",
        )
        return QueryResult(
            answer=answer,
            data=data,
            evidence={
                "rule": "按日汇总 normalized_pest_count 观察趋势",
                "sql": "pest_trend",
                "region_name": region_name,
                "region_level": region_level,
                "since": since,
                "until": until,
                "available_data_ranges": [],
                "no_data_reasons": [],
            },
        )

    @staticmethod
    def _latest_metric(series: list[dict], key: str) -> float:
        if not series:
            return 0.0
        return float(series[-1].get(key) or 0)

    @staticmethod
    def _peak_metric(series: list[dict], key: str) -> float:
        if not series:
            return 0.0
        return max(float(item.get(key) or 0) for item in series)

    @staticmethod
    def _series_date_value(item: dict) -> str:
        return str(item.get("date") or item.get("bucket") or "")

    @staticmethod
    def _detail_preview(series: list[dict], value_key: str, value_label: str, limit: int = 7) -> str:
        preview = list(series[-limit:]) if len(series) > limit else list(series)
        return "；".join(f"{QueryEngine._series_date_value(item)} {value_label}{QueryEngine._format_metric_value(float(item.get(value_key) or 0))}" for item in preview)

    @staticmethod
    def _average_metric(series: list[dict], key: str) -> float:
        if not series:
            return 0.0
        return sum(float(item.get(key) or 0) for item in series) / len(series)

    @staticmethod
    def _peak_point(series: list[dict], key: str) -> dict:
        if not series:
            return {}
        return max(series, key=lambda item: float(item.get(key) or 0))

    @staticmethod
    def _format_metric_value(value: float) -> str:
        if float(value).is_integer():
            return f"{value:.0f}"
        return f"{value:.1f}"

    def _build_detail_answer(
        self,
        *,
        region_name: str,
        since_scope: str,
        series: list[dict],
        value_key: str,
        value_label: str,
        topic_label: str,
    ) -> str:
        preview_limit = min(len(series), 7)
        latest_point = series[-1] if series else {}
        peak_point = self._peak_point(series, value_key)
        active_days = sum(1 for item in series if float(item.get(value_key) or 0) > 0)
        average_value = self._average_metric(series, value_key)
        preview_text = self._detail_preview(series, value_key, value_label, limit=preview_limit)

        lines = [
            f"{region_name}{since_scope}{topic_label}具体数据摘要：",
            f"- 共{len(series)}个观测日，其中{active_days}天{value_label}大于0",
            f"- 峰值{self._format_metric_value(float(peak_point.get(value_key) or 0))}（{self._series_date_value(peak_point)}）",
            f"- 最近值{self._format_metric_value(float(latest_point.get(value_key) or 0))}（{self._series_date_value(latest_point)}）",
            f"- 均值{self._format_metric_value(average_value)}",
            f"- 最近{preview_limit}个观测日：{preview_text}",
            "- 如果你要，我可以继续给你完整逐日明细或导出表格。",
        ]
        return "\n".join(lines)

    def _answer_pest_detail(self, question: str, plan: dict) -> QueryResult:
        since = str(plan.get("since") or "1970-01-01 00:00:00")
        until = plan.get("until") or None
        region_name, region_level = self._extract_region(question, plan)
        if not region_name:
            return QueryResult(answer="请补充要看的地区，比如某个市或区县。", data=[], evidence={})
        data = self.repo.pest_trend(since, until, region_name, region_level=region_level)
        since_scope = self._format_since_scope(since)
        if not data:
            answer = f"{region_name}{since_scope}暂无可用虫情具体数据。"
            suffix = self._available_pest_range_suffix()
            if suffix:
                answer = f"{answer}{suffix}"
            no_data_reason = self._build_no_data_reason(
                source="pest",
                label="虫情监测数据",
                since=since,
                until=until,
                time_range=self._available_pest_time_range(),
                region_name=region_name,
            )
            return QueryResult(
                answer=answer,
                data=data,
                evidence={
                    "rule": "按日汇总 normalized_pest_count 输出地区虫情具体值",
                    "sql": "pest_trend",
                    "query_type": "pest_detail",
                    "region_name": region_name,
                    "region_level": region_level,
                    "since": since,
                    "until": until,
                    "available_data_ranges": self._available_pest_ranges(),
                    "no_data_reasons": [no_data_reason],
                    "recovery_suggestions": self._build_recovery_suggestions(
                        question=question,
                        query_type="pest_detail",
                        no_data_reason=no_data_reason,
                        time_ranges=self._available_pest_ranges(),
                        region_name=region_name,
                    ),
                },
            )
        answer = self._build_detail_answer(
            region_name=region_name,
            since_scope=since_scope,
            series=data,
            value_key="severity_score",
            value_label="严重度",
            topic_label="虫情",
        )
        return QueryResult(
            answer=answer,
            data=data,
            evidence={
                "rule": "按日汇总 normalized_pest_count 输出地区虫情具体值",
                "sql": "pest_trend",
                "query_type": "pest_detail",
                "region_name": region_name,
                "region_level": region_level,
                "since": since,
                "until": until,
                "available_data_ranges": [],
                "no_data_reasons": [],
            },
        )

    def _answer_pest_overview(self, question: str, plan: dict) -> QueryResult:
        since = str(plan.get("since") or "1970-01-01 00:00:00")
        until = plan.get("until") or None
        region_name, region_level = self._extract_region(question, plan)
        data = self.repo.pest_trend(since, until, region_name or None, region_level=region_level)
        since_scope = self._format_since_scope(since)
        scope_prefix = self._scope_prefix(region_name, since_scope)
        if not data:
            answer = f"{scope_prefix}暂无可用虫情概况数据。"
            suffix = self._available_pest_range_suffix()
            if suffix:
                answer = f"{answer}{suffix}"
            no_data_reason = self._build_no_data_reason(
                source="pest",
                label="虫情监测数据",
                since=since,
                until=until,
                time_range=self._available_pest_time_range(),
                region_name=region_name,
            )
            return QueryResult(
                answer=answer,
                data=data,
                evidence={
                    "rule": "复用按日汇总 normalized_pest_count 的趋势数据生成地区概况",
                    "sql": "pest_trend",
                    "query_type": "pest_overview",
                    "region_name": region_name,
                    "region_level": region_level,
                    "since": since,
                    "until": until,
                    "available_data_ranges": self._available_pest_ranges(),
                    "no_data_reasons": [no_data_reason],
                    "recovery_suggestions": self._build_recovery_suggestions(
                        question=question,
                        query_type="pest_trend",
                        no_data_reason=no_data_reason,
                        time_ranges=self._available_pest_ranges(),
                        region_name=region_name,
                    ),
                },
            )
        trend = self._trend_text(data, "severity_score")
        latest = self._latest_metric(data, "severity_score")
        peak = self._peak_metric(data, "severity_score")
        answer = f"{scope_prefix}虫情概况：{trend}，最近值{latest:g}，峰值{peak:g}，共覆盖{len(data)}个观测日。"
        return QueryResult(
            answer=answer,
            data=data,
            evidence={
                "rule": "复用按日汇总 normalized_pest_count 的趋势数据生成地区概况",
                "sql": "pest_trend",
                "query_type": "pest_overview",
                "region_name": region_name,
                "region_level": region_level,
                "since": since,
                "until": until,
                "available_data_ranges": [],
                "no_data_reasons": [],
            },
        )

    def _answer_soil_trend(self, question: str, plan: dict) -> QueryResult:
        since = str(plan.get("since") or "1970-01-01 00:00:00")
        until = plan.get("until") or None
        region_name, region_level = self._extract_region(question, plan)
        data = self.repo.soil_trend(since, until, region_name or None, region_level=region_level)
        since_scope = self._format_since_scope(since)
        scope_prefix = self._scope_prefix(region_name, since_scope)
        no_data_reason = self._build_no_data_reason(
            source="soil",
            label="墒情监测数据",
            since=since,
            until=until,
            time_range=self._available_soil_time_range(),
            region_name=region_name,
        )
        recovery_suggestions = self._build_recovery_suggestions(
            question=question,
            query_type="soil_trend",
            no_data_reason=no_data_reason,
            time_ranges=self._available_soil_ranges(),
            region_name=region_name,
        )
        if not data:
            answer = self._compose_no_data_answer(
                base_answer=f"{scope_prefix}暂无可用墒情趋势数据。",
                no_data_reason=no_data_reason,
                range_suffix=self._available_soil_range_suffix(),
                recovery_suggestions=recovery_suggestions,
            )
            return QueryResult(
                answer=answer,
                data=data,
                evidence={
                    "rule": "按日汇总平均含水量与平均异常评分观察趋势",
                    "sql": "soil_trend",
                    "region_name": region_name,
                    "region_level": region_level,
                    "since": since,
                    "until": until,
                    "available_data_ranges": self._available_soil_ranges(),
                    "no_data_reasons": [no_data_reason],
                    "recovery_suggestions": recovery_suggestions,
                },
            )
        trend = self._trend_text(data, "avg_anomaly_score")
        answer = self._build_trend_answer(
            question=question,
            scope_prefix=scope_prefix,
            topic_label="墒情",
            trend=trend,
            first=self._first_metric(data, "avg_anomaly_score"),
            latest=self._latest_metric(data, "avg_anomaly_score"),
            peak=self._peak_metric(data, "avg_anomaly_score"),
            coverage_days=len(data),
            domain="soil",
        )
        return QueryResult(
            answer=answer,
            data=data,
            evidence={
                "rule": "按日汇总平均含水量与平均异常评分观察趋势",
                "sql": "soil_trend",
                "region_name": region_name,
                "region_level": region_level,
                "since": since,
                "until": until,
                "available_data_ranges": [],
                "no_data_reasons": [],
            },
        )

    def _answer_soil_overview(self, question: str, plan: dict) -> QueryResult:
        since = str(plan.get("since") or "1970-01-01 00:00:00")
        until = plan.get("until") or None
        region_name, region_level = self._extract_region(question, plan)
        data = self.repo.soil_trend(since, until, region_name or None, region_level=region_level)
        since_scope = self._format_since_scope(since)
        scope_prefix = self._scope_prefix(region_name, since_scope)
        if not data:
            answer = f"{scope_prefix}暂无可用墒情概况数据。"
            suffix = self._available_soil_range_suffix()
            if suffix:
                answer = f"{answer}{suffix}"
            no_data_reason = self._build_no_data_reason(
                source="soil",
                label="墒情监测数据",
                since=since,
                until=until,
                time_range=self._available_soil_time_range(),
                region_name=region_name,
            )
            return QueryResult(
                answer=answer,
                data=data,
                evidence={
                    "rule": "复用按日汇总平均异常评分的趋势数据生成地区概况",
                    "sql": "soil_trend",
                    "query_type": "soil_overview",
                    "region_name": region_name,
                    "region_level": region_level,
                    "since": since,
                    "until": until,
                    "available_data_ranges": self._available_soil_ranges(),
                    "no_data_reasons": [no_data_reason],
                    "recovery_suggestions": self._build_recovery_suggestions(
                        question=question,
                        query_type="soil_trend",
                        no_data_reason=no_data_reason,
                        time_ranges=self._available_soil_ranges(),
                        region_name=region_name,
                    ),
                },
            )
        trend = self._trend_text(data, "avg_anomaly_score")
        latest = self._latest_metric(data, "avg_anomaly_score")
        peak = self._peak_metric(data, "avg_anomaly_score")
        answer = f"{scope_prefix}墒情概况：{trend}，最近异常值{latest:g}，峰值{peak:g}，共覆盖{len(data)}个观测日。"
        return QueryResult(
            answer=answer,
            data=data,
            evidence={
                "rule": "复用按日汇总平均异常评分的趋势数据生成地区概况",
                "sql": "soil_trend",
                "query_type": "soil_overview",
                "region_name": region_name,
                "region_level": region_level,
                "since": since,
                "until": until,
                "available_data_ranges": [],
                "no_data_reasons": [],
            },
        )

    def _answer_soil_detail(self, question: str, plan: dict) -> QueryResult:
        since = str(plan.get("since") or "1970-01-01 00:00:00")
        until = plan.get("until") or None
        region_name, region_level = self._extract_region(question, plan)
        if not region_name:
            return QueryResult(answer="请补充要看的地区，比如某个市或区县。", data=[], evidence={})
        data = self.repo.soil_trend(since, until, region_name, region_level=region_level)
        since_scope = self._format_since_scope(since)
        if not data:
            answer = f"{region_name}{since_scope}暂无可用墒情具体数据。"
            suffix = self._available_soil_range_suffix()
            if suffix:
                answer = f"{answer}{suffix}"
            no_data_reason = self._build_no_data_reason(
                source="soil",
                label="墒情监测数据",
                since=since,
                until=until,
                time_range=self._available_soil_time_range(),
                region_name=region_name,
            )
            return QueryResult(
                answer=answer,
                data=data,
                evidence={
                    "rule": "按日汇总平均异常评分输出地区墒情具体值",
                    "sql": "soil_trend",
                    "query_type": "soil_detail",
                    "region_name": region_name,
                    "region_level": region_level,
                    "since": since,
                    "until": until,
                    "available_data_ranges": self._available_soil_ranges(),
                    "no_data_reasons": [no_data_reason],
                    "recovery_suggestions": self._build_recovery_suggestions(
                        question=question,
                        query_type="soil_detail",
                        no_data_reason=no_data_reason,
                        time_ranges=self._available_soil_ranges(),
                        region_name=region_name,
                    ),
                },
            )
        answer = self._build_detail_answer(
            region_name=region_name,
            since_scope=since_scope,
            series=data,
            value_key="avg_anomaly_score",
            value_label="异常值",
            topic_label="墒情",
        )
        return QueryResult(
            answer=answer,
            data=data,
            evidence={
                "rule": "按日汇总平均异常评分输出地区墒情具体值",
                "sql": "soil_trend",
                "query_type": "soil_detail",
                "region_name": region_name,
                "region_level": region_level,
                "since": since,
                "until": until,
                "available_data_ranges": [],
                "no_data_reasons": [],
            },
        )

    def _answer_joint_risk(self, question: str, plan: dict) -> QueryResult:
        since = str(plan.get("since") or "1970-01-01 00:00:00")
        until = plan.get("until") or None
        region_level = str(plan.get("region_level") or "city")
        data = self.repo.joint_risk_regions(since, until, region_level=region_level, top_n=5)
        if data:
            answer = f"从{since[:10]}起，同时出现高虫情和低墒情的联合风险地区为："
            answer += "；".join(
                f"{idx+1}.{row['region_name']}（联合得分{row['joint_score']}，虫情{row['pest_score']}，低墒{row['low_soil_score']}）"
                for idx, row in enumerate(data)
            )
        else:
            answer = "暂无满足联合风险条件的地区。"
            pest_suffix = self._available_pest_range_suffix()
            soil_suffix = self._available_soil_range_suffix(anomaly_direction="low")
            if pest_suffix:
                answer = f"{answer}{pest_suffix}"
            if soil_suffix:
                answer = f"{answer}{soil_suffix}"
        return QueryResult(
            answer=answer,
            data=data,
            evidence={
                "rule": "地区联合风险=虫情严重度 + 低墒异常强度",
                "sql": "joint_risk_regions",
                "since": since,
                "until": until,
                "region_level": region_level,
                "available_data_ranges": (self._available_pest_ranges() + self._available_soil_ranges(anomaly_direction="low")) if not data else [],
                "no_data_reasons": [
                    {
                        "source": "joint_risk",
                        "code": "no_joint_risk_matches",
                        "message": "当前时间窗与筛选条件下暂无同时满足高虫情和低墒情的联合样本。",
                    }
                ]
                if not data
                else [],
                "recovery_suggestions": self._build_recovery_suggestions(
                    question=question,
                    query_type="joint_risk",
                    no_data_reason={
                        "source": "joint_risk",
                        "code": "no_joint_risk_matches",
                        "message": "当前时间窗与筛选条件下暂无同时满足高虫情和低墒情的联合样本。",
                    },
                    time_ranges=self._available_pest_ranges() + self._available_soil_ranges(anomaly_direction="low"),
                )
                if not data
                else [],
            },
        )

    def _answer_alerts_trend(self, question: str, plan: dict) -> QueryResult:
        since = str(plan.get("since") or "1970-01-01 00:00:00")
        until = plan.get("until") or None
        city = plan.get("city") or self._extract_city(question)
        data = self.repo.alerts_trend(since, until, city=city) if hasattr(self.repo, "alerts_trend") else []
        since_scope = self._format_since_scope(since)
        scope_prefix = self._scope_prefix(city, since_scope)
        if not data:
            answer = f"{scope_prefix}暂无可用预警趋势数据。"
            suffix = self._available_alert_range_suffix()
            if suffix:
                answer = f"{answer}{suffix}"
            return QueryResult(
                answer=answer,
                data=data,
                evidence={
                    "sql": "alerts_trend",
                    "query_type": "alerts_trend",
                    "since": since,
                    "until": until,
                    "city": city,
                    "available_data_ranges": self._available_alert_ranges(),
                    "no_data_reasons": [
                        self._build_no_data_reason(
                            source="alerts",
                            label="告警数据",
                            since=since,
                            until=until,
                            time_range=self.repo.available_alert_time_range() if hasattr(self.repo, "available_alert_time_range") else None,
                            region_name=city or "",
                        )
                    ],
                },
            )
        trend = self._trend_text(data, "alert_count")
        latest = int(self._latest_metric(data, "alert_count"))
        first = int(float(data[0].get("alert_count") or 0))
        answer = f"{scope_prefix}预警数量趋势：{trend}，起点{first}条，最近{latest}条，共覆盖{len(data)}个观测日。"
        return QueryResult(
            answer=answer,
            data=data,
            evidence={
                "sql": "alerts_trend",
                "query_type": "alerts_trend",
                "since": since,
                "until": until,
                "city": city,
                "available_data_ranges": [],
                "no_data_reasons": [],
            },
        )

    def _answer_alerts_top(self, question: str, plan: dict) -> QueryResult:
        """返回预警/报警 Top 排行。"""
        since = str(plan.get("since") or self._extract_since(question))
        field = str(plan.get("field", "")).strip() or ("county" if "区县" in question or "县" in question else "city")
        top_n = int(plan.get("top_n") or 5)
        day_start, day_end = self._extract_day_range(question)
        if day_start:
            since = day_start
        data = self.repo.top_n_filtered(field, top_n, since, until=day_end) if hasattr(self.repo, "top_n_filtered") else self.repo.top_n(field, top_n, since)
        if data:
            answer = f"自{since[:10]}以来，Top{top_n}为：" + "；".join([f"{i+1}.{r['name']}({r['count']})" for i, r in enumerate(data)])
        else:
            suffix = self._available_alert_range_suffix()
            answer = f"自{since[:10]}以来，暂无可用于 Top{top_n} 排行的数据。"
            if suffix:
                answer = f"{answer}{suffix}"
        return QueryResult(
            answer=answer,
            data=data,
            evidence={
                "sql": f"SELECT {field}, COUNT(*) FROM alerts WHERE alert_time >= ? GROUP BY {field} ORDER BY COUNT(*) DESC LIMIT {top_n}",
                "since": since,
                "query_type": "alerts_top",
                "available_data_ranges": self._available_alert_ranges() if not data else [],
                "no_data_reasons": [
                    self._build_no_data_reason(
                        source="alerts",
                        label="告警数据",
                        since=since,
                        until=day_end,
                        time_range=self.repo.available_alert_time_range() if hasattr(self.repo, "available_alert_time_range") else None,
                    )
                ]
                if not data
                else [],
                "recovery_suggestions": self._build_recovery_suggestions(
                    question=question,
                    query_type="top",
                    no_data_reason=self._build_no_data_reason(
                        source="alerts",
                        label="告警数据",
                        since=since,
                        until=day_end,
                        time_range=self.repo.available_alert_time_range() if hasattr(self.repo, "available_alert_time_range") else None,
                    ),
                    time_ranges=self._available_alert_ranges(),
                    top_n=top_n,
                    field=field,
                )
                if not data
                else [],
            },
        )

    @staticmethod
    def _rank_score(index: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return round((total - index) / total, 4)

    def _build_cross_signal_gap_rows(
        self,
        *,
        primary_rows: list[dict],
        secondary_rows: list[dict],
        primary_key: str,
        secondary_key: str,
        top_n: int,
    ) -> list[dict]:
        primary_total = len(primary_rows)
        secondary_total = len(secondary_rows)
        primary_map = {
            str(row.get("region_name") or row.get("name") or ""): {
                "value": float(row.get(primary_key) or row.get("count") or 0),
                "rank_score": self._rank_score(index, primary_total),
            }
            for index, row in enumerate(primary_rows)
            if str(row.get("region_name") or row.get("name") or "")
        }
        secondary_map = {
            str(row.get("region_name") or row.get("name") or ""): {
                "value": float(row.get(secondary_key) or row.get("count") or 0),
                "rank_score": self._rank_score(index, secondary_total),
            }
            for index, row in enumerate(secondary_rows)
            if str(row.get("region_name") or row.get("name") or "")
        }
        candidates: list[dict] = []
        for region_name, primary_meta in primary_map.items():
            secondary_meta = secondary_map.get(region_name, {"value": 0.0, "rank_score": 0.0})
            gap_score = round(primary_meta["rank_score"] - secondary_meta["rank_score"], 4)
            if primary_meta["value"] <= 0 or gap_score <= 0:
                continue
            candidates.append(
                {
                    "region_name": region_name,
                    "primary_value": primary_meta["value"],
                    "secondary_value": secondary_meta["value"],
                    "gap_score": gap_score,
                }
            )
        candidates.sort(key=lambda item: (-item["gap_score"], -item["primary_value"], item["secondary_value"], item["region_name"]))
        return candidates[:top_n]

    def _answer_alerts_high_pest_low(self, question: str, plan: dict) -> QueryResult:
        since = str(plan.get("since") or "1970-01-01 00:00:00")
        until = plan.get("until") or None
        region_level = str(plan.get("region_level") or "county")
        top_n = max(1, int(plan.get("top_n") or 5))
        field = "county" if region_level == "county" else "city"
        alert_rows = self.repo.top_n_filtered(field, max(top_n * 4, 12), since, until=until) if hasattr(self.repo, "top_n_filtered") else []
        pest_rows = self.repo.top_pest_regions(since, until, region_level=region_level, top_n=max(top_n * 4, 12), city=plan.get("city"), county=plan.get("county")) if hasattr(self.repo, "top_pest_regions") else []
        data = self._build_cross_signal_gap_rows(
            primary_rows=[{"region_name": row.get("name"), "count": row.get("count")} for row in alert_rows],
            secondary_rows=pest_rows,
            primary_key="count",
            secondary_key="severity_score",
            top_n=top_n,
        )
        if not data:
            return QueryResult(
                answer="当前没有识别出“预警多但虫情并不高”的明显县级地区。",
                data=[],
                evidence={"sql": "alerts_top + top_pest_regions", "query_type": "alerts_high_pest_low", "since": since, "until": until},
            )
        details = "；".join(
            f"{idx+1}.{row['region_name']}（预警{int(row['primary_value'])}条，虫情严重度{self._format_metric_value(row['secondary_value'])}，反差{row['gap_score']:.2f}）"
            for idx, row in enumerate(data)
        )
        return QueryResult(
            answer=f"从{since[:10]}起，预警多但虫情并不高的重点县为：{details}",
            data=data,
            evidence={"sql": "alerts_top + top_pest_regions", "query_type": "alerts_high_pest_low", "since": since, "until": until, "region_level": region_level},
        )

    def _answer_pest_high_alerts_low(self, question: str, plan: dict) -> QueryResult:
        since = str(plan.get("since") or "1970-01-01 00:00:00")
        until = plan.get("until") or None
        region_level = str(plan.get("region_level") or "county")
        top_n = max(1, int(plan.get("top_n") or 5))
        field = "county" if region_level == "county" else "city"
        pest_rows = self.repo.top_pest_regions(since, until, region_level=region_level, top_n=max(top_n * 4, 12), city=plan.get("city"), county=plan.get("county")) if hasattr(self.repo, "top_pest_regions") else []
        alert_rows = self.repo.top_n_filtered(field, max(top_n * 4, 12), since, until=until) if hasattr(self.repo, "top_n_filtered") else []
        data = self._build_cross_signal_gap_rows(
            primary_rows=pest_rows,
            secondary_rows=[{"region_name": row.get("name"), "count": row.get("count")} for row in alert_rows],
            primary_key="severity_score",
            secondary_key="count",
            top_n=top_n,
        )
        if not data:
            return QueryResult(
                answer="当前没有识别出“虫情高但预警并不多”的明显县级地区。",
                data=[],
                evidence={"sql": "top_pest_regions + alerts_top", "query_type": "pest_high_alerts_low", "since": since, "until": until},
            )
        details = "；".join(
            f"{idx+1}.{row['region_name']}（虫情严重度{self._format_metric_value(row['primary_value'])}，预警{int(row['secondary_value'])}条，反差{row['gap_score']:.2f}）"
            for idx, row in enumerate(data)
        )
        return QueryResult(
            answer=f"从{since[:10]}起，虫情高但预警并不多的重点县为：{details}",
            data=data,
            evidence={"sql": "top_pest_regions + alerts_top", "query_type": "pest_high_alerts_low", "since": since, "until": until, "region_level": region_level},
        )

    def answer(self, question: str, plan: Optional[dict] = None) -> QueryResult:
        """执行查询计划并返回统一 QueryResult。"""
        plan = plan or {}
        query_type = str(plan.get("query_type") or "count")

        if hasattr(self.repo, "top_pest_regions"):
            # 新版结构化仓储路径：优先命中细分查询分支。
            if query_type == "alerts_top":
                return self._answer_alerts_top(question, plan)
            if query_type == "alerts_high_pest_low":
                return self._answer_alerts_high_pest_low(question, plan)
            if query_type == "alerts_trend":
                return self._answer_alerts_trend(question, plan)
            if query_type == "pest_top":
                return self._answer_pest_top(question, plan)
            if query_type == "pest_high_alerts_low":
                return self._answer_pest_high_alerts_low(question, plan)
            if query_type == "soil_top":
                return self._answer_soil_top(question, plan)
            if query_type == "pest_detail":
                return self._answer_pest_detail(question, plan)
            if query_type == "pest_overview":
                return self._answer_pest_overview(question, plan)
            if query_type == "soil_detail":
                return self._answer_soil_detail(question, plan)
            if query_type == "soil_overview":
                return self._answer_soil_overview(question, plan)
            if query_type == "pest_trend":
                return self._answer_pest_trend(question, plan)
            if query_type == "soil_trend":
                return self._answer_soil_trend(question, plan)
            if query_type == "joint_risk":
                return self._answer_joint_risk(question, plan)
            if query_type == "structured_agri":
                if "虫" in question:
                    return self._answer_pest_top(question, plan)
                return self._answer_soil_top(question, plan)

        if query_type == "alerts_trend":
            return self._answer_alerts_trend(question, plan)

        # 旧版 SQLite 告警数据回退路径：当结构化接口不可用时使用。
        since = str(plan.get("since") or self._extract_since(question))

        if query_type in {"pest_top", "soil_top", "structured_agri"}:
            field = "county" if "区县" in question or "县" in question else "city"
            top_n = int(plan.get("top_n") or 5)
            data = self.repo.top_n_filtered(field, top_n, since) if hasattr(self.repo, "top_n_filtered") else self.repo.top_n(field, top_n, since)
            label = "虫情" if query_type == "pest_top" or "虫" in question else "墒情"
            answer = f"自{since[:10]}以来，{label}最需要关注的Top{top_n}地区为：" + "；".join(
                [f"{i+1}.{r['name']}({r['count']})" for i, r in enumerate(data)]
            )
            return QueryResult(
                answer=answer,
                data=data,
                evidence={
                    "sql": f"SELECT {field}, COUNT(*) FROM alerts WHERE alert_time >= ? GROUP BY {field} ORDER BY COUNT(*) DESC LIMIT {top_n}",
                    "since": since,
                    "query_type": query_type,
                },
            )

        if query_type in {"top", "alerts_top"}:
            return self._answer_alerts_top(question, plan)

        if query_type == "highest_values":
            m = re.search(r"最高的(\d+)条", question)
            limit = int(m.group(1)) if m else 10
            data = self.repo.highest_alert_values(limit=limit)
            if data:
                details = "；".join(
                    f"{idx+1}.{row.get('alert_time', '')[:10]} {row.get('city', '')}{row.get('county', '')} "
                    f"{row.get('device_code', '')} 告警值{row.get('alert_value')}"
                    for idx, row in enumerate(data)
                )
                answer = f"告警值最高的{limit}条记录为：{details}"
            else:
                answer = f"暂无告警值最高的{limit}条记录。"
            return QueryResult(
                answer=answer,
                data=data,
                evidence={"sql": "SELECT ... ORDER BY CAST(alert_value AS REAL) DESC LIMIT ?", "limit": limit},
            )

        if query_type == "threshold_summary":
            threshold = self._extract_threshold(question) or 150.0
            day_start, day_end = self._extract_day_range(question)
            if day_start:
                since = day_start
            data = self.repo.top_n_filtered("city", 5, since, until=day_end, min_alert_value=threshold)
            above_count = self.repo.count_alert_value_above(threshold, since, day_end)
            city_summary = "；".join([f"{r['name']}({r['count']})" for r in data]) if data else "无"
            return QueryResult(
                answer=f"自{since[:10]}以来，告警值超过{threshold:g}的预警共{above_count}条，主要集中在：{city_summary}",
                data={"above_threshold_count": above_count, "top_cities": data},
                evidence={"sql": "SELECT city, COUNT(*) FROM alerts WHERE CAST(alert_value AS REAL) > ? GROUP BY city", "threshold": threshold, "since": since, "until": day_end},
            )

        if query_type == "avg_by_level":
            data = self.repo.avg_alert_value_by_level(since)
            details = "；".join([f"{r['level']}={r['avg_alert_value']}" for r in data]) if data else "无"
            return QueryResult(
                answer=f"自{since[:10]}以来，各告警等级平均告警值为：{details}。",
                data=data,
                evidence={"sql": "SELECT alert_level, AVG(CAST(alert_value AS REAL)) FROM alerts WHERE alert_time >= ? GROUP BY alert_level", "since": since},
            )

        if query_type == "consecutive_devices":
            min_days = int(plan.get("min_days") or 2)
            data = self.repo.devices_triggered_on_multiple_days(since, min_days=min_days)
            details = "；".join([f"{r['device_code']}({r['active_days']}天)" for r in data[:10]]) if data else "无"
            return QueryResult(
                answer=f"自{since[:10]}以来，连续至少{min_days}天触发预警的设备有：{details}。",
                data=data,
                evidence={"sql": "SELECT device_code ... HAVING day_cnt >= ?", "since": since, "min_days": min_days},
            )

        if query_type == "active_devices":
            top_n = max(1, int(plan.get("top_n") or 10))
            until = plan.get("until") or None
            data = self.repo.top_active_devices(since, until=until, limit=top_n)
            since_scope = self._format_since_scope(since)
            prefix = f"{since_scope}，" if since_scope else "历史上，"
            details = "；".join(
                f"{idx+1}.{row['device_code']}（预警{row['alert_count']}次，活跃{row['active_days']}天）"
                for idx, row in enumerate(data)
            ) if data else "无"
            answer = f"{prefix}最活跃的Top{top_n}台设备为：{details}。"
            return QueryResult(
                answer=answer,
                data=data,
                evidence={"sql": "top_active_devices", "since": since, "until": until, "top_n": top_n},
            )

        if query_type == "unknown_region_devices":
            data = self.repo.unknown_region_devices(limit=max(1, int(plan.get("top_n") or 20)))
            if data:
                details = "；".join(
                    f"{idx+1}.{row['device_code']}（{row.get('device_name') or '未命名设备'}，出现{row['alert_count']}次）"
                    for idx, row in enumerate(data)
                )
                answer = f"未知区域对应的设备有：{details}。"
            else:
                answer = "当前没有落入未知区域的设备。"
            return QueryResult(
                answer=answer,
                data=data,
                evidence={"sql": "unknown_region_devices"},
            )

        if query_type == "empty_county_records":
            rows = self.repo.empty_county_records(limit=max(1, int(plan.get("top_n") or 20)))
            if rows:
                details = "；".join(
                    f"{idx+1}.{row.get('alert_time', '')[:10]} {row.get('device_code') or ''}"
                    for idx, row in enumerate(rows[:10])
                )
                answer = f"县字段为空的记录共{len(rows)}条，示例：{details}。"
            else:
                answer = "当前没有县字段为空的记录。"
            return QueryResult(
                answer=answer,
                data=rows,
                evidence={"sql": "empty_county_records"},
            )

        if query_type == "unmatched_region_records":
            rows = self.repo.unmatched_region_records(limit=max(1, int(plan.get("top_n") or 20)))
            if rows:
                details = "；".join(
                    f"{idx+1}.{row.get('alert_time', '')[:10]} {row.get('device_code') or ''}"
                    for idx, row in enumerate(rows[:10])
                )
                answer = f"没有匹配到区域的数据共{len(rows)}条，示例：{details}。"
            else:
                answer = "当前没有未匹配到区域的数据。"
            return QueryResult(
                answer=answer,
                data=rows,
                evidence={"sql": "unmatched_region_records"},
            )

        if query_type == "latest_device":
            m = re.search(r"(SNS\d+)", question)
            if not m:
                return QueryResult(answer="未识别到设备编码。", data=[], evidence={"sql": ""})
            device_code = m.group(1)
            row = self.repo.latest_by_device(device_code)
            if row is None:
                return QueryResult(answer=f"未找到设备{device_code}的预警记录。", data=[], evidence={"sql": "SELECT ... WHERE device_code = ?"})
            disposal = str(row.get("disposal_suggestion") or "").strip()
            disposal_text = f"，处置建议：{disposal}" if disposal else ""
            return QueryResult(
                answer=f"设备{device_code}最近一次预警时间{row['alert_time']}，等级{row['alert_level']}{disposal_text}。",
                data=[row],
                evidence={"sql": "SELECT ... WHERE device_code = ? ORDER BY alert_time DESC LIMIT 1"},
            )

        if query_type == "latest_soil_device":
            device_code = str(plan.get("device_code") or "")
            if not device_code:
                m = re.search(r"(SNS\d+)", question)
                device_code = m.group(1) if m else ""
            if not device_code:
                return QueryResult(answer="未识别到设备编码。", data=[], evidence={"sql": ""})
            row = self.repo.latest_soil_by_device(device_code) if hasattr(self.repo, "latest_soil_by_device") else None
            if row is None:
                return QueryResult(answer=f"未找到设备{device_code}的墒情记录。", data=[], evidence={"sql": "latest_soil_by_device"})
            anomaly = str(row.get("soil_anomaly_type") or "normal")
            return QueryResult(
                answer=f"设备{device_code}最近一次墒情记录时间{row['sample_time']}，异常类型{anomaly}。",
                data=[row],
                evidence={"sql": "latest_soil_by_device", "query_type": "latest_soil_device"},
            )

        if query_type == "soil_abnormal_devices":
            top_n = max(1, int(plan.get("top_n") or 10))
            until = plan.get("until") or None
            city = plan.get("city")
            county = plan.get("county")
            data = self.repo.abnormal_soil_devices(since, until=until, city=city, county=county, limit=top_n) if hasattr(self.repo, "abnormal_soil_devices") else []
            scope_parts = [part for part in [city, county] if part]
            scope_text = "".join(scope_parts)
            prefix = f"{scope_text}墒情异常设备有：" if scope_text else "墒情异常设备有："
            details = "；".join(
                f"{idx+1}.{row['device_sn']}（{row.get('device_name') or '未命名设备'}，异常{row['abnormal_count']}次）"
                for idx, row in enumerate(data)
            ) if data else "无"
            return QueryResult(
                answer=f"{prefix}{details}。",
                data=data,
                evidence={"sql": "abnormal_soil_devices", "query_type": "soil_abnormal_devices", "city": city, "county": county, "since": since, "until": until},
            )

        if query_type == "soil_only_abnormal_devices":
            top_n = max(1, int(plan.get("top_n") or 10))
            until = plan.get("until") or None
            city = plan.get("city")
            county = plan.get("county")
            data = self.repo.soil_anomaly_devices_without_alerts(since, until=until, city=city, county=county, limit=top_n) if hasattr(self.repo, "soil_anomaly_devices_without_alerts") else []
            details = "；".join(
                f"{idx+1}.{row['device_sn']}（{row.get('device_name') or '未命名设备'}，墒情异常{row['abnormal_count']}次）"
                for idx, row in enumerate(data)
            ) if data else "无"
            return QueryResult(
                answer=f"最近时间窗内没有任何预警但有墒情异常的设备有：{details}。",
                data=data,
                evidence={"sql": "soil_anomaly_devices_without_alerts", "query_type": "soil_only_abnormal_devices", "city": city, "county": county, "since": since, "until": until},
            )

        if query_type == "region_disposal":
            city = self._extract_city(question)
            m = re.search(r"([\u4e00-\u9fa5]{1,12}(?:镇|街道))", question)
            region = m.group(1) if m else ""
            if city and region.startswith(city):
                region = region[len(city):]
            if not city or not region:
                return QueryResult(answer="未识别到城市或乡镇信息。", data=[], evidence={"sql": ""})
            row = self.repo.latest_by_region_keyword(city, region)
            if row is None:
                return QueryResult(answer=f"未找到{city}{region}相关预警记录。", data=[], evidence={"sql": "SELECT ... WHERE city = ? AND region_name LIKE ?"})
            return QueryResult(
                answer=f"{city}{region}最近一条处置建议：{row['disposal_suggestion']}",
                data=[row],
                evidence={"sql": "SELECT ... WHERE city = ? AND region_name LIKE ? ORDER BY alert_time DESC LIMIT 1"},
            )

        if query_type == "sms_empty":
            m = re.search(r"([\u4e00-\u9fa5]{1,12}(?:县|区))", question)
            county = m.group(1) if m else ""
            rows = self.repo.sms_empty_records(county)
            return QueryResult(
                answer=f"{county}中sms_content为空的记录共{len(rows)}条。",
                data=rows,
                evidence={"sql": "SELECT ... WHERE county = ? AND sms_content IS NULL/empty"},
            )

        if query_type == "subtype_ratio":
            ratio = self.repo.subtype_ratio("土壤墒情仪", "墒情预警", since)
            return QueryResult(
                answer=f"自{since[:10]}以来，土壤墒情仪类型中墒情预警占比{ratio['ratio_percent']}%（{ratio['subtype_count']}/{ratio['type_count']}）。",
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
            return QueryResult(
                answer=f"{city}{day1.strftime('%m月%d日')}到{day2.strftime('%m月%d日')}预警数量变化{diff:+d}（{c1}->{c2}）。",
                data=[{"city": city, "day1_count": c1, "day2_count": c2, "diff": diff}],
                evidence={"sql": "SELECT COUNT(*) ... city + day range"},
            )

        day_start, day_end = self._extract_day_range(question)
        if day_start:
            since = day_start
        city = self._extract_city(question)
        level = self._extract_level(question)
        count = self.repo.count_filtered(since, until=day_end, city=city, level=level) if hasattr(self.repo, "count_filtered") else self.repo.count_since(since)
        scope = ""
        if city:
            scope += city
        if level:
            scope += f"{level}等级"
        answer = f"自{since[:10]}以来，{scope}预警信息共 {count} 条。"
        if count == 0:
            suffix = self._available_alert_range_suffix()
            if suffix:
                answer = f"{answer}{suffix}"
        return QueryResult(
            answer=answer,
            data=[{"count": count}],
            evidence={
                "sql": "SELECT COUNT(*) FROM alerts WHERE alert_time >= ?",
                "since": since,
                "until": day_end,
                "city": city,
                "alert_level": level,
                "samples": self.repo.sample_alerts(since, 3) if hasattr(self.repo, 'sample_alerts') else [],
                "available_data_ranges": self._available_alert_ranges() if count == 0 else [],
                "no_data_reasons": [
                    self._build_no_data_reason(
                        source="alerts",
                        label="告警数据",
                        since=since,
                        until=day_end,
                        time_range=self.repo.available_alert_time_range() if hasattr(self.repo, "available_alert_time_range") else None,
                        region_name=city or "",
                    )
                ]
                if count == 0
                else [],
                "recovery_suggestions": self._build_recovery_suggestions(
                    question=question,
                    query_type="count",
                    no_data_reason=self._build_no_data_reason(
                        source="alerts",
                        label="告警数据",
                        since=since,
                        until=day_end,
                        time_range=self.repo.available_alert_time_range() if hasattr(self.repo, "available_alert_time_range") else None,
                        region_name=city or "",
                    ),
                    time_ranges=self._available_alert_ranges(),
                    region_name=city or "",
                )
                if count == 0
                else [],
            },
        )
