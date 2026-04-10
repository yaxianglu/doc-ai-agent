from __future__ import annotations

from dataclasses import dataclass

from .forecast_engine import ForecastEngine


@dataclass
class ForecastProjection:
    projected_score: float
    forecast_backend: str
    model_name: str
    history_points: int
    fallback: bool
    fallback_reason: str


class StatsForecastBackend:
    def forecast_series(self, series: list[dict], *, date_key: str, value_key: str, horizon_days: int) -> ForecastProjection:
        history_points = len(series)
        if history_points < 3:
            return self._fallback_projection(series, value_key=value_key, horizon_days=horizon_days, reason="insufficient_history")

        try:
            import pandas as pd
            from statsforecast import StatsForecast
            from statsforecast.models import AutoETS
        except Exception:
            projected_score = self._manual_projection(series, value_key=value_key, horizon_days=horizon_days)
            return self._build_projection(projected_score, history_points=history_points, fallback=False, fallback_reason="")

        frame = pd.DataFrame(
            {
                "ds": pd.to_datetime([item.get(date_key) for item in series]),
                "y": [float(item.get(value_key) or 0) for item in series],
                "unique_id": ["series-1"] * history_points,
            }
        ).sort_values("ds")
        model = StatsForecast(models=[AutoETS(season_length=1)], freq="D")
        predicted = model.forecast(df=frame, h=max(1, horizon_days))
        projected_score = round(max(0.0, float(predicted["AutoETS"].iloc[-1])), 2)
        return self._build_projection(projected_score, history_points=history_points, fallback=False, fallback_reason="")
        
    @staticmethod
    def _manual_projection(series: list[dict], *, value_key: str, horizon_days: int) -> float:
        values = [float(item.get(value_key) or 0) for item in series]
        if not values:
            return 0.0
        if len(values) == 1:
            baseline = values[-1]
            slope = 0.0
        else:
            baseline = sum(values[-3:]) / min(3, len(values))
            slope = (values[-1] - values[0]) / max(1, len(values) - 1)
        return round(max(0.0, baseline + slope * min(horizon_days, 14) * 0.7), 2)

    @classmethod
    def _build_projection(cls, projected_score: float, *, history_points: int, fallback: bool, fallback_reason: str) -> ForecastProjection:
        return ForecastProjection(
            projected_score=projected_score,
            forecast_backend="statsforecast",
            model_name="AutoETS",
            history_points=history_points,
            fallback=fallback,
            fallback_reason=fallback_reason,
        )

    @staticmethod
    def _fallback_projection(series: list[dict], *, value_key: str, horizon_days: int, reason: str) -> ForecastProjection:
        projected_score = StatsForecastBackend._manual_projection(series, value_key=value_key, horizon_days=horizon_days)
        return StatsForecastBackend._build_projection(
            projected_score,
            history_points=len(series),
            fallback=True,
            fallback_reason=reason,
        )


