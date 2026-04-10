from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

INPUT = Path('/Users/mac/Desktop/personal/doc-cloud/output/playwright/doccloud-eval/dialogue_raw.json')
OUTPUT = Path('/Users/mac/Desktop/personal/doc-cloud/doc-ai-agent/docs/reports/2026-04-10-50-dialogue-evaluation.md')


def contains_all(text: str, words: list[str]) -> tuple[bool, list[str]]:
    missing = [word for word in words if word not in text]
    return not missing, missing


def contains_any(text: str, words: list[str]) -> tuple[bool, list[str]]:
    hits = [word for word in words if word in text]
    return bool(hits), hits


def main() -> int:
    if not INPUT.exists():
        raise SystemExit(f'missing input: {INPUT}')
    payload = json.loads(INPUT.read_text(encoding='utf-8'))
    results = payload.get('results', [])
    lines: list[str] = []
    scores: list[float] = []
    lines.append('# 50轮真实对话评测报告')
    lines.append('')
    lines.append(f'- 生成时间：{payload.get("generatedAt", "") or "unknown"}')
    lines.append(f'- 总条数：{len(results)}')
    lines.append('')
    lines.append('## 总览')
    lines.append('')

    category_scores: dict[str, list[float]] = {}
    low_cases: list[tuple[str, float, str]] = []

    for item in results:
        score = 10.0
        notes: list[str] = []
        response = str(item.get('response') or '')
        panel = str(item.get('panelText') or '')
        status = str(item.get('status') or '')
        meta = item.get('meta') or {}
        expected_mode = str(item.get('expectedMode') or '')
        actual_mode = str(meta.get('mode') or '')
        if status != 'done':
            score -= 5
            notes.append(f'回复状态异常：{status}')
        if expected_mode and actual_mode != expected_mode:
            score -= 2
            notes.append(f'模式不匹配：期望 {expected_mode}，实际 {actual_mode or "unknown"}')
        if len(response.strip()) < int(item.get('minAnswerLength') or 0):
            score -= 1.5
            notes.append('回答长度偏短')
        must_all = item.get('mustContainAll') or []
        if must_all:
            ok, missing = contains_all(response, must_all)
            if not ok:
                score -= min(2.5, 0.8 * len(missing))
                notes.append('缺少关键点：' + '、'.join(missing))
        must_any = item.get('mustContainAny') or []
        if must_any:
            ok, hits = contains_any(response, must_any)
            if not ok:
                score -= 1.5
                notes.append('未命中任一关键点：' + '、'.join(must_any))
        if expected_mode and actual_mode and expected_mode in {'analysis', 'data_query'} and '处理链' not in panel:
            score -= 0.5
            notes.append('右侧分析面板未体现处理链')
        if item.get('expectContext') and not item.get('usedContext'):
            score -= 1.5
            notes.append('该轮应使用上下文，但证据显示未使用')
        if item.get('expectFreshContext') and item.get('usedContext'):
            score -= 0.5
            notes.append('该轮期望独立理解，但仍沿用了上下文')
        if response.startswith('timeout waiting for response'):
            score -= 3
            notes.append('页面等待超时')
        score = max(0.0, round(score, 1))
        scores.append(score)
        category = str(item.get('category') or 'unknown')
        category_scores.setdefault(category, []).append(score)
        if score < 8.0:
            low_cases.append((str(item.get('id')), score, '; '.join(notes) or '综合表现偏弱'))

        lines.append(f"## {item.get('id')} · {category}")
        lines.append('')
        lines.append(f"- 问题：{item.get('prompt')}")
        lines.append(f"- 预期模式：{expected_mode or 'unknown'}")
        lines.append(f"- 实际模式：{actual_mode or 'unknown'}")
        lines.append(f"- 会话ID：{item.get('sessionId') or '—'}")
        lines.append(f"- 耗时：{item.get('durationMs') or '—'} ms")
        lines.append(f"- 使用上下文：{'是' if item.get('usedContext') else '否'}")
        lines.append(f"- 评分：{score}/10")
        lines.append('- 回复：')
        lines.append('')
        lines.append('```text')
        lines.append(response.strip())
        lines.append('```')
        lines.append('')
        lines.append(f"- 分析：{'; '.join(notes) if notes else '命中预期，回答完整，处理链与证据可读性正常。'}")
        lines.append('')

    avg = round(mean(scores), 2) if scores else 0.0
    lines.insert(6, f'- 平均分：{avg}/10')
    lines.insert(7, f'- 低于8分条数：{len(low_cases)}')
    lines.insert(8, '')
    lines.insert(9, '### 分类均分')
    lines.insert(10, '')
    idx = 11
    for category, values in sorted(category_scores.items()):
        lines.insert(idx, f'- {category}: {round(mean(values), 2)}/10')
        idx += 1
    lines.insert(idx, '')
    idx += 1
    lines.insert(idx, '### 低分样本')
    idx += 1
    lines.insert(idx, '')
    idx += 1
    if low_cases:
        for case_id, score, reason in low_cases:
            lines.insert(idx, f'- {case_id}: {score}/10 · {reason}')
            idx += 1
    else:
        lines.insert(idx, '- 无')
        idx += 1
    OUTPUT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(OUTPUT), 'avg': avg, 'low_cases': len(low_cases), 'count': len(results)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
