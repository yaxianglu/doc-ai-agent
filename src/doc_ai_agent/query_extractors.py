"""查询语句信息抽取工具集。

本模块负责把用户自然语言问题解析成结构化查询线索，例如：
- 时间范围（具体日期、相对时间、未来时间窗）
- 地区范围（市、县/区）
- 设备编码、TopN 数量等参数

这些函数只做“轻量规则抽取”，不直接决定最终业务意图，
后续由规划与路由层再综合上下文做决策。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from .agri_semantics import infer_region_scope

CITY_ALIASES = {
    "南京": "南京市",
    "无锡": "无锡市",
    "徐州": "徐州市",
    "常州": "常州市",
    "苏州": "苏州市",
    "南通": "南通市",
    "连云港": "连云港市",
    "淮安": "淮安市",
    "盐城": "盐城市",
    "扬州": "扬州市",
    "镇江": "镇江市",
    "泰州": "泰州市",
    "宿迁": "宿迁市",
}

CHINESE_NUMBER_MAP = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

INVALID_REGION_PHRASES = {
    "我问的是县",
    "我说的是县",
    "问的是县",
    "说的是县",
    "我问的是区",
    "我说的是区",
    "问的是区",
    "说的是区",
    "看县",
    "看区",
    "看市",
}


def is_invalid_region_candidate(candidate: str) -> bool:
    """判断一个地区候选词是否应被过滤。

    这里主要拦截“泛词、疑问词、口语修正词”等非真实地名，
    例如“哪些地区”“我问的是县”等，避免误识别为地区实体。
    """
    normalized = str(candidate or "").strip()
    if not normalized:
        return True
    if normalized in {"地区", "区域", "市区", "城区"}:
        return True
    if normalized.startswith("某"):
        return True
    if normalized.startswith("个"):
        return True
    if normalized in INVALID_REGION_PHRASES:
        return True
    if any(token in normalized for token in ["预警", "最多", "最高", "最严重", "最突出", "地方", "地区"]):
        return True
    if any(token in normalized for token in ["哪些", "哪个", "什么", "哪几个", "再细到", "下面", "范围内"]):
        return True
    if any(token in normalized for token in ["我问的是", "我说的是", "问的是", "说的是", "不是市", "不是县", "不是区"]):
        return True
    return False


def parse_number_token(token: str) -> int:
    """将阿拉伯数字或常见中文数字转成整数。"""
    value = str(token or "").strip()
    if value.isdigit():
        return int(value)
    return CHINESE_NUMBER_MAP.get(value, 1)


def extract_day_range(question: str) -> tuple[Optional[str], Optional[str]]:
    """抽取问题中的绝对日期范围。

    返回 `(since, until)`，其中 `until` 使用“次日零点”的右开区间表达，
    便于后续 SQL 使用 `>= since and < until`。
    """
    range_match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日到(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日", question)
    if range_match:
        start_year = int(range_match.group(1))
        start_month = int(range_match.group(2))
        start_day = int(range_match.group(3))
        end_year = int(range_match.group(4) or start_year)
        end_month = int(range_match.group(5))
        end_day = int(range_match.group(6))
        start = datetime(start_year, start_month, start_day)
        end = datetime(end_year, end_month, end_day) + timedelta(days=1)
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")

    match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", question)
    if not match:
        return None, None
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    start = datetime(year, month, day)
    end = start + timedelta(days=1)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def extract_city(question: str) -> Optional[str]:
    """优先按别名表抽取城市，其次回退到“XX市”通配规则。"""
    normalized = question or ""
    city_positions: list[tuple[int, str]] = []
    for alias, canonical in CITY_ALIASES.items():
        for match in re.finditer(re.escape(canonical), normalized):
            city_positions.append((match.start(), canonical))
        for match in re.finditer(rf"{re.escape(alias)}(?!市)", normalized):
            city_positions.append((match.start(), canonical))
    if city_positions:
        city_positions.sort(key=lambda item: item[0])
        return city_positions[-1][1]
    matches = re.finditer(r"([\u4e00-\u9fa5]{2,6}市)", normalized)
    filtered = [
        match.group(1)
        for match in matches
        if match.group(1) not in {"城市"}
        and not match.group(1).endswith("城市")
        and not is_invalid_region_candidate(match.group(1))
    ]
    if filtered:
        return filtered[-1]
    for alias, canonical in CITY_ALIASES.items():
        if re.search(rf"{alias}(?!市)", question):
            return canonical
    return None


def extract_county(question: str) -> Optional[str]:
    """抽取县/区名称，并过滤疑问词触发的伪匹配。"""
    match = re.search(r"(?<!哪些)(?<!哪个)(?<!什么)([\u4e00-\u9fa5]{1,12}(?:县|区))", question)
    if not match:
        return None
    county = match.group(1)
    if is_invalid_region_candidate(county):
        return None
    return county


def asks_for_county_scope(question: str) -> bool:
    """判断问题是否明确要求下钻到县/区粒度。"""
    return infer_region_scope(question) == "county"


def extract_device_code(question: str) -> Optional[str]:
    """抽取设备编码（例如 `SNS12345`）。"""
    match = re.search(r"(SNS\d+)", question)
    if match:
        return match.group(1)
    return None


def extract_top_n(question: str) -> Optional[int]:
    """抽取 TopN 参数（支持 `top 5`、`前五` 等表达）。"""
    lowered = str(question or "").lower()
    if match := re.search(r"top\s*(\d+)", lowered):
        return max(1, int(match.group(1)))

    match = re.search(r"前\s*(\d+|[一二两三四五六七八九十])", question)
    if not match:
        return None

    suffix = question[match.end() :]
    if re.match(r"\s*个?(?:天|周|星期|月|年)", suffix):
        return None
    return max(1, parse_number_token(match.group(1)))


def asks_for_multiple_ranked_results(question: str) -> bool:
    """判断是否在询问多个排行结果（而不是单一对象）。"""
    q = question or ""
    return any(token in q for token in ["哪些", "哪几个", "前列", "排行", "排名"]) or "top" in q.lower()


def default_top_n(question: str, query_type: str) -> Optional[int]:
    """为不同查询类型给出默认 TopN。

    设计原则：先尊重用户显式输入；未指定时再按业务类型兜底。
    """
    explicit_top_n = extract_top_n(question)
    if explicit_top_n is not None:
        return explicit_top_n
    if query_type == "active_devices":
        return 10
    if query_type in {"pest_top", "soil_top", "joint_risk"}:
        return 5 if asks_for_multiple_ranked_results(question) else 1
    if query_type == "top":
        return 5
    return None


def extract_relative_window(question: str) -> tuple[Optional[str], Optional[str], dict]:
    """抽取“近 X 天/周/月、今年以来”等相对历史窗口。"""
    now = datetime.now()
    if "今年以来" in question:
        return f"{now.year}-01-01 00:00:00", None, {"window_type": "year_since", "window_value": now.year}
    if re.search(r"(?:过去|最近|近|这)半年", question) or "半年内" in question:
        since = now - timedelta(days=30 * 6)
        return since.strftime("%Y-%m-%d 00:00:00"), None, {"window_type": "months", "window_value": 6}
    if match := re.search(r"(?:近|进|过去|最近)(\d+|[一二两三四五六七八九十])个?(?:星期|周)", question):
        weeks = max(1, parse_number_token(match.group(1)))
        since = now - timedelta(days=7 * weeks)
        return since.strftime("%Y-%m-%d 00:00:00"), None, {"window_type": "weeks", "window_value": weeks}
    if match := re.search(r"(?:近|进|过去|最近)(\d+|[一二两三四五六七八九十])个?月", question):
        months = max(1, parse_number_token(match.group(1)))
        since = now - timedelta(days=30 * months)
        return since.strftime("%Y-%m-%d 00:00:00"), None, {"window_type": "months", "window_value": months}
    if match := re.search(r"(?:近|进|过去|最近)(\d+|[一二两三四五六七八九十])天", question):
        days = max(1, parse_number_token(match.group(1)))
        since = now - timedelta(days=days)
        return since.strftime("%Y-%m-%d 00:00:00"), None, {"window_type": "days", "window_value": days}
    return None, None, {"window_type": "none", "window_value": None}


def extract_future_window(question: str) -> dict | None:
    """抽取未来预测窗口（未来 X 天/周/月）。"""
    if "下个月" in question or "下月" in question:
        return {"window_type": "months", "window_value": 1, "horizon_days": 30}
    if "未来半个月" in question:
        return {"window_type": "days", "window_value": 15, "horizon_days": 15}
    if "未来两周" in question:
        return {"window_type": "weeks", "window_value": 2, "horizon_days": 14}
    if any(token in question for token in ["未来会更糟", "会更糟吗", "会恶化吗", "会不会更糟", "会不会恶化", "会不会更严重", "会更严重吗"]):
        return {"window_type": "weeks", "window_value": 2, "horizon_days": 14}
    if match := re.search(r"未来(\d+|[一二两三四五六七八九十])个?(?:星期|周)", question):
        weeks = max(1, parse_number_token(match.group(1)))
        return {"window_type": "weeks", "window_value": weeks, "horizon_days": weeks * 7}
    if match := re.search(r"未来(\d+|[一二两三四五六七八九十])天", question):
        days = max(1, parse_number_token(match.group(1)))
        return {"window_type": "days", "window_value": days, "horizon_days": days}
    if match := re.search(r"未来(\d+|[一二两三四五六七八九十])个?月", question):
        months = max(1, parse_number_token(match.group(1)))
        return {"window_type": "months", "window_value": months, "horizon_days": months * 30}
    return None


def build_route(question: str, query_type: str) -> dict:
    """组装基础 route 字典，供上层规划器继续修正。

    本函数只负责“稳健兜底”：
    - 时间无命中时回退到全量时间窗
    - 地区粒度优先遵循县级信息
    """
    since, until = extract_day_range(question)
    forecast_window = extract_future_window(question)
    if since is None:
        rel_since, rel_until, window = extract_relative_window(question)
        since, until = rel_since, rel_until
    else:
        window = {"window_type": "day", "window_value": 1}
    if since is None:
        match = re.search(r"(20\d{2})年以?来", question)
        if match:
            since = f"{match.group(1)}-01-01 00:00:00"
            window = {"window_type": "year_since", "window_value": int(match.group(1))}
    if since is None:
        # 最终兜底为全量时间范围，保证后续执行层始终有稳定的 since。
        since = "1970-01-01 00:00:00"
        window = {"window_type": "all", "window_value": None}
    county = extract_county(question)
    region_level = "county" if county or asks_for_county_scope(question) else "city"
    return {
        "query_type": query_type,
        "since": since,
        "until": until,
        "city": extract_city(question),
        "county": county,
        "device_code": extract_device_code(question),
        "region_level": region_level,
        "window": window,
        "top_n": default_top_n(question, query_type),
        "forecast_window": forecast_window,
    }
