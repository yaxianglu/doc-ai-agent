#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from doc_ai_agent.config import AppConfig
from doc_ai_agent.server import AgentApp


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "acceptance_run_after_data_refresh.json"
QUESTION_BANK = ROOT / "evals" / "strict_acceptance_140.json"


def _load_questions() -> list[dict]:
    if not QUESTION_BANK.exists():
        raise SystemExit(f"cannot find strict question bank: {QUESTION_BANK}")
    payload = json.loads(QUESTION_BANK.read_text(encoding="utf-8"))
    return [
        {
            "index": int(item["index"]),
            "category": str(item["category"]),
            "question": str(item["question"]),
            "turns": [str(turn) for turn in item.get("turns", [])] if isinstance(item.get("turns"), list) else [],
        }
        for item in payload
    ]


def _thread_id_for(category: str, known: dict[str, str]) -> str:
    if category not in known:
        known[category] = f"acceptance-{len(known) + 1}"
    return known[category]


def main() -> int:
    cfg = AppConfig.from_env(os.environ)
    app = AgentApp(cfg)
    app.refresh()
    questions = _load_questions()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    thread_ids: dict[str, str] = {}
    results: list[dict] = []

    for item in questions:
        question = item["question"]
        category = item["category"]
        turns = list(item.get("turns") or [])
        started = time.perf_counter()
        try:
            if turns:
                thread_id = f"acceptance-multi-{int(item['index'])}"
                turn_results: list[dict] = []
                response = {}
                for turn in turns:
                    response = app.chat(turn, thread_id=thread_id)
                    turn_results.append(
                        {
                            "question": turn,
                            "ok": True,
                            "mode": response.get("mode"),
                            "seconds": float(response.get("processing", {}).get("elapsed_seconds", 0) or 0),
                            "answer": response.get("answer", ""),
                        }
                    )
            else:
                response = app.chat(question, thread_id=_thread_id_for(category, thread_ids))
            elapsed = round(time.perf_counter() - started, 2)
            results.append(
                {
                    "index": item["index"],
                    "category": category,
                    "question": question,
                    "turns": turns,
                    "turn_results": turn_results if turns else [],
                    "ok": True,
                    "mode": response.get("mode"),
                    "seconds": elapsed,
                    "answer": response.get("answer", ""),
                    "evidence": response.get("evidence", {}),
                }
            )
        except Exception as exc:  # pragma: no cover - acceptance harness
            elapsed = round(time.perf_counter() - started, 2)
            results.append(
                {
                    "index": item["index"],
                    "category": category,
                    "question": question,
                    "ok": False,
                    "seconds": elapsed,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        print(f"[{item['index']:02d}/{len(questions)}] {category} - {question}")

    OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "count": len(results)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
