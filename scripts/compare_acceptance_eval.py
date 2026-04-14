#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from doc_ai_agent.acceptance_eval import compare_scored_runs, render_comparison_report


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: compare_acceptance_eval.py CURRENT_SCORED BASELINE_SCORED OUTPUT_MD")
    current = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    baseline = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    comparison = compare_scored_runs(current=current, baseline=baseline)
    output_path = Path(sys.argv[3])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_comparison_report(comparison), encoding="utf-8")
    print(json.dumps(comparison["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
