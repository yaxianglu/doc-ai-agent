#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from doc_ai_agent.config import AppConfig
from doc_ai_agent.server import AgentApp


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "acceptance_run_after_data_refresh.json"


def _question_source_candidates() -> list[Path]:
    direct = ROOT / "output" / "acceptance_run_after_data_refresh.json"
    candidates = [direct]
    try:
        proc = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return candidates
    for line in proc.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        worktree_path = Path(line.split(" ", 1)[1].strip())
        candidate = worktree_path / "output" / "acceptance_run_after_data_refresh.json"
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _load_questions() -> list[dict]:
    for candidate in _question_source_candidates():
        if not candidate.exists():
            continue
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        return [
            {
                "index": int(item["index"]),
                "category": str(item["category"]),
                "question": str(item["question"]),
            }
            for item in payload
        ]
    raise SystemExit("cannot find acceptance_run_after_data_refresh.json to source questions")


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
        started = time.perf_counter()
        try:
            response = app.chat(question, thread_id=_thread_id_for(category, thread_ids))
            elapsed = round(time.perf_counter() - started, 2)
            results.append(
                {
                    "index": item["index"],
                    "category": category,
                    "question": question,
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
        print(f"[{item['index']:02d}/50] {category} - {question}")

    OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "count": len(results)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
