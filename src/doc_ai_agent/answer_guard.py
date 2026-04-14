"""最终答案守卫：在回复落盘前做规则校验、重写和保守降级。"""

from __future__ import annotations

import re

from .agri_semantics import asks_county_scope, has_trend_intent
from .query_plan import execution_route
from .request_understanding_reasoning import has_negated_trend

TREND_CUES = ("趋势", "上升", "下降", "平稳", "波动", "缓解", "增加", "减少")


class AnswerGuard:
    """对最终答案做轻量规则守卫，优先重写，无法修复时再降级。"""

    @staticmethod
    def _route(plan: dict) -> dict:
        route = dict(plan.get("route") or {})
        if route:
            return route
        return execution_route(plan.get("query_plan"))

    @staticmethod
    def _domains_in_text(text: str) -> set[str]:
        normalized = str(text or "")
        domains: set[str] = set()
        if any(token in normalized for token in ["预警", "报警", "告警"]):
            domains.add("alerts")
        if any(token in normalized for token in ["虫情", "虫害"]):
            domains.add("pest")
        if any(token in normalized for token in ["墒情", "低墒", "高墒", "缺水", "干旱", "土壤含水"]):
            domains.add("soil")
        if "天气" in normalized:
            domains.add("weather")
        return domains

    def _expected_domain(self, question: str, understanding: dict, plan: dict, query_result: dict, forecast_result: dict) -> str:
        question_domains = self._domains_in_text(question)
        if "weather" in question_domains:
            return "weather"
        if "alerts" in question_domains:
            return "alerts"
        if "pest" in question_domains and "soil" not in question_domains:
            return "pest"
        if "soil" in question_domains and "pest" not in question_domains:
            return "soil"
        understanding_domain = str(understanding.get("domain") or "")
        if understanding_domain in {"pest", "soil"}:
            return understanding_domain
        route = self._route(plan)
        query_type = str(
            route.get("query_type")
            or (query_result.get("evidence") or {}).get("query_type")
            or (forecast_result.get("forecast") or {}).get("domain")
            or ""
        )
        if query_type.startswith("pest"):
            return "pest"
        if query_type.startswith("soil"):
            return "soil"
        if "alert" in query_type or query_type in {"count", "top", "avg_by_level", "threshold_summary"}:
            return "alerts"
        return ""

    @staticmethod
    def _has_trend_language(answer: str) -> bool:
        normalized = str(answer or "")
        return any(token in normalized for token in TREND_CUES)

    @staticmethod
    def _sanitize_internal_time(answer: str) -> str:
        sanitized = str(answer or "")
        sanitized = sanitized.replace("从1970-01-01起", "历史上")
        sanitized = sanitized.replace("1970-01-01 00:00:00", "历史")
        sanitized = sanitized.replace("1970-01-01", "历史")
        sanitized = re.sub(r"历史上整体", "整体", sanitized)
        return sanitized

    @staticmethod
    def _trend_text(series: list[dict], value_key: str) -> str:
        if len(series) < 2:
            return "样本不足，暂不判断趋势"
        first = float(series[0].get(value_key) or 0)
        last = float(series[-1].get(value_key) or 0)
        if last > first * 1.15:
            return "整体上升"
        if last < first * 0.85:
            return "整体下降"
        return "整体波动平稳"

    @staticmethod
    def _format_metric(value: float) -> str:
        if float(value).is_integer():
            return f"{value:.0f}"
        return f"{value:.1f}"

    def _rewrite_trend_answer(self, question: str, plan: dict, query_result: dict, response: dict) -> str:
        route = self._route(plan)
        query_type = str(route.get("query_type") or (query_result.get("evidence") or {}).get("query_type") or "")
        series = query_result.get("data") if isinstance(query_result.get("data"), list) else response.get("data")
        if not isinstance(series, list) or not series:
            return str(response.get("answer") or "")

        if query_type == "alerts_trend":
            value_key = "alert_count"
            label = "预警数量"
        elif query_type == "soil_trend":
            value_key = "avg_anomaly_score"
            label = "墒情"
        else:
            value_key = "severity_score"
            label = "虫情"

        trend = self._trend_text(series, value_key)
        first = float(series[0].get(value_key) or 0)
        latest = float(series[-1].get(value_key) or 0)
        peak = max(float(item.get(value_key) or 0) for item in series)
        answer = (
            f"{label}趋势：{trend}，起点{self._format_metric(first)}，最近{self._format_metric(latest)}，"
            f"峰值{self._format_metric(peak)}，共覆盖{len(series)}个观测日。"
        )
        if label == "墒情" and any(token in question for token in ["缓解", "好转"]):
            if trend == "整体下降":
                answer = f"{answer}有缓解迹象。"
            elif trend == "整体上升":
                answer = f"{answer}暂未缓解，异常还有加重迹象。"
            elif trend == "整体波动平稳":
                answer = f"{answer}暂无明显缓解。"
            else:
                answer = f"{answer}暂无法判断是否缓解。"
        return answer

    @staticmethod
    def _rewrite_forecast_support(answer: str, forecast_result: dict) -> str:
        forecast = dict(forecast_result.get("forecast") or {})
        confidence = forecast.get("confidence")
        history_points = int(forecast.get("history_points") or 0)
        factors = [str(item) for item in (forecast.get("top_factors") or []) if str(item).strip()]
        coverage = next((item for item in factors if item.startswith("样本覆盖")), "")
        if not coverage and history_points > 0:
            coverage = f"样本覆盖 {history_points} 个观测日"
        evidence_factors = [item for item in factors if item and item != coverage][:2]
        support = []
        if confidence not in {None, ""}:
            support.append(f"置信度{float(confidence):.2f}")
        if coverage:
            support.append(coverage)
        support_text = "，".join(support)
        reason_text = "、".join(evidence_factors) if evidence_factors else "历史样本与最近波动"
        suffix = f"补充预测依据：{support_text}。依据：{reason_text}。"
        return f"{str(answer or '').rstrip()} {suffix}".strip()

    @staticmethod
    def _fallback_answer(question: str, expected_domain: str, *, county_scope: bool) -> str:
        if expected_domain == "weather":
            return "我目前主要支持农业虫情、墒情、预警数据分析，暂不直接提供天气查询。你如果要看农情，我可以继续帮你查相关风险。"
        if county_scope:
            return "这次回答没有对齐到县级口径，我先保守收口：请让我按县一级重新返回结果，避免把市级排行误当成县级答案。"
        if expected_domain == "alerts":
            return "这次回答没有对齐到预警口径，我先保守收口：请让我按预警/报警数据重新回答，避免混入虫情或墒情排行。"
        if expected_domain == "soil":
            return "这次回答没有对齐到墒情口径，我先保守收口：请让我按墒情数据重新回答，避免混入虫情或预警结果。"
        if expected_domain == "pest":
            return "这次回答没有对齐到虫情口径，我先保守收口：请让我按虫情数据重新回答，避免混入墒情或预警结果。"
        return f"这次回答和你的问题没有完全对齐。我建议我按原问题“{question}”重新生成一次更保守的答案。"

    @staticmethod
    def _retry_route_for_violation(question: str, route: dict, expected_domain: str, violations: list[dict]) -> dict:
        """为可恢复的问题生成一次内部重试 route。"""
        if not violations:
            return {}
        codes = {str(item.get("code") or "") for item in violations}
        updated = dict(route or {})
        if "county_scope_mismatch" in codes and str(updated.get("region_level") or "") == "county":
            if updated.get("city") and updated.get("county") == updated.get("city"):
                updated["county"] = None
                return updated
        if "domain_mismatch" in codes and expected_domain == "alerts":
            if str(updated.get("query_type") or "") in {"top", "count", "", "structured_agri"}:
                updated["query_type"] = "alerts_top" if not has_trend_intent(question) else "alerts_trend"
                return updated
        return {}

    def review(
        self,
        *,
        question: str,
        understanding: dict,
        plan: dict,
        query_result: dict,
        forecast_result: dict,
        response: dict,
    ) -> dict:
        """审查最终回答，并返回 pass / rewrite / fallback 结果。"""
        answer = str(response.get("answer") or "")
        expected_domain = self._expected_domain(question, understanding, plan, query_result, forecast_result)
        answer_domains = self._domains_in_text(answer)
        route = self._route(plan)
        county_scope = asks_county_scope(question) or str(route.get("region_level") or "") == "county"
        hard_violations: list[dict] = []
        soft_violations: list[dict] = []
        rewritten_answer = answer

        if "1970-01-01" in answer:
            soft_violations.append({"code": "internal_default_time_exposed", "message": "回答暴露了内部默认时间。"})
            rewritten_answer = self._sanitize_internal_time(rewritten_answer)

        if expected_domain == "weather" and answer_domains - {"weather"}:
            hard_violations.append({"code": "domain_mismatch", "message": "问题是天气查询，但回答被农业分析结果劫持。"})
        elif expected_domain and expected_domain not in answer_domains and answer_domains & {"alerts", "pest", "soil"}:
            hard_violations.append({"code": "domain_mismatch", "message": "回答领域与问题不一致。"})

        if county_scope:
            mentions_county = bool(re.search(r"[^\s，。；：]{1,12}(县|区|区县)", answer)) or "区县" in answer
            if not mentions_county:
                hard_violations.append({"code": "county_scope_mismatch", "message": "用户要求县级结果，但回答没有按县级返回。"})

        if has_trend_intent(question) and not has_negated_trend(str(question or "")) and not self._has_trend_language(answer):
            rewritten_trend = self._rewrite_trend_answer(question, plan, query_result, response)
            if rewritten_trend and rewritten_trend != answer:
                soft_violations.append({"code": "trend_missing_direction", "message": "趋势问题只答了数量，没有给出趋势判断。"})
                rewritten_answer = rewritten_trend

        forecast_needed = bool(understanding.get("needs_forecast")) or bool((forecast_result.get("forecast") or {}).get("domain"))
        if forecast_needed:
            missing_support = "置信度" not in rewritten_answer or "依据：" not in rewritten_answer or "样本覆盖" not in rewritten_answer
            if missing_support and forecast_result.get("forecast"):
                soft_violations.append({"code": "forecast_missing_support", "message": "预测回答缺少置信度、依据或样本覆盖。"})
                rewritten_answer = self._rewrite_forecast_support(rewritten_answer, forecast_result)

        violations = hard_violations + soft_violations
        if hard_violations:
            retry_route = self._retry_route_for_violation(question, route, expected_domain, hard_violations)
            if retry_route:
                return {
                    "ok": False,
                    "action": "retry",
                    "violations": violations,
                    "rewritten_answer": "",
                    "fallback_answer": "",
                    "retry_route": retry_route,
                }
            fallback_answer = self._fallback_answer(question, expected_domain, county_scope=county_scope)
            return {
                "ok": False,
                "action": "fallback",
                "violations": violations,
                "rewritten_answer": "",
                "fallback_answer": fallback_answer,
                "retry_route": {},
            }
        if rewritten_answer != answer:
            return {
                "ok": False,
                "action": "rewrite",
                "violations": violations,
                "rewritten_answer": rewritten_answer,
                "fallback_answer": "",
                "retry_route": {},
            }
        return {
            "ok": True,
            "action": "pass",
            "violations": [],
            "rewritten_answer": "",
            "fallback_answer": "",
            "retry_route": {},
        }
