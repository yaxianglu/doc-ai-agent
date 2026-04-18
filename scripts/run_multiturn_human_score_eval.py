#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from doc_ai_agent.acceptance_eval import render_score_report, score_run
from doc_ai_agent.agent import DocAIAgent
from doc_ai_agent.capabilities.forecast import ForecastCapability


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "multiturn_human_score_cases.json"
OUTPUT_ROOT = ROOT / "output" / "evals" / "multiturn-human-score"
PASS_SCORE = 7.0
THRESHOLDS = {
    "average_score": 6.5,
    "pass_rate": 0.65,
    "generic_clarification_rate": 0.10,
}
GENERIC_CLARIFICATION_PATTERNS = [
    "数据统计，还是生成处置建议",
    "你希望我做数据统计，还是生成处置建议",
]
EXPLANATION_FAILURE_KEYS = {
    "explanation_missing_reason_section",
    "explanation_missing_grounding",
    "explanation_missing_followup_checks",
}


class EvalRepo:
    def count_since(self, since):
        del since
        return 22

    def top_n(self, field, n, since):
        return self.top_n_filtered(field, n, since)

    def available_alert_time_range(self):
        return {
            "min_time": "2026-01-01 00:00:00",
            "max_time": "2026-04-10 00:00:00",
        }

    def top_n_filtered(self, field, n, since, until=None, city=None, level=None, min_alert_value=None):
        del since, until, city, level, min_alert_value
        if field == "county":
            return [
                {"name": "如东县", "count": 9},
                {"name": "溧阳市", "count": 7},
            ][:n]
        return [
            {"name": "常州市", "count": 12},
            {"name": "徐州市", "count": 10},
        ][:n]

    def sample_alerts(self, since, limit=3):
        del since
        return [{"alert_id": "A-1"}][:limit]

    def count_filtered(self, since, until=None, city=None, level=None):
        del since, until, city, level
        return 22

    def alerts_trend(self, since, until=None, city=None):
        del since, until
        if city == "常州市":
            return [
                {"date": "2026-03-20", "alert_count": 3},
                {"date": "2026-03-27", "alert_count": 5},
                {"date": "2026-04-03", "alert_count": 8},
            ]
        return [
            {"date": "2026-03-20", "alert_count": 6},
            {"date": "2026-03-27", "alert_count": 9},
            {"date": "2026-04-03", "alert_count": 12},
        ]

    def top_pest_regions(self, since, until, region_level="city", top_n=5, city=None, county=None):
        city_rows = [
            {"region_name": "常州市", "severity_score": 120, "record_count": 16, "active_days": 7},
            {"region_name": "徐州市", "severity_score": 92, "record_count": 14, "active_days": 6},
        ]
        county_rows = [
            {"region_name": "溧阳市", "severity_score": 48, "record_count": 7, "active_days": 4},
            {"region_name": "金坛区", "severity_score": 36, "record_count": 5, "active_days": 3},
        ]
        if region_level == "county":
            if city == "常州市":
                return county_rows[:top_n]
            if city == "徐州市":
                return [
                    {"region_name": "沛县", "severity_score": 41, "record_count": 6, "active_days": 4},
                    {"region_name": "邳州市", "severity_score": 29, "record_count": 4, "active_days": 3},
                ][:top_n]
            return (county_rows + [{"region_name": "沛县", "severity_score": 41, "record_count": 6, "active_days": 4}])[:top_n]
        if city:
            return [row for row in city_rows if row["region_name"] == city][:top_n]
        return city_rows[:top_n]

    def pest_trend(self, since, until, region_name, region_level="city"):
        del since, until, region_level
        if region_name in {"常州市", "溧阳市", "金坛区"}:
            return [
                {"date": "2026-03-20", "severity_score": 16},
                {"date": "2026-03-27", "severity_score": 24},
                {"date": "2026-04-03", "severity_score": 33},
            ]
        return [
            {"date": "2026-03-20", "severity_score": 20},
            {"date": "2026-03-27", "severity_score": 19},
            {"date": "2026-04-03", "severity_score": 18},
        ]

    def sample_pest_records(self, since, until, limit=3):
        del since, until
        return [
            {
                "city_name": "常州市",
                "county_name": "溧阳市",
                "normalized_pest_count": 12,
                "monitor_time": "2026-04-03 08:00:00",
            }
        ][:limit]

    def joint_risk_regions(self, since, until, region_level="city", top_n=5, city=None, county=None):
        del since, until, region_level, county
        rows = [
            {"region_name": "常州市", "joint_score": 118, "pest_score": 80, "low_soil_score": 38},
            {"region_name": "徐州市", "joint_score": 102, "pest_score": 71, "low_soil_score": 31},
        ]
        if city:
            rows = [row for row in rows if row["region_name"] == city]
        return rows[:top_n]

    def available_soil_time_range(self, anomaly_direction=None):
        del anomaly_direction
        return None

    def top_soil_regions(self, since, until, region_level="city", top_n=5, anomaly_direction=None, city=None, county=None):
        del since, until, region_level, anomaly_direction, city, county
        return [
            {
                "region_name": "常州市",
                "anomaly_score": 88,
                "abnormal_count": 16,
                "low_count": 11,
                "high_count": 0,
            },
            {
                "region_name": "徐州市",
                "anomaly_score": 73,
                "abnormal_count": 12,
                "low_count": 8,
                "high_count": 1,
            },
        ][:top_n]

    def sample_soil_records(self, since, until, limit=3):
        del since, until
        return [
            {
                "city_name": "常州市",
                "county_name": "金坛区",
                "soil_anomaly_score": 18,
                "sample_time": "2026-04-01 08:00:00",
            }
        ][:limit]

    def soil_trend(self, since, until, region_name, region_level="city"):
        del since, until, region_name, region_level
        return [
            {"date": "2026-03-28", "avg_anomaly_score": 45},
            {"date": "2026-03-29", "avg_anomaly_score": 56},
            {"date": "2026-03-30", "avg_anomaly_score": 70},
            {"date": "2026-03-31", "avg_anomaly_score": 81},
        ]

    def top_active_devices(self, since, until=None, limit=10, city=None, county=None):
        del since, until, city
        region = county or ""
        return [
            {
                "device_code": "SNS-RD-001" if region == "如东县" else "SNS001",
                "device_name": "如东虫情设备" if region == "如东县" else "设备1",
                "alert_count": 5,
                "active_days": 3,
                "last_alert_time": "2026-04-13 10:00:00",
            },
            {
                "device_code": "SNS-RD-002" if region == "如东县" else "SNS002",
                "device_name": "如东墒情设备" if region == "如东县" else "设备2",
                "alert_count": 4,
                "active_days": 2,
                "last_alert_time": "2026-04-12 10:00:00",
            },
        ][:limit]

    def latest_by_device(self, device_code, since=None, until=None):
        del until
        if device_code != "SNS00204659":
            return None
        if since and since >= "2026-04-10 00:00:00":
            return {
                "alert_time": "2026-04-13 10:00:00",
                "alert_level": "橙色预警",
                "disposal_suggestion": "建议先排查设备点位，再复核周边田块。",
                "city": "常州市",
                "county": "武进区",
                "device_code": device_code,
                "device_name": "常州设备1",
            }
        return {
            "alert_time": "2025-12-24 00:00:00",
            "alert_level": "涝渍",
            "disposal_suggestion": "建议尽快排水散墒。",
            "city": "常州市",
            "county": "武进区",
            "device_code": device_code,
            "device_name": "常州设备1",
        }


