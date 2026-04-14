"""验收评估工具：对批量问答结果打分并生成对比报告。"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SUITE_BY_CATEGORY = {
    "边界能力": "ood",
    "原因解释": "explanation",
    "预测能力": "forecast",
    "多轮上下文": "context",
}


def load_question_bank(path: Path) -> list[dict]:
    """加载题库并规范化字段类型。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    normalized = []
    for item in payload:
        entry = {
            "index": int(item["index"]),
            "category": str(item["category"]),
            "question": str(item["question"]),
        }
        if isinstance(item.get("turns"), list):
            entry["turns"] = [str(turn) for turn in item["turns"] if str(turn).strip()]
        normalized.append(entry)
    return normalized


def _contains_any(text: str, tokens: list[str]) -> bool:
    """判断文本是否命中任意关键词。"""
    return any(token in text for token in tokens)


def _asks_county_scope(question: str) -> bool:
    """识别是否明确要求县/区县粒度。"""
    return _contains_any(question, ["县", "区县", "按县", "按区县", "最高的县", "哪些县", "哪个县"])


def _has_county_level_answer(answer: str) -> bool:
    """粗略判断回答里是否真的落到了县/区县粒度。"""
    return bool(_contains_any(answer, ["区县", "县"]) or ("区" in answer and "市" not in answer))


def _is_trend_question(question: str) -> bool:
    """识别趋势/增减/缓解类问题。"""
    return _contains_any(question, ["趋势", "走势", "上升", "下降", "增加", "减少", "缓解", "好转"])


def _has_trend_answer(answer: str) -> bool:
    """识别回答里是否给出了趋势判断。"""
    return _contains_any(answer, ["趋势", "上升", "下降", "平稳", "波动", "缓解", "增加", "减少"])


def _is_weak_forecast_without_caution(answer: str) -> bool:
    """识别样本极弱但仍然强预测的情况。"""
    weak_sample = _contains_any(answer, ["样本覆盖 0 个观测日", "样本覆盖 1 个观测日"])
    caution = _contains_any(answer, ["暂不做强预测", "保守预测", "回退预测", "证据强度weak", "证据较弱"])
    return weak_sample and not caution


def _is_placeholder_question(question: str) -> bool:
    """识别是否在问“某设备/某县”这类占位问题。"""
    return _contains_any(question, ["某设备", "某县", "这个县", "该县", "这个地区", "该地区", "这个区域", "该区域"])


def _is_advice_or_explanation_question(question: str) -> bool:
    """识别是否属于建议或原因解释类题目。"""
    return _contains_any(question, ["建议", "怎么办", "怎么做", "怎么处理", "该咋办", "巡查", "行动建议", "为什么", "原因"])


def _is_domain_ambiguous_question(question: str) -> bool:
    """识别是否缺少虫情/墒情领域限定。"""
    return "最严重的是哪里" in question and not _contains_any(question, ["虫情", "墒情", "预警", "设备"])


def _is_boundary_question(item: dict, question: str) -> bool:
    """识别新增的边界能力题目。"""
    category = str(item.get("category") or "")
    return category == "边界能力" or _contains_any(question, ["天气", "下雨", "气温", "天气预报", "台风", "新闻", "高铁票", "火车票", "你是谁"])


def _is_identity_boundary_question(question: str) -> bool:
    """识别身份说明类边界题。"""
    stripped = question.strip().rstrip("？?")
    return stripped in {"你是谁", "你是干什么的", "你能做什么", "你可以做什么"}


def _suite_name_for(item: dict) -> str:
    """推断题目所属的专项评测子集。"""
    explicit_suite = str(item.get("suite") or "").strip()
    if explicit_suite:
        return explicit_suite

    category = str(item.get("category") or "")
    if category in SUITE_BY_CATEGORY:
        return SUITE_BY_CATEGORY[category]

    question = str(item.get("question") or "")
    if _is_boundary_question(item, question):
        return "ood"
    if _contains_any(question, ["为什么", "原因", "从数据看"]):
        return "explanation"
    if "未来" in question or "下周" in question:
        return "forecast"
    if int(item.get("index") or 0) in {46, 47, 48, 49, 50}:
        return "context"
    return ""


