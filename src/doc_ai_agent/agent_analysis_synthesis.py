from __future__ import annotations


def _reasoning_metric_key(domain: str, series: list[dict]) -> tuple[str, str, str]:
    if domain == "soil" or any("avg_anomaly_score" in item for item in series):
        return "avg_anomaly_score", "异常值", "墒情"
    return "severity_score", "严重度", "虫情"


def _is_time_series(series: list[dict]) -> bool:
    return bool(series) and isinstance(series[0], dict) and any(key in series[0] for key in ["date", "bucket"])


def _is_ranking_rows(series: list[dict]) -> bool:
    return bool(series) and isinstance(series[0], dict) and "region_name" in series[0] and not _is_time_series(series)


def _reasoning_point_date(point: dict) -> str:
    return str(point.get("date") or point.get("bucket") or "")


def _reasoning_format_metric(value: float) -> str:
    if float(value).is_integer():
        return f"{value:.0f}"
    return f"{value:.1f}"


def _comparison_trend(series: list[dict], key: str) -> str:
    if len(series) < 2:
        return "样本不足"
    first = float(series[0].get(key) or 0)
    last = float(series[-1].get(key) or 0)
    if last > first * 1.15:
        return "整体上升"
    if last < first * 0.85:
        return "整体下降"
    return "整体平稳"


def _comparison_average(series: list[dict], key: str) -> float:
    if not series:
        return 0.0
    return sum(float(item.get(key) or 0) for item in series) / len(series)


def _reasoning_series_summary(domain: str, series: list[dict]) -> dict:
    metric_key, metric_label, domain_label = _reasoning_metric_key(domain, series)
    if not series:
        return {
            "domain_label": domain_label,
            "metric_label": metric_label,
            "trend": "样本不足",
            "average": 0.0,
            "peak_value": 0.0,
            "peak_date": "",
            "latest_value": 0.0,
            "latest_date": "",
            "active_days": 0,
            "sample_days": 0,
        }

    peak_point = max(series, key=lambda item: float(item.get(metric_key) or 0))
    latest_point = series[-1]
    active_days = sum(1 for item in series if float(item.get(metric_key) or 0) > 0)
    return {
        "domain_label": domain_label,
        "metric_label": metric_label,
        "trend": _comparison_trend(series, metric_key),
        "average": _comparison_average(series, metric_key),
        "peak_value": float(peak_point.get(metric_key) or 0),
        "peak_date": _reasoning_point_date(peak_point),
        "latest_value": float(latest_point.get(metric_key) or 0),
        "latest_date": _reasoning_point_date(latest_point),
        "active_days": active_days,
        "sample_days": len(series),
    }