class EvalSourceProvider:
    def search(self, question, limit=3, context=None):
        del question, context
        return [
            {
                "title": "虫情监测与绿色防控技术",
                "snippet": "加强监测预警，按阈值和区域分级响应。",
                "domain": "pest",
            }
        ][:limit]


class WeakEvidenceForecastService:
    def forecast_top_regions(self, domain, since, horizon_days, region_level="city", top_n=1, city=None, county=None, anomaly_direction=None):
        del since, anomaly_direction
        region_name = county or city or ("如东县" if region_level == "county" else "常州市")
        return {
            "answer": f"未来{horizon_days}天{region_name}{domain}风险一定会继续恶化。",
            "data": [{"region_name": region_name, "risk_level": "高"}][:top_n],
            "forecast": {
                "domain": domain,
                "mode": "ranking",
                "confidence": 0.18,
                "history_points": 3,
                "top_factors": ["样本覆盖 3 个观测日", "最近值仍高于窗口均值"],
                "risk_level": "高",
            },
            "analysis_context": {"domain": domain, "region_name": region_name, "region_level": region_level},
        }

    def forecast_region(self, route, context=None):
        del route, context
        return {
            "answer": "未来两周常州市虫情一定会继续恶化。",
            "data": [{"region_name": "常州市", "risk_level": "高"}],
            "forecast": {
                "domain": "pest",
                "mode": "region",
                "confidence": 0.18,
                "history_points": 3,
                "top_factors": ["样本覆盖 3 个观测日", "最近值仍高于窗口均值"],
                "risk_level": "高",
            },
            "analysis_context": {"domain": "pest", "region_name": "常州市", "region_level": "city"},
        }


