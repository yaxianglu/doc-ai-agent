from __future__ import annotations

import re


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def normalize_relative_window_typos(text: str) -> str:
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
    normalized = text
    for alias, canonical in city_aliases.items():
        normalized = re.sub(rf"{alias}(?!市)", canonical, normalized)
    return normalized


def normalize_follow_up_question(text: str) -> str:
    normalized = re.sub(r"[，。！？；、]+", "", text)
    return re.sub(r"\s+", " ", normalized).strip()


def is_greeting(text: str, greeting_patterns: set[str]) -> bool:
    stripped = normalize_follow_up_question(text).lower()
    if not stripped:
        return False
    if stripped in greeting_patterns:
        return True
    return bool(re.fullmatch(r"(你好吗|最近好吗|在吗)", stripped))


def is_invalid_region_candidate(candidate: str, invalid_region_phrases: set[str]) -> bool:
    normalized = normalize_spaces(candidate)
    if not normalized:
        return True
    if normalized in {"地区", "区域", "市区", "城区"}:
        return True
    if normalized.startswith("个"):
        return True
    if normalized in invalid_region_phrases:
        return True
    if any(token in normalized for token in ["预警", "最多", "最严重", "地方", "地区"]):
        return True
    if any(token in normalized for token in ["我问的是", "我说的是", "问的是", "说的是", "不是市", "不是县", "不是区"]):
        return True
    return False


def coalesce_region_name(primary: str, secondary: str | None, city_aliases: dict[str, str], invalid_region_phrases: set[str]) -> str:
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
    return "虫情" in text or "虫害" in text or text.strip() == "虫"


def contains_soil(text: str) -> bool:
    return "墒情" in text or text.strip() == "墒"


def domain_label(domain: str) -> str:
    if domain == "pest":
        return "虫情"
    if domain == "soil":
        return "墒情"
    return ""


def inject_domain_into_question(question: str, domain: str) -> str:
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
    stripped = text.strip()
    if is_greeting(stripped, greeting_patterns):
        return False
    if re.search(r"(SNS\d+|设备|预警时间|等级|最近一次|这条预警|哪个|多少|Top|TOP|20\d{2}年)", stripped):
        return False
    if len(stripped) <= 8:
        return True
    return stripped in {"未来两周呢", "未来两周", "给建议", "建议", "处置建议", "原因呢", "为什么呢", "怎么办", "怎么做"}


def should_reuse_context_region(text: str, greeting_patterns: set[str]) -> bool:
    stripped = text.strip()
    if is_greeting(stripped, greeting_patterns):
        return False
    if stripped in {"未来两周呢", "未来两周", "给建议", "建议", "处置建议", "原因呢", "为什么呢", "怎么办", "怎么做", "怎么处理"}:
        return True
    if len(stripped) <= 4:
        return True
    return any(token in stripped for token in ["那里", "那边", "这边", "这里", "这个地方", "这地方", "该地区", "该地", "那呢", "这呢"])


def is_domain_switch_follow_up(text: str) -> bool:
    stripped = normalize_follow_up_question(text)
    if not stripped or stripped in {"虫情", "虫害", "墒情", "低墒", "高墒"}:
        return False
    if not (contains_pest(stripped) or contains_soil(stripped)):
        return False
    return bool(re.search(r"(换成|改成|改看|切到|切换到|切换成|改为|换看)", stripped))


def is_window_only_follow_up(text: str, *, extract_past_window, city_aliases: dict[str, str], invalid_region_phrases: set[str]) -> bool:
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