def _score_boundary_response(question: str, answer: str, score: float, failed: list[str]) -> tuple[float, list[str]]:
    """对越界/边界能力问题做专项评分。"""
    if _is_identity_boundary_question(question):
        if _contains_any(answer, ["我是", "AI农情工作台", "助手"]):
            return score, failed
        score -= 3.0
        failed.append("identity_answer_unhelpful")
        return score, failed

    boundary_ok = _contains_any(answer, ["我目前", "我主要", "暂不", "不能", "无法", "不直接提供", "支持农业", "农情"])
    helpful_redirect = _contains_any(answer, ["虫情", "墒情", "预警", "如果你要看农情", "可以继续帮你查"])
    agri_hijack = _contains_any(answer, ["异常最多", "风险最高", "观测日", "地区为：", "Top", "TOP", "从202", "从1970"]) and _contains_any(
        answer,
        ["虫情", "墒情", "预警", "报警", "设备", "风险"],
    )

    if agri_hijack and not boundary_ok:
        score -= 8.0
        failed.append("boundary_hijacked_by_agri")
    elif not boundary_ok:
        score -= 3.0
        failed.append("boundary_missing_scope_statement")

    if boundary_ok and not helpful_redirect:
        score -= 1.0
        failed.append("boundary_missing_redirect")

    return score, failed