def _timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def load_groups(path: Path = FIXTURE_PATH) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("groups") or [])


def _looks_like_generic_clarification(answer: str) -> bool:
    normalized = str(answer or "")
    return any(pattern in normalized for pattern in GENERIC_CLARIFICATION_PATTERNS)


def _build_agent(memory_path: Path, *, weak_forecast: bool = False) -> DocAIAgent:
    agent = DocAIAgent(
        EvalRepo(),
        memory_store_path=str(memory_path),
        source_provider=EvalSourceProvider(),
    )
    if weak_forecast:
        agent.forecast_capability = ForecastCapability(WeakEvidenceForecastService())
    return agent


def run_raw_eval(output_root: Path | None = None) -> list[dict]:
    groups = load_groups()
    output_root = Path(output_root or OUTPUT_ROOT)
    memory_root = output_root / "tmp-memory"
    if memory_root.exists():
        shutil.rmtree(memory_root)
    memory_root.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for group in groups:
        group_id = str(group.get("group_id") or "")
        agent = _build_agent(memory_root / f"{group_id}.json", weak_forecast=(group_id == "17"))
        thread_id = f"multiturn-human-score-{group_id}"
        turn_results: list[dict] = []
        final_response: dict = {}
        total_seconds = 0.0
        for turn in list(group.get("turns") or []):
            question = str(turn.get("user_input") or "")
            response = agent.answer(question, thread_id=thread_id)
            elapsed = float(response.get("processing", {}).get("elapsed_seconds", 0) or 0)
            total_seconds += elapsed
            final_response = response
            turn_results.append(
                {
                    "question": question,
                    "ok": True,
                    "mode": response.get("mode"),
                    "seconds": elapsed,
                    "answer": response.get("answer", ""),
                }
            )
        results.append(
            {
                "index": int(group_id),
                "category": "多轮上下文",
                "suite": "context",
                "question": str((group.get("turns") or [{}])[0].get("user_input") or ""),
                "ok": True,
                "mode": final_response.get("mode"),
                "seconds": round(total_seconds, 2),
                "answer": final_response.get("answer", ""),
                "evidence": final_response.get("evidence", {}),
                "processing": final_response.get("processing", {}),
                "turn_results": turn_results,
                "failure_cluster": str(group.get("failure_cluster") or ""),
            }
        )
    return results


