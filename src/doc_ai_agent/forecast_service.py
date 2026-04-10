from __future__ import annotations

from .forecast_engine import ForecastEngine


class ForecastService:
    def __init__(self, repo):
        self.repo = repo
        self.engine = ForecastEngine(repo)

    @staticmethod
    def _uplift(score: float, horizon_days: int) -> float:
        factor = 1 + min(horizon_days, 30) / 60
        return round(score * factor, 2)

    def forecast_region(self, route: dict, context: dict | None = None) -> dict:
        domain = str((context or {}).get("domain") or route.get("query_type", "")).replace("_forecast", "")
        if domain == "pest" and not hasattr(self.repo, "pest_trend"):
            return self._fallback_region_forecast(route, domain="pest")
        if domain == "soil" and not hasattr(self.repo, "soil_trend"):
            return self._fallback_region_forecast(route, domain="soil")
        result = self.engine.forecast("", route, context=context)
        evidence = dict(result.evidence or {})
        evidence.setdefault("forecast", {})["mode"] = "region"
        return {
            "answer": result.answer,
            "data": result.data,
            "forecast": evidence.get("forecast", {}),
            "analysis_context": evidence.get("analysis_context", {}),
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
                "fallback": True,
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
                {
                    **row,
                    "projected_score": self._uplift(float(row.get("severity_score") or 0), horizon_days),
                }
                for row in raw
            ]
        elif domain == "soil" and hasattr(self.repo, "top_soil_regions"):
            raw = self.repo.top_soil_regions(since, until, region_level=region_level, top_n=top_n, anomaly_direction=None)
            ranked = [
                {
                    **row,
                    "projected_score": self._uplift(float(row.get("anomaly_score") or 0), horizon_days),
                }
                for row in raw
            ]
        else:
            raw = self.repo.top_n_filtered("city", top_n, since) if hasattr(self.repo, "top_n_filtered") else self.repo.top_n("city", top_n, since)
            ranked = [
                {
                    "region_name": row["name"],
                    "record_count": row["count"],
                    "projected_score": self._uplift(float(row["count"]), horizon_days),
                }
                for row in raw
            ]

        ranked.sort(key=lambda row: float(row.get("projected_score") or 0), reverse=True)
        label = "虫情" if domain == "pest" else "墒情"
        answer = (
            f"未来{horizon_days}天{label}风险最高的地区为："
            + "；".join(
                f"{idx+1}.{row['region_name']}（预测得分{row['projected_score']}）"
                for idx, row in enumerate(ranked[:top_n])
            )
        )
        return {
            "answer": answer,
            "data": ranked[:top_n],
            "forecast": {
                "domain": domain,
                "mode": "ranking",
                "horizon_days": horizon_days,
                "risk_level": "高" if ranked else "低",
            },
            "analysis_context": {
                "domain": domain,
                "region_name": "",
            },
        }
