"""Forecast Capability：统一封装未来风险预测。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..capability_result import CapabilityResult

if TYPE_CHECKING:
    from ..forecast_service import ForecastService


class ForecastCapability:
    """对 ForecastService 的轻量能力封装。"""

    def __init__(self, forecast_service: ForecastService):
        self.forecast_service = forecast_service

    def execute(self, route: dict, runtime_context: dict) -> CapabilityResult:
        forecast_mode = str(route.get("forecast_mode") or "")
        if forecast_mode == "ranking":
            result = self.forecast_service.forecast_top_regions(
                domain=str(runtime_context.get("domain") or "pest"),
                since=str(route.get("since") or "1970-01-01 00:00:00"),
                horizon_days=int(route.get("forecast_window", {}).get("horizon_days") or 14),
                region_level=str(route.get("region_level") or "city"),
                top_n=max(1, int(route.get("top_n") or 1)),
                city=route.get("city"),
                county=route.get("county"),
            )
        else:
            result = self.forecast_service.forecast_region(route, context=runtime_context)
        return CapabilityResult(
            type="forecast",
            data=result.get("data"),
            evidence=dict(result.get("forecast") or {}),
            confidence=float((result.get("forecast") or {}).get("confidence") or 0.0),
            meta={
                "answer": str(result.get("answer") or ""),
                "analysis_context": dict(result.get("analysis_context") or {}),
                "forecast": dict(result.get("forecast") or {}),
            },
        )
