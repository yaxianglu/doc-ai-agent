"""请求上下文补全与纠错逻辑。

主要解决多轮对话中的“省略表达”问题，例如：
- “未来两周呢”“给建议”这类短句需要继承上一轮领域/地区；
- “换成墒情”这类句子需要识别为切换，不应盲目继承；
- 口语错别字（如“进两周”）要先规范化再解析。
"""

from __future__ import annotations

import re


def normalize_spaces(text: str) -> str:
    """压缩多余空白并去掉首尾空格。"""
    return re.sub(r"\s+", " ", str(text or "").strip())


def normalize_relative_window_typos(text: str) -> str:
    """修正常见口语输入：把“进X周/月/天”规范为“近X周/月/天”。"""
    normalized = str(text or "")
    normalized = re.sub(
        r"(?<=[\u4e00-\u9fa5])进(?=(\d+|[一二两三四五六七八九十])个?(?:月|星期|周))",
        "近",
        normalized,
    )
    normalized = re.sub(
        r"(?<=[\u4e00-\u9fa5])进(?=(\d+|[一二两三四五六七八九十])天)",
        "近",
        normalized,
    )
    return normalized


def normalize_city_mentions(text: str, city_aliases: dict[str, str]) -> str:
    """把城市别名统一成标准城市名（如“南京”->“南京市”）。"""
    normalized = text
    for alias, canonical in city_aliases.items():
        normalized = re.sub(rf"{alias}(?!市)", canonical, normalized)
    return normalized


def normalize_follow_up_question(text: str) -> str:
    """追问场景下的轻量标准化：去标点、压空格。"""
    normalized = re.sub(r"[，。！？；、]+", "", text)
    return re.sub(r"\s+", " ", normalized).strip()


def is_greeting(text: str, greeting_patterns: set[str]) -> bool:
    """判断是否是问候语，避免被误判为业务追问。"""
    stripped = normalize_follow_up_question(text).lower()
    if not stripped:
        return False
    if stripped in greeting_patterns:
        return True
    return bool(re.fullmatch(r"(你好吗|最近好吗|在吗)", stripped))


def is_invalid_region_candidate(candidate: str, invalid_region_phrases: set[str]) -> bool:
    """过滤明显不是有效地区名的候选词。"""
    normalized = normalize_spaces(candidate)
    if not normalized:
        return True
    if normalized in {"地区", "区域", "市区", "城区"}:
        return True
    if normalized.startswith("某"):
        return True
    if normalized.startswith("个"):
        return True
    if normalized in invalid_region_phrases:
        return True
    if any(token in normalized for token in ["预警", "最多", "最高", "最严重", "最突出", "地方", "地区"]):
        return True
    if any(token in normalized for token in ["哪些", "哪个", "什么", "哪几个", "再细到", "下面", "范围内"]):
        return True
    if any(token in normalized for token in ["我问的是", "我说的是", "问的是", "说的是", "不是市", "不是县", "不是区"]):
        return True
    return False


def coalesce_region_name(primary: str, secondary: str | None, city_aliases: dict[str, str], invalid_region_phrases: set[str]) -> str:
    """从多个候选里挑选一个有效地区名。"""
    for candidate in [primary, secondary or ""]:
        if not candidate:
            continue
        if is_invalid_region_candidate(candidate, invalid_region_phrases):
            continue
        if candidate in city_aliases.values():
            return candidate
        if re.fullmatch(r"[\u4e00-\u9fa5]{2,12}(?:市|县|区)", candidate):
            return candidate
    return ""


def contains_pest(text: str) -> bool:
    """判断文本是否显式提到虫情领域。"""
    return "虫情" in text or "虫害" in text or text.strip() == "虫"


def contains_soil(text: str) -> bool:
    """判断文本是否显式提到墒情领域。"""
    return "墒情" in text or text.strip() == "墒"


def domain_label(domain: str) -> str:
    """把内部领域枚举转换成中文标签。"""
    if domain == "pest":
        return "虫情"
    if domain == "soil":
        return "墒情"
    return ""


def inject_domain_into_question(question: str, domain: str) -> str:
    """把继承得到的领域词补回用户问题，便于后续统一解析。"""
    label = domain_label(domain)
    if not label:
        return normalize_spaces(question)
    base = normalize_spaces(question)
    if label in base:
        return base
    for token in ["受灾", "灾害情况", "灾害"]:
        if token in base:
            return normalize_follow_up_question(base.replace(token, label))
    if "最严重的地方" in base:
        return normalize_follow_up_question(base.replace("最严重的地方", f"{label}最严重的地方"))
    if "最严重" in base:
        return normalize_follow_up_question(base.replace("最严重", f"{label}最严重"))
    return normalize_follow_up_question(f"{base} {label}")


