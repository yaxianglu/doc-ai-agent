#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from doc_ai_agent.acceptance_eval import render_score_report, score_run


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: score_strict_acceptance_eval.py RAW_JSON OUTPUT_DIR")
    raw_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    raw_items = json.loads(raw_path.read_text(encoding="utf-8"))
    scored = score_run(raw_items)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "scored.json").write_text(json.dumps(scored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(render_score_report(scored), encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "average_score": scored["summary"]["average_score"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