def score_multiturn_run(raw_items: list[dict]) -> dict:
    scored = score_run(raw_items)
    scored_items = list(scored.get("items") or [])
    turn_items: list[dict] = []
    for item in scored_items:
        turns = list(item.get("turn_scores") or [])
        if turns:
            turn_items.extend(turns)
        else:
            turn_items.append(item)

    generic_clarification_count = sum(1 for item in turn_items if _looks_like_generic_clarification(item.get("answer", "")))
    explanation_followup_failure_count = sum(
        1
        for item in turn_items
        if any(key in set(item.get("checks_failed") or []) for key in EXPLANATION_FAILURE_KEYS)
    )
    pass_count = sum(1 for item in scored_items if float(item.get("score") or 0) >= PASS_SCORE)
    count = len(scored_items)
    pass_rate = round(pass_count / count, 2) if count else 0.0
    turn_count = len(turn_items)
    generic_clarification_rate = round(generic_clarification_count / turn_count, 2) if turn_count else 0.0

    failure_clusters = Counter()
    for item in turn_items:
        for failed in list(item.get("checks_failed") or []):
            failure_clusters[str(failed)] += 1

    summary = dict(scored.get("summary") or {})
    summary.update(
        {
            "count": count,
            "turn_count": turn_count,
            "pass_count": pass_count,
            "pass_rate": pass_rate,
            "generic_clarification_count": generic_clarification_count,
            "generic_clarification_rate": generic_clarification_rate,
            "explanation_followup_failure_count": explanation_followup_failure_count,
            "failure_clusters": dict(sorted(failure_clusters.items())),
        }
    )
    gate_checks = {
        "average_score": float(summary.get("average_score") or 0) >= THRESHOLDS["average_score"],
        "pass_rate": pass_rate >= THRESHOLDS["pass_rate"],
        "generic_clarification_rate": generic_clarification_rate < THRESHOLDS["generic_clarification_rate"],
        "explanation_followup_failures": explanation_followup_failure_count == 0,
    }
    scored["summary"] = summary
    scored["gate"] = {
        "suite": "context",
        "thresholds": dict(THRESHOLDS),
        "checks": gate_checks,
        "passed": all(gate_checks.values()),
    }
    return scored


def render_multiturn_report(scored: dict) -> str:
    base = render_score_report(scored).rstrip()
    summary = scored["summary"]
    gate = scored["gate"]
    lines = [
        base,
        "",
        "## Multi-Turn Gate",
        "",
        f"- Pass Count: {summary['pass_count']}/{summary['count']}",
        f"- Pass Rate: {summary['pass_rate']}",
        f"- Generic Clarification Count: {summary['generic_clarification_count']}/{summary['turn_count']}",
        f"- Generic Clarification Rate: {summary['generic_clarification_rate']}",
        f"- Explanation Follow-Up Failure Count: {summary['explanation_followup_failure_count']}",
        f"- Gate Passed: {gate['passed']}",
        "",
        "## Failure Clusters",
        "",
    ]
    if summary["failure_clusters"]:
        for key, value in summary["failure_clusters"].items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def write_eval_artifacts(*, output_root: Path, raw_items: list[dict], scored: dict) -> dict:
    run_dir = output_root / _timestamp_slug()
    latest_dir = output_root / "latest"
    run_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)

    raw_path = run_dir / "raw.json"
    scored_path = run_dir / "scored.json"
    report_path = run_dir / "report.md"

    raw_path.write_text(json.dumps(raw_items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scored_path.write_text(json.dumps(scored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(render_multiturn_report(scored), encoding="utf-8")

    (latest_dir / "raw.json").write_text(raw_path.read_text(encoding="utf-8"), encoding="utf-8")
    (latest_dir / "scored.json").write_text(scored_path.read_text(encoding="utf-8"), encoding="utf-8")
    (latest_dir / "report.md").write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    return {"run_dir": str(run_dir), "latest_dir": str(latest_dir)}


def run_eval(*, output_root: Path | None = None) -> dict:
    output_root = Path(output_root or OUTPUT_ROOT)
    raw_items = run_raw_eval(output_root=output_root)
    scored = score_multiturn_run(raw_items)
    scored["paths"] = write_eval_artifacts(output_root=output_root, raw_items=raw_items, scored=scored)
    return scored


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    args = parser.parse_args()

    scored = run_eval(output_root=Path(args.output_root))
    print(json.dumps(scored.get("paths") or {}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
