#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from doc_ai_agent.acceptance_eval import compare_scored_runs, load_question_bank, render_comparison_report, render_score_report, score_run
from doc_ai_agent.config import AppConfig
from doc_ai_agent.server import AgentApp


ROOT = Path(__file__).resolve().parents[1]
QUESTION_BANK = ROOT / "evals" / "strict_acceptance_60.json"
EVAL_ROOT = ROOT / "output" / "evals"
SUITE_BANKS = {
    "ood": ROOT / "evals" / "ood_eval.json",
    "explanation": ROOT / "evals" / "explanation_eval.json",
    "forecast": ROOT / "evals" / "forecast_eval.json",
    "context": ROOT / "evals" / "context_eval.json",
}


def _timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _thread_id_for(category: str, known: dict[str, str]) -> str:
    if category not in known:
        known[category] = f"strict-eval-{len(known) + 1}"
    return known[category]


def _load_suite_index() -> dict[int, str]:
    suite_index: dict[int, str] = {}
    for suite_name, path in SUITE_BANKS.items():
        if not path.exists():
            continue
        for item in load_question_bank(path):
            suite_index[int(item["index"])] = suite_name
    return suite_index


def run_eval() -> list[dict]:
    questions = load_question_bank(QUESTION_BANK)
    suite_index = _load_suite_index()
    app = AgentApp(AppConfig.from_env(os.environ))
    app.refresh()
    thread_ids: dict[str, str] = {}
    results: list[dict] = []
    for item in questions:
        response = app.chat(item["question"], thread_id=_thread_id_for(item["category"], thread_ids))
        results.append(
            {
                "index": item["index"],
                "category": item["category"],
                "suite": suite_index.get(int(item["index"]), ""),
                "question": item["question"],
                "ok": True,
                "mode": response.get("mode"),
                "seconds": response.get("processing", {}).get("elapsed_seconds", 0),
                "answer": response.get("answer", ""),
                "evidence": response.get("evidence", {}),
                "processing": response.get("processing", {}),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--baseline", default=str(EVAL_ROOT / "baseline" / "scored.json"))
    parser.add_argument("--from-raw", default="")
    args = parser.parse_args()

    run_dir = EVAL_ROOT / _timestamp_slug()
    latest_dir = EVAL_ROOT / "latest"
    run_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)

    if args.from_raw:
        raw = json.loads(Path(args.from_raw).read_text(encoding="utf-8"))
    else:
        raw = run_eval()
    raw_path = run_dir / "raw.json"
    raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (latest_dir / "raw.json").write_text(raw_path.read_text(encoding="utf-8"), encoding="utf-8")

    if args.score or args.compare:
        scored = score_run(raw)
        scored_path = run_dir / "scored.json"
        report_path = run_dir / "report.md"
        scored_path.write_text(json.dumps(scored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report_path.write_text(render_score_report(scored), encoding="utf-8")
        (latest_dir / "scored.json").write_text(scored_path.read_text(encoding="utf-8"), encoding="utf-8")
        (latest_dir / "report.md").write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")

        if args.compare:
            baseline_path = Path(args.baseline)
            if baseline_path.exists():
                baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
                comparison = compare_scored_runs(current=scored, baseline=baseline)
                compare_path = run_dir / "comparison.md"
                compare_path.write_text(render_comparison_report(comparison), encoding="utf-8")
                (latest_dir / "comparison.md").write_text(compare_path.read_text(encoding="utf-8"), encoding="utf-8")

    print(json.dumps({"run_dir": str(run_dir), "latest_dir": str(latest_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