def build_data_grounded_explanation(
    *,
    plan_context: dict,
    query_result: dict,
    forecast_result: dict,
    knowledge: list[dict],
    default_region_name: str = "",
) -> str:
    domain = str(plan_context.get("domain") or "")
    region_name = str(plan_context.get("region_name") or default_region_name or "当前地区")
    series = list(query_result.get("data") or [])
    if not series or not isinstance(series[0], dict):
        return ""
    if _is_ranking_rows(series):
        top = series[0]
        metric_key, metric_label, domain_label = _reasoning_metric_key(domain, series)
        score = _reasoning_format_metric(float(top.get(metric_key) or top.get("anomaly_score") or 0))
        record_count = int(top.get("record_count") or top.get("abnormal_count") or 0)
        top_region = str(top.get("region_name") or region_name or "当前地区")
        return (
            f"从当前排行汇总看，{top_region}{domain_label}排在最前，{metric_label}{score}，相关记录{record_count}条。"
            f"这说明它当前更突出，但这类汇总排行本身还不足以单独判断成因；如果要继续解释原因，最好结合{top_region}的逐日趋势和现场记录再判断。"
        )

    summary = _reasoning_series_summary(domain, series)
    average = float(summary["average"] or 0)
    peak_value = float(summary["peak_value"] or 0)
    latest_value = float(summary["latest_value"] or 0)
    trend = str(summary["trend"] or "整体平稳")
    metric_label = str(summary["metric_label"] or "指标")

    sentences = [
        f"从数据看，{region_name}{summary['domain_label']}在这个时间窗内{trend}，高值主要出现在{summary['peak_date'] or '窗口内高点'}，峰值{_reasoning_format_metric(peak_value)}。"
    ]
    if latest_value <= average * 0.7 and peak_value > 0:
        sentences.append(
            f"最近值{_reasoning_format_metric(latest_value)}，明显低于窗口均值{_reasoning_format_metric(average)}，说明当前已经从前期高点回落，但前段时间确实存在一轮明显抬升。"
        )
    elif latest_value >= average * 1.2 and latest_value > 0:
        sentences.append(
            f"最近值{_reasoning_format_metric(latest_value)}，仍高于窗口均值{_reasoning_format_metric(average)}，说明当前压力还没有完全消退。"
        )
    else:
        sentences.append(
            f"最近值{_reasoning_format_metric(latest_value)}，与窗口均值{_reasoning_format_metric(average)}接近，说明当前处于高点后的回落或平稳阶段。"
        )

    if summary["active_days"] >= max(3, summary["sample_days"] // 3):
        sentences.append(
            f"窗口内共有{summary['active_days']}个观测日{metric_label}大于0，不是单点异常，更像是一段持续性的高值过程。"
        )
    else:
        sentences.append(
            f"窗口内只有{summary['active_days']}个观测日{metric_label}大于0，更像是局部时段冲高。"
        )

    forecast = dict(forecast_result.get("forecast") or {})
    if forecast:
        horizon_days = int(forecast.get("horizon_days") or 14)
        horizon_phrase = "未来两周" if horizon_days == 14 else f"未来{horizon_days}天"
        risk_level = str(forecast.get("risk_level") or "中")
        confidence = float(forecast.get("confidence") or 0)
        factor_list = [str(item) for item in list(forecast.get("top_factors") or []) if str(item)]
        factor_text = "、".join(factor_list[:2]) if factor_list else "历史样本与最近波动"
        sentences.append(
            f"按{horizon_phrase}预测，风险仍为{risk_level}，置信度{confidence:.2f}；依据主要是{factor_text}，所以后续应优先复核前期高值点位，而不是只看单日波动。"
        )

    if knowledge:
        first_title = str(knowledge[0].get("title") or "")
        if first_title:
            sentences.append(f"结合{first_title}的经验，这类“先冲高、后回落”或持续高值形态，通常都需要复核监测点位、阈值判断和田间处置时机。")
    sentences.append("待核查项包括监测点位是否稳定、阈值口径是否一致，以及田间处置是否与异常抬升时段对应。")

    return "".join(sentences)


def build_data_grounded_advice(
    *,
    plan_context: dict,
    query_result: dict,
    forecast_result: dict,
    default_region_name: str = "",
) -> str:
    domain = str(plan_context.get("domain") or "")
    region_name = str(plan_context.get("region_name") or default_region_name or "当前地区")
    series = list(query_result.get("data") or [])
    if not series or not isinstance(series[0], dict):
        return ""
    if _is_ranking_rows(series):
        top = series[0]
        metric_key, metric_label, domain_label = _reasoning_metric_key(domain, series)
        score = _reasoning_format_metric(float(top.get(metric_key) or top.get("anomaly_score") or 0))
        record_count = int(top.get("record_count") or top.get("abnormal_count") or 0)
        top_region = str(top.get("region_name") or region_name or "当前地区")
        if domain == "pest":
            return (
                f"{top_region}当前在排行中最突出，{metric_label}{score}、记录{record_count}条，"
                "建议先围绕该县复核高值点位和监测设备，再对连续异常地块做分区处置。"
            )
        return (
            f"{top_region}当前在排行中最突出，{metric_label}{score}、异常记录{record_count}条，"
            "建议先区分低墒和高墒地块，低墒优先补灌，高墒优先排水，并继续跟踪复测。"
        )

    summary = _reasoning_series_summary(domain, series)
    average = float(summary["average"] or 0)
    latest_value = float(summary["latest_value"] or 0)
    forecast = dict(forecast_result.get("forecast") or {})
    risk_level = str(forecast.get("risk_level") or "")
    confidence = float(forecast.get("confidence") or 0)
    rising_pressure = latest_value >= average * 1.2 if average > 0 else latest_value > 0
    clearly_receded = latest_value <= average * 0.7 if average > 0 else latest_value == 0

    if domain == "pest":
        if risk_level == "高" or rising_pressure:
            return (
                f"{region_name}当前仍处在偏高压力区，先复核高值点位和诱捕监测，再对连续高值地块按阈值分区处置；"
                "本轮不要全域铺开，优先盯住峰值附近区域，处置后 24-48 小时复查虫口变化。"
            )
        if confidence and confidence < 0.5:
            return (
                f"{region_name}当前预测把握度一般，建议先保留高频监测和点位复核，"
                "不要仅凭一次预测结果直接扩大处置范围，先看 2-3 天连续数据再决定是否升级动作。"
            )
        if clearly_receded:
            return (
                f"{region_name}当前已经较峰值阶段明显回落，建议先以复核高值点位和维持监测为主，"
                "暂不直接扩大处置范围；如果后续连续几天再抬升，再升级到分区防控。"
            )
        return (
            f"{region_name}当前处于中间压力阶段，建议先复核高值点位，再对持续偏高地块做分区处置，"
            "同时保留连续监测，避免因为短时回落就过早撤掉巡查。"
        )

    if risk_level == "高" or rising_pressure:
        return (
            f"{region_name}当前异常压力偏高，建议先分区复核低墒/高墒地块，再优先处理持续异常区域；"
            "低墒先补灌，高墒先排水，处置后继续看 3-5 天监测是否回落。"
        )
    if confidence and confidence < 0.5:
        return (
            f"{region_name}当前预测把握度一般，建议先维持分区抽样复核，不要一次性放大灌排动作；"
            "先确认低墒或高墒是否持续，再决定是否升级到集中处置。"
        )
    if clearly_receded:
        return (
            f"{region_name}当前已经较前期高点回落，建议先维持监测和抽样复核，不要一次性加大灌排动作；"
            "重点盯住此前异常最集中的地块，看是否再次抬头。"
        )
    return (
        f"{region_name}当前仍有一定异常压力，建议先复核异常分布，再按地块类型做补灌或排水，"
        "并持续复查，避免处置动作和实时墒情脱节。"
    )
