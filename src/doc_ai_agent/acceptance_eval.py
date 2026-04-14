from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def load_question_bank(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        {
            "index": int(item["index"]),
            "category": str(item["category"]),
            "question": str(item["question"]),
        }
        for item in payload
    ]


def _contains_any(text: str, tokens: list[str]) -> bool:
    return any(token in text for token in tokens)


def _is_placeholder_question(question: str) -> bool:
    return _contains_any(question, ["某设备", "某县", "这个县", "该县", "这个地区", "该地区", "这个区域", "该区域"])


def _is_advice_or_explanation_question(question: str) -> bool:
    return _contains_any(question, ["建议", "怎么办", "怎么做", "怎么处理", "该咋办", "巡查", "行动建议", "为什么", "原因"])


def _is_domain_ambiguous_question(question: str) -> bool:
    return "最严重的是哪里" in question and not _contains_any(question, ["虫情", "墒情", "预警", "设备"])


def _score_item(item: dict) -> dict:
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
    ):
        score -= 3.0
        failed.append("misrouted_to_advice")

    if _is_placeholder_question(question) and "请补充具体对象" in answer:
        return {
            "index": int(item["index"]),
            "category": str(item.get("category") or ""),
            "question": question,
            "mode": mode,
            "score": max(score, 8.5),
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
            "score": max(score, 8.5),
            "checks_failed": [entry for entry in failed if entry != "misrouted_to_advice"],
            "seconds": seconds,
            "answer": answer,
        }

    if _contains_any(question, ["预警", "报警"]) and "墒情异常最多" in answer and "预警" not in answer:
        score -= 3.5
        failed.append("alert_domain_mismatch")

    if _contains_any(question, ["偏低", "低墒", "缺水"]) and "高墒" in answer and "低墒" not in answer:
        score -= 2.0
        failed.append("soil_direction_mismatch")

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

    if _contains_any(question, ["为什么", "原因"]) and "原因" not in answer:
        score -= 2.0
        failed.append("explanation_missing_reason_section")
    if _contains_any(question, ["为什么", "原因", "从数据看"]) and "依据：" not in answer and "从数据看" not in answer:
        score -= 2.0
        failed.append("explanation_missing_grounding")
    if _contains_any(question, ["为什么", "原因"]) and "待核查" not in answer:
        score -= 0.8
        failed.append("explanation_missing_followup_checks")

    score = max(0.0, round(score, 1))
    return {
        "index": int(item["index"]),
        "category": str(item.get("category") or ""),
        "question": question,
        "mode": mode,
        "score": score,
        "checks_failed": failed,
        "seconds": seconds,
        "answer": answer,
    }


def score_run(raw_items: list[dict]) -> dict:
    items = [_score_item(item) for item in raw_items]
    by_category: dict[str, list[float]] = defaultdict(list)
    for item in items:
        by_category[item["category"]].append(float(item["score"]))
    average = round(sum(float(item["score"]) for item in items) / len(items), 2) if items else 0.0
    category_scores = {
        category: round(sum(values) / len(values), 2)
        for category, values in sorted(by_category.items())
    }
    return {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "count": len(items),
            "average_score": average,
            "category_scores": category_scores,
            "low_score_count": sum(1 for item in items if float(item["score"]) < 7.0),
        },
        "items": items,
    }


def compare_scored_runs(*, current: dict, baseline: dict) -> dict:
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
    lines.extend(["", "## Items", ""])
    for item in scored["items"]:
        lines.append(f"- {item['index']:02d} `{item['score']}` {item['question']}")
        if item["checks_failed"]:
            lines.append(f"  - checks_failed: {', '.join(item['checks_failed'])}")
    return "\n".join(lines) + "\n"


def render_comparison_report(comparison: dict) -> str:
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
