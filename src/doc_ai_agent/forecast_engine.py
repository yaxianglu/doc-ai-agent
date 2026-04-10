from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ForecastResult:
    answer: str
    data: list
    evidence: dict


class ForecastEngine:
    def __init__(self, repo):
        self.repo = repo

    @staticmethod
    def _risk_level(score: float) -> str:
        if score >= 85:
            return "高"
        if score >= 60:
            return "中"
        return "低"

    @staticmethod
    def _project_series(series: list[dict], value_key: str, horizon_days: int) -> tuple[float, float]:
        if not series:
            return 0.0, 0.0
        values = [float(item.get(value_key) or 0) for item in series]
        if len(values) == 1:
            baseline = values[-1]
            slope = 0.0
        else:
            baseline = sum(values[-3:]) / min(3, len(values))
            slope = (values[-1] - values[0]) / max(1, len(values) - 1)
        projected = max(0.0, baseline + slope * min(horizon_days, 14) * 0.7)
        return round(projected, 2), round(slope, 2)

    def forecast(self, question: str, plan: dict, context: dict | None = None) -> ForecastResult:
        route = dict(plan or {})
        context = dict(context or {})
        query_type = str(route.get("query_type") or "")
        horizon_days = int(route.get("forecast_window", {}).get("horizon_days") or 14)
        region_name = route.get("city") or route.get("county") or context.get("region_name") or "重点地区"

        if query_type == "pest_forecast":
            series = self.repo.pest_trend(
                str(route.get("since") or context.get("since") or "1970-01-01 00:00:00"),
                route.get("until"),
                region_name,
                region_level=str(route.get("region_level") or "city"),
            )
            projected, slope = self._project_series(series, "severity_score", horizon_days)
            level = self._risk_level(projected)
            return ForecastResult(
                answer=f"{region_name}未来两周虫情风险预计为{level}，预测严重度约 {projected}。",
                data=series,
                evidence={
                    "forecast": {
                        "domain": "pest",
                        "horizon_days": horizon_days,
                        "projected_score": projected,
                        "trend_slope": slope,
                        "risk_level": level,
                    },
                    "analysis_context": {
                        "domain": "pest",
                        "region_name": region_name,
                    },
                },
            )

        if query_type == "soil_forecast":
            series = self.repo.soil_trend(
                str(route.get("since") or context.get("since") or "1970-01-01 00:00:00"),
                route.get("until"),
                region_name,
                region_level=str(route.get("region_level") or "city"),
            )
            projected, slope = self._project_series(series, "avg_anomaly_score", horizon_days)
            level = self._risk_level(projected)
            return ForecastResult(
                answer=f"{region_name}未来两周墒情风险预计为{level}，预测异常得分约 {projected}。",
                data=series,
                evidence={
                    "forecast": {
                        "domain": "soil",
                        "horizon_days": horizon_days,
                        "projected_score": projected,
                        "trend_slope": slope,
                        "risk_level": level,
                    },
                    "analysis_context": {
                        "domain": "soil",
                        "region_name": region_name,
                    },
                },
            )

        return ForecastResult(
            answer="当前预测能力暂未命中明确的虫情/墒情风险场景。",
            data=[],
            evidence={
                "forecast": {
                    "domain": "unknown",
                    "horizon_days": horizon_days,
                    "projected_score": 0,
                    "trend_slope": 0,
                    "risk_level": "低",
                },
                "analysis_context": {"domain": "unknown", "region_name": region_name},
            },
        )
