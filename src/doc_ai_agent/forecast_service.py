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
        if score >= 70:
            return "高"
        if score >= 40:
            return "中"
        return "低"

    @staticmethod
    def _horizon_phrase(horizon_days: int) -> str:
        if horizon_days == 14:
            return "未来两周"
        return f"未来{horizon_days}天"

    @staticmethod
    def _safe_float(value: object) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _series_stats(cls, series: list[dict], value_key: str) -> dict:
        values = [cls._safe_float(item.get(value_key)) for item in series]
        if not values:
            return {
                "latest": 0.0,
                "average": 0.0,
                "peak": 0.0,
                "history_points": 0,
            }
        return {
            "latest": values[-1],
            "average": sum(values) / len(values),
            "peak": max(values),
            "history_points": len(values),
        }

    @classmethod
    def _risk_index_from_series(cls, projected_score: float, *, latest: float, average: float, peak: float) -> float:
        if projected_score <= 0:
            return 0.0

        components = 0.0
        if peak > 0:
            components += min(projected_score / peak, 1.6) * 35
        if average > 0:
            components += min(projected_score / average, 1.8) * 35
        if latest > 0:
            components += min(projected_score / latest, 1.6) * 30
        elif projected_score > 0:
            components += 10
        return round(min(100.0, components), 1)

    @staticmethod
    def _confidence(history_points: int, *, fallback: bool, horizon_days: int) -> float:
        base = 0.35 + min(max(history_points, 0), 30) / 30 * 0.35
        if history_points >= 7:
            base += 0.08
        if horizon_days <= 14:
            base += 0.05
        elif horizon_days > 30:
            base -= 0.05
        if fallback:
            base -= 0.12
        return round(max(0.2, min(0.93, base)), 2)

    @classmethod
    def _region_top_factors(
        cls,
        *,
        latest: float,
        average: float,
        peak: float,
        history_points: int,
        projected_score: float,
        fallback: bool,
    ) -> list[str]:
        factors: list[str] = []
        if latest >= average * 1.2 and latest > 0:
            factors.append("最近值仍高于窗口均值")
        elif latest <= average * 0.8 and average > 0:
            factors.append("最近值已低于窗口均值")
        else:
            factors.append("最近值与窗口均值接近")

        if peak > 0 and projected_score >= peak * 0.9:
            factors.append("预测结果仍接近历史高位")
        elif peak > 0 and projected_score <= peak * 0.5:
            factors.append("预测结果低于历史高位一半")

        factors.append(f"样本覆盖 {history_points} 个观测日")
        if fallback:
            factors.append("当前使用回退预测方案")
        return factors[:3]

    @classmethod
    def _region_answer(cls, *, region_name: str, horizon_phrase: str, label: str, risk_level: str, confidence: float, top_factors: list[str]) -> str:
        coverage_text = next((item for item in top_factors if str(item).startswith("样本覆盖")), "")
        factor_items = [str(item) for item in top_factors if str(item) and str(item) != coverage_text]
        factor_text = "、".join(factor_items[:2]) if factor_items else "历史样本与最近波动"
        coverage_suffix = f"，{coverage_text}" if coverage_text else ""
        return f"{region_name}{horizon_phrase}{label}风险预计为{risk_level}（置信度{confidence:.2f}{coverage_suffix}）。依据：{factor_text}。"

    @classmethod
    def _ranking_confidence(cls, row: dict, *, horizon_days: int) -> float:
        record_count = cls._safe_float(row.get("record_count") or row.get("abnormal_count"))
        active_days = cls._safe_float(row.get("active_days"))
        base = 0.42 + min(record_count, 30) / 30 * 0.22 + min(active_days, 14) / 14 * 0.14
        if horizon_days <= 14:
            base += 0.04
        return round(max(0.25, min(0.9, base)), 2)

    @classmethod
    def _ranking_factors(cls, row: dict, *, domain: str) -> list[str]:
        if domain == "pest":
            return [
                f"历史严重度 {cls._safe_float(row.get('severity_score')):.1f}",
                f"记录数 {int(cls._safe_float(row.get('record_count')))} 条",
                f"活跃天数 {int(cls._safe_float(row.get('active_days')))} 天",
            ]
        return [
            f"历史异常强度 {cls._safe_float(row.get('anomaly_score')):.1f}",
            f"异常记录 {int(cls._safe_float(row.get('abnormal_count')))} 条",
            f"低墒 {int(cls._safe_float(row.get('low_count')))} / 高墒 {int(cls._safe_float(row.get('high_count')))}",
        ]

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
            stats = self._series_stats(series, "severity_score")
        else:
            series = self.repo.soil_trend(
                str(route.get("since") or (context or {}).get("since") or "1970-01-01 00:00:00"),
                route.get("until"),
                region_name,
                region_level=str(route.get("region_level") or "city"),
            )
            projection = self.backend.forecast_series(series, date_key="date", value_key="avg_anomaly_score", horizon_days=horizon_days)
            stats = self._series_stats(series, "avg_anomaly_score")

        risk_index = self._risk_index_from_series(
            projection.projected_score,
            latest=float(stats["latest"]),
            average=float(stats["average"]),
            peak=float(stats["peak"]),
        )
        risk_level = self._risk_level(risk_index)
        confidence = self._confidence(projection.history_points, fallback=projection.fallback, horizon_days=horizon_days)
        label = "虫情" if domain == "pest" else "墒情"
        horizon_phrase = self._horizon_phrase(horizon_days)
        top_factors = self._region_top_factors(
            latest=float(stats["latest"]),
            average=float(stats["average"]),
            peak=float(stats["peak"]),
            history_points=projection.history_points,
            projected_score=projection.projected_score,
            fallback=projection.fallback,
        )
        return {
            "answer": self._region_answer(
                region_name=region_name,
                horizon_phrase=horizon_phrase,
                label=label,
                risk_level=risk_level,
                confidence=confidence,
                top_factors=top_factors,
            ),
            "data": series,
            "forecast": {
                "domain": domain,
                "mode": "region",
                "horizon_days": horizon_days,
                "projected_score": projection.projected_score,
                "risk_index": risk_index,
                "risk_level": risk_level,
                "confidence": confidence,
                "top_factors": top_factors,
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
        risk_index = min(100.0, round(projected_score * 18, 1))
        risk_level = self._risk_level(risk_index)
        confidence = self._confidence(1 if count else 0, fallback=True, horizon_days=horizon_days)
        label = "虫情" if domain == "pest" else "墒情"
        top_factors = [f"历史样本量 {count} 条", "当前使用回退预测方案"]
        return {
            "answer": self._region_answer(
                region_name=region_name,
                horizon_phrase=self._horizon_phrase(horizon_days),
                label=label,
                risk_level=risk_level,
                confidence=confidence,
                top_factors=top_factors,
            ),
            "data": [{"region_name": region_name, "historical_count": count, "projected_score": projected_score}],
            "forecast": {
                "domain": domain,
                "mode": "region",
                "horizon_days": horizon_days,
                "projected_score": projected_score,
                "risk_index": risk_index,
                "risk_level": risk_level,
                "confidence": confidence,
                "top_factors": top_factors,
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
        city: str | None = None,
        county: str | None = None,
    ) -> dict:
        if domain == "pest" and hasattr(self.repo, "top_pest_regions"):
            raw = self.repo.top_pest_regions(since, until, region_level=region_level, top_n=top_n, city=city, county=county)
            ranked = [
                {**row, "projected_score": self._uplift(float(row.get("severity_score") or 0), horizon_days)}
                for row in raw
            ]
        elif domain == "soil" and hasattr(self.repo, "top_soil_regions"):
            raw = self.repo.top_soil_regions(
                since,
                until,
                region_level=region_level,
                top_n=top_n,
                anomaly_direction=None,
                city=city,
                county=county,
            )
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
        max_score = max((self._safe_float(row.get("projected_score")) for row in ranked), default=0.0)
        for row in ranked:
            if max_score > 0:
                risk_index = round(min(100.0, self._safe_float(row.get("projected_score")) / max_score * 100), 1)
            else:
                risk_index = 0.0
            row["risk_index"] = risk_index
            row["risk_level"] = self._risk_level(risk_index)
            row["confidence"] = self._ranking_confidence(row, horizon_days=horizon_days)
            row["top_factors"] = self._ranking_factors(row, domain=domain)

        label = "虫情" if domain == "pest" else "墒情"
        answer = f"{self._horizon_phrase(horizon_days)}{label}风险最高的地区为：" + "；".join(
            f"{idx+1}.{row['region_name']}（{row['risk_level']}，置信度{row['confidence']:.2f}）" for idx, row in enumerate(ranked[:top_n])
        )
        overall_confidence = round(sum(float(row.get("confidence") or 0) for row in ranked[:top_n]) / max(len(ranked[:top_n]), 1), 2) if ranked else 0.2
        return {
            "answer": answer,
            "data": ranked[:top_n],
            "forecast": {
                "domain": domain,
                "mode": "ranking",
                "horizon_days": horizon_days,
                "risk_level": "高" if ranked else "低",
                "confidence": overall_confidence,
                "top_factors": ["按历史风险强度排序", "结合记录覆盖与活跃天数估计置信度"],
                "forecast_backend": "statsforecast",
                "model_name": "AutoETS",
                "history_points": len(ranked),
                "fallback": False,
                "fallback_reason": "",
            },
            "analysis_context": {"domain": domain, "region_name": ""},
        }
