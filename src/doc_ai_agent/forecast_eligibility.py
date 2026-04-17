"""预测准入判断：显式决定当前请求是否适合进入预测。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ForecastEligibility:
    eligible: bool
    reason: str
    fallback_mode: str
    confidence_band: str

    def to_dict(self) -> dict:
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "fallback_mode": self.fallback_mode,
            "confidence_band": self.confidence_band,
        }


def evaluate_series_eligibility(series: list[dict], *, value_key: str, horizon_days: int) -> ForecastEligibility:
    """评估单序列预测是否具备可靠性。"""

    history_points = len(series)
    if horizon_days > 90:
        return ForecastEligibility(False, "unsupported_horizon", "trend_only", "low")
    if history_points < 3:
        return ForecastEligibility(False, "insufficient_history", "conservative_trend", "low")

    raw_values = [item.get(value_key) for item in series]
    missing_count = sum(1 for value in raw_values if value in {None, ""})
    missing_rate = missing_count / max(history_points, 1)
    if missing_rate >= 0.4:
        return ForecastEligibility(False, "high_missingness", "trend_only", "low")

    values = [float(value or 0) for value in raw_values if value not in {None, ""}]
    if len(values) >= 4:
        average = sum(values) / len(values)
        peak = max(values)
        trough = min(values)
        if average > 0 and peak > average * 4 and (peak - trough) > average * 2:
            return ForecastEligibility(False, "extreme_volatility", "trend_only", "low")

    confidence_band = "high" if history_points >= 7 and horizon_days <= 14 else "medium"
    return ForecastEligibility(True, "", "", confidence_band)


def evaluate_ranking_eligibility(*, row_count: int, horizon_days: int) -> ForecastEligibility:
    """评估排行预测是否具备基本准入条件。"""

    if horizon_days > 90:
        return ForecastEligibility(False, "unsupported_horizon", "trend_only", "low")
    if row_count <= 0:
        return ForecastEligibility(False, "insufficient_history", "conservative_trend", "low")
    return ForecastEligibility(True, "", "", "medium")