def _score_item(item: dict) -> dict:
    """按规则评估单条问答结果并输出分数与失败项。"""
    if isinstance(item.get("turn_results"), list):
        turns = list(item.get("turn_results") or [])
        scored_turns = [
            _score_item(
                {
                    "index": int(item["index"]),
                    "category": "多轮上下文",
                    "suite": "context",
                    "question": str(turn.get("question") or ""),
                    "ok": bool(turn.get("ok", True)),
                    "mode": str(turn.get("mode") or ""),
                    "seconds": float(turn.get("seconds") or 0),
                    "answer": str(turn.get("answer") or ""),
                }
            )
            for turn in turns
        ]
        average_score = round(sum(float(turn["score"]) for turn in scored_turns) / len(scored_turns), 1) if scored_turns else 0.0
        checks_failed: list[str] = []
        for turn in scored_turns:
            for failed in list(turn.get("checks_failed") or []):
                if failed not in checks_failed:
                    checks_failed.append(failed)
        return {
            "index": int(item["index"]),
            "category": str(item.get("category") or "多轮上下文"),
            "suite": "context",
            "question": str(item.get("question") or ""),
            "mode": str(item.get("mode") or ""),
            "score": average_score,
            "checks_failed": checks_failed,
            "seconds": float(item.get("seconds") or 0),
            "answer": str(item.get("answer") or ""),
            "turn_scores": scored_turns,
        }

    question = str(item.get("question") or "")
    answer = str(item.get("answer") or "")
    mode = str(item.get("mode") or "")
    ok = bool(item.get("ok"))
    seconds = float(item.get("seconds") or 0)
    score = 10.0
    failed: list[str] = []

    if not ok:
        score = 0.0
        failed.append("runtime_error")
    if ok and not answer.strip():
        score = min(score, 1.0)
        failed.append("empty_answer")
    if seconds > 30:
        score -= 1.0
        failed.append("slow_response")

    data_cues = ["多少", "哪些", "哪个", "哪里", "最多", "最高", "趋势", "增加", "减少", "上升", "下降", "未来", "最近", "过去"]
    if (
        _contains_any(question, data_cues)
        and mode == "advice"
        and not _is_advice_or_explanation_question(question)
        and not _is_placeholder_question(question)
        and not _is_domain_ambiguous_question(question)
        and not _is_boundary_question(item, question)
    ):
        score -= 3.0
        failed.append("misrouted_to_advice")

    if _is_placeholder_question(question) and "请补充具体对象" in answer:
        return {
            "index": int(item["index"]),
            "category": str(item.get("category") or ""),
            "question": question,
            "mode": mode,
            "score": max(0.0, round(score, 1)),
            "checks_failed": [entry for entry in failed if entry != "misrouted_to_advice"],
            "seconds": seconds,
            "answer": answer,
        }

    if _is_domain_ambiguous_question(question) and _contains_any(answer, ["虫情还是墒情", "虫情还是墒情？", "你想看虫情还是墒情"]):
        return {
            "index": int(item["index"]),
            "category": str(item.get("category") or ""),
            "question": question,
            "mode": mode,
            "score": max(0.0, round(score, 1)),
            "checks_failed": [entry for entry in failed if entry != "misrouted_to_advice"],
            "seconds": seconds,
            "answer": answer,
        }

    if _is_boundary_question(item, question):
        score, failed = _score_boundary_response(question, answer, score, failed)

    if _contains_any(question, ["预警", "报警"]) and "墒情异常最多" in answer and "预警" not in answer:
        score -= 3.5
        failed.append("alert_domain_mismatch")

    if _contains_any(question, ["偏低", "低墒", "缺水"]) and "高墒" in answer and "低墒" not in answer:
        score -= 2.0
        failed.append("soil_direction_mismatch")

    if _asks_county_scope(question) and not _has_county_level_answer(answer):
        score -= 3.0
        failed.append("county_scope_mismatch")

    if _is_trend_question(question) and not _has_trend_answer(answer):
        score -= 3.0
        failed.append("trend_missing_direction")

    if "未来" in question:
        if "置信度" not in answer:
            score -= 1.5
            failed.append("forecast_missing_confidence")
        if "依据：" not in answer:
            score -= 1.5
            failed.append("forecast_missing_evidence")
        if "样本覆盖" not in answer:
            score -= 1.0
            failed.append("forecast_missing_sample_coverage")
        if _is_weak_forecast_without_caution(answer):
            score -= 3.0
            failed.append("forecast_overclaims_weak_evidence")

    if _contains_any(question, ["为什么", "原因"]) and "原因" not in answer:
        score -= 2.0
        failed.append("explanation_missing_reason_section")
    if _contains_any(question, ["为什么", "原因", "从数据看"]) and "依据：" not in answer and "从数据看" not in answer:
        score -= 2.0
        failed.append("explanation_missing_grounding")
    if _contains_any(question, ["为什么", "原因"]) and "待核查" not in answer:
        score -= 0.8
        failed.append("explanation_missing_followup_checks")

    if "1970-01-01" in answer:
        score -= 3.5
        failed.append("internal_default_time_exposed")

    score = max(0.0, round(score, 1))
    return {
        "index": int(item["index"]),
        "category": str(item.get("category") or ""),
        "suite": _suite_name_for(item),
        "question": question,
        "mode": mode,
        "score": score,
        "checks_failed": failed,
        "seconds": seconds,
        "answer": answer,
    }


def score_run(raw_items: list[dict]) -> dict:
    """对整批运行结果打分并汇总分类统计。"""
    items = [_score_item(item) for item in raw_items]
    by_category: dict[str, list[float]] = defaultdict(list)
    by_suite: dict[str, list[float]] = defaultdict(list)
    low_score_items_by_suite: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_category[item["category"]].append(float(item["score"]))
        suite = str(item.get("suite") or "")
        if suite:
            by_suite[suite].append(float(item["score"]))
            if float(item["score"]) < 7.0:
                low_score_items_by_suite[suite].append(
                    {
                        "index": int(item["index"]),
                        "question": str(item["question"]),
                        "score": float(item["score"]),
                        "checks_failed": list(item.get("checks_failed") or []),
                    }
                )
    average = round(sum(float(item["score"]) for item in items) / len(items), 2) if items else 0.0
    category_scores = {
        category: round(sum(values) / len(values), 2)
        for category, values in sorted(by_category.items())
    }
    suite_scores = {
        suite: round(sum(values) / len(values), 2)
        for suite, values in sorted(by_suite.items())
    }
    return {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "count": len(items),
            "average_score": average,
            "category_scores": category_scores,
            "suite_scores": suite_scores,
            "low_score_count": sum(1 for item in items if float(item["score"]) < 7.0),
            "low_score_items_by_suite": {
                suite: sorted(values, key=lambda item: (float(item["score"]), int(item["index"])))
                for suite, values in sorted(low_score_items_by_suite.items())
            },
        },
        "items": items,
    }