def extract_region(text: str, city_aliases: dict[str, str], invalid_region_phrases: set[str]) -> str | None:
    """从文本中抽取地区：城市优先，其次县区，再次市级。"""
    normalized = normalize_city_mentions(text, city_aliases)
    city_positions: list[tuple[int, str]] = []
    for canonical in city_aliases.values():
        for match in re.finditer(re.escape(canonical), normalized):
            city_positions.append((match.start(), canonical))
    if city_positions:
        city_positions.sort(key=lambda item: item[0])
        return city_positions[-1][1]
    county_match = re.search(r"(?<!哪些)(?<!哪个)(?<!什么)([\u4e00-\u9fa5]{1,12}(?:县|区))", normalized)
    if county_match:
        county = county_match.group(1)
        if not is_invalid_region_candidate(county, invalid_region_phrases):
            return county
    city = re.findall(r"([\u4e00-\u9fa5]{2,6}市)", normalized)
    for item in reversed(city):
        if item not in {"城市"} and not item.endswith("城市") and not is_invalid_region_candidate(item, invalid_region_phrases):
            return item
    return None


def is_contextual_follow_up(text: str, greeting_patterns: set[str]) -> bool:
    """判断是否属于依赖上下文的短追问。"""
    stripped = text.strip()
    if is_greeting(stripped, greeting_patterns):
        return False
    if re.search(r"(SNS\d+|设备|预警时间|等级|最近一次|这条预警|哪个|多少|Top|TOP|20\d{2}年)", stripped):
        return False
    if len(stripped) <= 8:
        return True
    return stripped in {"未来两周呢", "未来两周", "给建议", "建议", "处置建议", "原因呢", "为什么呢", "怎么办", "怎么做"}


def should_reuse_context_region(text: str, greeting_patterns: set[str]) -> bool:
    """判断短追问是否应复用上一轮地区。"""
    stripped = text.strip()
    if is_greeting(stripped, greeting_patterns):
        return False
    if stripped in {"未来两周呢", "未来两周", "给建议", "建议", "处置建议", "原因呢", "为什么呢", "怎么办", "怎么做", "怎么处理"}:
        return True
    if len(stripped) <= 4:
        return True
    return any(token in stripped for token in ["那里", "那边", "这边", "这里", "这个地方", "这地方", "该地区", "该地", "那呢", "这呢"])


def is_domain_switch_follow_up(text: str) -> bool:
    """判断是否在“切换领域”（如换成墒情）。"""
    stripped = normalize_follow_up_question(text)
    if not stripped or stripped in {"虫情", "虫害", "墒情", "低墒", "高墒"}:
        return False
    if not (contains_pest(stripped) or contains_soil(stripped)):
        return False
    return bool(re.search(r"(换成|改成|改看|切到|切换到|切换成|改为|换看)", stripped))


def is_window_only_follow_up(text: str, *, extract_past_window, city_aliases: dict[str, str], invalid_region_phrases: set[str]) -> bool:
    """判断是否只是补充时间窗，不包含领域或地区信息。"""
    stripped = normalize_follow_up_question(text)
    if not stripped:
        return False
    if contains_pest(stripped) or contains_soil(stripped) or extract_region(stripped, city_aliases, invalid_region_phrases):
        return False
    return extract_past_window(stripped).get("window_type") != "all"


def resolve_with_context(
    text: str,
    context: dict | None,
    *,
    city_aliases: dict[str, str],
    invalid_region_phrases: set[str],
    greeting_patterns: set[str],
    extract_past_window,
) -> tuple[str, list[str]]:
    """根据上下文重写当前问题，并返回触发的解析动作。

    返回值第二项是动作标签列表，便于上层记录“这次是如何被补全的”。
    """
    context = dict(context or {})
    cleaned = normalize_city_mentions(normalize_relative_window_typos(normalize_spaces(text)), city_aliases)
    if not cleaned:
        return cleaned, []
    if is_greeting(cleaned, greeting_patterns):
        return cleaned, []

    pending_question = normalize_spaces(str(context.get("pending_user_question") or ""))
    pending_clarification = str(context.get("pending_clarification") or "")
    if pending_question and pending_clarification == "agri_domain":
        if contains_pest(cleaned):
            return inject_domain_into_question(pending_question, "pest"), ["resolved_agri_domain_from_pending_question"]
        if contains_soil(cleaned):
            return inject_domain_into_question(pending_question, "soil"), ["resolved_agri_domain_from_pending_question"]

    domain = str(context.get("domain") or "")
    region_name = normalize_spaces(str(context.get("region_name") or ""))
    if (domain or region_name) and is_contextual_follow_up(cleaned, greeting_patterns):
        if is_domain_switch_follow_up(cleaned) or is_window_only_follow_up(
            cleaned,
            extract_past_window=extract_past_window,
            city_aliases=city_aliases,
            invalid_region_phrases=invalid_region_phrases,
        ):
            # 显式切换领域或仅补时间窗时，保留用户原句，不强行拼接旧上下文。
            return cleaned, []
        current_region = extract_region(cleaned, city_aliases, invalid_region_phrases)
        reuse_region = not current_region and should_reuse_context_region(cleaned, greeting_patterns)
        prefix_region = region_name if reuse_region else ""
        parts = [part for part in [prefix_region, domain_label(domain), cleaned] if part]
        resolution = ["expanded_short_follow_up_from_memory"]
        if reuse_region:
            resolution.append("reused_region_from_memory")
        return normalize_spaces(" ".join(parts)), resolution

    return cleaned, []