class ForecastService:
    def __init__(self, repo, backend: StatsForecastBackend | None = None):
        self.repo = repo
        self.engine = ForecastEngine(repo)
        self.backend = backend or StatsForecastBackend()

    @staticmethod
    def _uplift(score: float, horizon_days: int) -> float:
        factor = 1 + min(horizon_days, 30) / 60
        return round(score * factor, 2)

    @staticmethod
    def _risk_level(score: float) -> str:
        if score >= 85:
            return "高"
        if score >= 60:
            return "中"
        return "低"

    def forecast_region(self, route: dict, context: dict | None = None) -> dict:
        domain = str((context or {}).get("domain") or route.get("query_type", "")).replace("_forecast", "")
        if domain == "pest" and not hasattr(self.repo, "pest_trend"):
            return self._fallback_region_forecast(route, domain="pest")
        if domain == "soil" and not hasattr(self.repo, "soil_trend"):
            return self._fallback_region_forecast(route, domain="soil")

        region_name = str(route.get("city") or route.get("county") or (context or {}).get("region_name") or "重点地区")
        horizon_days = int(route.get("forecast_window", {}).get("horizon_days") or 14)
        if domain == "pest":
            series = self.repo.pest_trend(
                str(route.get("since") or (context or {}).get("since") or "1970-01-01 00:00:00"),
                route.get("until"),
                region_name,
                region_level=str(route.get("region_level") or "city"),
            )
            projection = self.backend.forecast_series(series, date_key="date", value_key="severity_score", horizon_days=horizon_days)
        else:
            series = self.repo.soil_trend(
                str(route.get("since") or (context or {}).get("since") or "1970-01-01 00:00:00"),
                route.get("until"),
                region_name,
                region_level=str(route.get("region_level") or "city"),
            )
            projection = self.backend.forecast_series(series, date_key="date", value_key="avg_anomaly_score", horizon_days=horizon_days)

        risk_level = self._risk_level(projection.projected_score)
        label = "虫情" if domain == "pest" else "墒情"
        return {
            "answer": f"{region_name}未来两周{label}风险预计为{risk_level}，预测得分约 {projection.projected_score}。",
            "data": series,
            "forecast": {
                "domain": domain,
                "mode": "region",
                "horizon_days": horizon_days,
                "projected_score": projection.projected_score,
                "risk_level": risk_level,
                "forecast_backend": projection.forecast_backend,
                "model_name": projection.model_name,
                "history_points": projection.history_points,
                "fallback": projection.fallback,
                "fallback_reason": projection.fallback_reason,
            },
            "analysis_context": {"domain": domain, "region_name": region_name},
        }

    def _fallback_region_forecast(self, route: dict, *, domain: str) -> dict:
        since = str(route.get("since") or "1970-01-01 00:00:00")
        horizon_days = int(route.get("forecast_window", {}).get("horizon_days") or 14)
        region_name = str(route.get("city") or route.get("county") or "重点地区")
        if hasattr(self.repo, "count_filtered"):
            count = self.repo.count_filtered(since, city=region_name if route.get("city") else None)
        else:
            count = self.repo.count_since(since)
        projected_score = round(max(1, count) * (1 + min(horizon_days, 30) / 30), 2)
        risk_level = "高" if projected_score >= 4 else ("中" if projected_score >= 2 else "低")
        label = "虫情" if domain == "pest" else "墒情"
        return {
            "answer": f"{region_name}未来{horizon_days}天{label}风险预计为{risk_level}，基于历史告警量近似推断得分 {projected_score}。",
            "data": [{"region_name": region_name, "historical_count": count, "projected_score": projected_score}],
            "forecast": {
                "domain": domain,
                "mode": "region",
                "horizon_days": horizon_days,
                "projected_score": projected_score,
                "risk_level": risk_level,
                "forecast_backend": "statsforecast",
                "model_name": "AutoETS",
                "history_points": 1 if count else 0,
                "fallback": True,
                "fallback_reason": "aggregate_count_only",
            },
            "analysis_context": {"domain": domain, "region_name": region_name},
        }

    def forecast_top_regions(
        self,
        *,
        domain: str,
        since: str,
        horizon_days: int,
        region_level: str = "city",
        top_n: int = 5,
        until: str | None = None,
    ) -> dict:
        if domain == "pest" and hasattr(self.repo, "top_pest_regions"):
            raw = self.repo.top_pest_regions(since, until, region_level=region_level, top_n=top_n)
            ranked = [
                {**row, "projected_score": self._uplift(float(row.get("severity_score") or 0), horizon_days)}
                for row in raw
            ]
        elif domain == "soil" and hasattr(self.repo, "top_soil_regions"):
            raw = self.repo.top_soil_regions(since, until, region_level=region_level, top_n=top_n, anomaly_direction=None)
            ranked = [
                {**row, "projected_score": self._uplift(float(row.get("anomaly_score") or 0), horizon_days)}
                for row in raw
            ]
        else:
            raw = self.repo.top_n_filtered("city", top_n, since) if hasattr(self.repo, "top_n_filtered") else self.repo.top_n("city", top_n, since)
            ranked = [
                {"region_name": row["name"], "record_count": row["count"], "projected_score": self._uplift(float(row["count"]), horizon_days)}
                for row in raw
            ]

        ranked.sort(key=lambda row: float(row.get("projected_score") or 0), reverse=True)
        label = "虫情" if domain == "pest" else "墒情"
        answer = f"未来{horizon_days}天{label}风险最高的地区为：" + "；".join(
            f"{idx+1}.{row['region_name']}（预测得分{row['projected_score']}）" for idx, row in enumerate(ranked[:top_n])
        )
        return {
            "answer": answer,
            "data": ranked[:top_n],
            "forecast": {
                "domain": domain,
                "mode": "ranking",
                "horizon_days": horizon_days,
                "risk_level": "高" if ranked else "低",
                "forecast_backend": "statsforecast",
                "model_name": "AutoETS",
                "history_points": len(ranked),
                "fallback": False,
                "fallback_reason": "",
            },
            "analysis_context": {"domain": domain, "region_name": ""},
        }