def compare_scored_runs(*, current: dict, baseline: dict) -> dict:
    """比较当前与基线评分，输出提升与回退条目。"""
    baseline_by_index = {int(item["index"]): item for item in list(baseline.get("items") or [])}
    current_by_index = {int(item["index"]): item for item in list(current.get("items") or [])}
    improved: list[dict] = []
    regressed: list[dict] = []

    for index, current_item in sorted(current_by_index.items()):
        baseline_item = baseline_by_index.get(index)
        if not baseline_item:
            continue
        delta = round(float(current_item.get("score") or 0) - float(baseline_item.get("score") or 0), 1)
        payload = {
            "index": index,
            "question": current_item.get("question") or baseline_item.get("question") or "",
            "baseline_score": float(baseline_item.get("score") or 0),
            "current_score": float(current_item.get("score") or 0),
            "delta": delta,
        }
        if delta > 0:
            improved.append(payload)
        elif delta < 0:
            regressed.append(payload)

    average_delta = round(
        float(current.get("summary", {}).get("average_score") or 0) - float(baseline.get("summary", {}).get("average_score") or 0),
        2,
    )
    return {
        "summary": {
            "average_delta": average_delta,
            "improved_count": len(improved),
            "regressed_count": len(regressed),
        },
        "improved": improved,
        "regressed": regressed,
    }


def render_score_report(scored: dict) -> str:
    """将评分结果渲染为可读 Markdown 报告。"""
    lines = [
        "# Strict Acceptance Eval Report",
        "",
        f"- Count: {scored['summary']['count']}",
        f"- Average Score: {scored['summary']['average_score']}",
        f"- Low Score Count (<7): {scored['summary']['low_score_count']}",
        "",
        "## Category Scores",
        "",
    ]
    for category, score in scored["summary"]["category_scores"].items():
        lines.append(f"- {category}: {score}")
    suite_scores = scored["summary"].get("suite_scores") or {}
    if suite_scores:
        lines.extend(["", "## Suite Scores", ""])
        for suite, score in suite_scores.items():
            lines.append(f"- {suite}: {score}")
    low_score_items_by_suite = scored["summary"].get("low_score_items_by_suite") or {}
    if low_score_items_by_suite:
        lines.extend(["", "## Low Score Items By Suite", ""])
        for suite, items in low_score_items_by_suite.items():
            lines.append(f"- {suite}:")
            for item in items:
                lines.append(f"  - {item['index']:02d} `{item['score']}` {item['question']}")
    lines.extend(["", "## Items", ""])
    for item in scored["items"]:
        lines.append(f"- {item['index']:02d} `{item['score']}` {item['question']}")
        if item["checks_failed"]:
            lines.append(f"  - checks_failed: {', '.join(item['checks_failed'])}")
    return "\n".join(lines) + "\n"


def render_comparison_report(comparison: dict) -> str:
    """把两次评分结果的差异渲染成 Markdown 对比报告。"""
    lines = [
        "# Strict Acceptance Eval Comparison",
        "",
        f"- Average Delta: {comparison['summary']['average_delta']}",
        f"- Improved Count: {comparison['summary']['improved_count']}",
        f"- Regressed Count: {comparison['summary']['regressed_count']}",
        "",
        "## Improved",
        "",
    ]
    if comparison["improved"]:
        for item in comparison["improved"]:
            lines.append(f"- {item['index']:02d} `{item['baseline_score']} -> {item['current_score']}` {item['question']}")
    else:
        lines.append("- none")
    lines.extend(["", "## Regressed", ""])
    if comparison["regressed"]:
        for item in comparison["regressed"]:
            lines.append(f"- {item['index']:02d} `{item['baseline_score']} -> {item['current_score']}` {item['question']}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"
