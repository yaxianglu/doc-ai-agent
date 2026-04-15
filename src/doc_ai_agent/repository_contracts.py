"""Shared repository contracts for analytics-facing backends."""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable


@runtime_checkable
class AnalyticsRepository(Protocol):
    """Shared analytics operations expected by query and forecast layers."""

    def backend_label(self) -> str:
        ...

    def count_since(self, since: str) -> int:
        ...

    def top_n(self, field: str, n: int, since: str) -> List[dict]:
        ...

    def sample_alerts(self, since: str, limit: int = 3) -> List[dict]:
        ...

    def available_alert_time_range(self) -> Optional[dict]:
        ...

    def avg_alert_value_by_level(self, since: str) -> List[dict]:
        ...

    def devices_triggered_on_multiple_days(self, since: str, min_days: int = 2, limit: int = 50) -> List[dict]:
        ...

    def count_filtered(
        self,
        since: str,
        until: Optional[str] = None,
        city: Optional[str] = None,
        level: Optional[str] = None,
    ) -> int:
        ...

    def alerts_trend(self, since: str, until: Optional[str] = None, city: Optional[str] = None) -> List[dict]:
        ...

    def top_n_filtered(
        self,
        field: str,
        n: int,
        since: str,
        until: Optional[str] = None,
        city: Optional[str] = None,
        level: Optional[str] = None,
        min_alert_value: Optional[float] = None,
    ) -> List[dict]:
        ...


@runtime_checkable
class AlertQueryRepository(Protocol):
    """Alert-query operations used by standard QueryEngine flows."""

    def count_since(self, since: str) -> int:
        ...

    def top_n(self, field: str, n: int, since: str) -> List[dict]:
        ...

    def sample_alerts(self, since: str, limit: int = 3) -> List[dict]:
        ...

    def available_alert_time_range(self) -> Optional[dict]:
        ...

    def count_filtered(
        self,
        since: str,
        until: Optional[str] = None,
        city: Optional[str] = None,
        level: Optional[str] = None,
    ) -> int:
        ...

    def alerts_trend(self, since: str, until: Optional[str] = None, city: Optional[str] = None) -> List[dict]:
        ...

    def top_n_filtered(
        self,
        field: str,
        n: int,
        since: str,
        until: Optional[str] = None,
        city: Optional[str] = None,
        level: Optional[str] = None,
        min_alert_value: Optional[float] = None,
    ) -> List[dict]:
        ...


@runtime_checkable
class MonitoringRepository(Protocol):
    """Structured agri-monitoring operations used by query flows."""

    def sample_pest_records(self, since: str, until: Optional[str], limit: int = 3) -> List[dict]:
        ...

    def sample_soil_records(self, since: str, until: Optional[str], limit: int = 3) -> List[dict]:
        ...

    def available_pest_time_range(self) -> Optional[dict]:
        ...

    def available_soil_time_range(self, anomaly_direction: Optional[str] = None) -> Optional[dict]:
        ...

    def top_pest_regions(
        self,
        since: str,
        until: Optional[str] = None,
        region_level: str = "city",
        top_n: int = 5,
        city: Optional[str] = None,
        county: Optional[str] = None,
    ) -> List[dict]:
        ...

    def top_soil_regions(
        self,
        since: str,
        until: Optional[str] = None,
        region_level: str = "city",
        top_n: int = 5,
        anomaly_direction: Optional[str] = None,
        city: Optional[str] = None,
        county: Optional[str] = None,
    ) -> List[dict]:
        ...

    def pest_trend(
        self,
        since: str,
        until: Optional[str],
        region_name: Optional[str] = None,
        region_level: str = "city",
    ) -> List[dict]:
        ...

    def soil_trend(
        self,
        since: str,
        until: Optional[str],
        region_name: Optional[str] = None,
        region_level: str = "city",
    ) -> List[dict]:
        ...


@runtime_checkable
class ForecastRepository(Protocol):
    """Forecast-ready structured operations for ranking and regional prediction."""

    def pest_trend(
        self,
        since: str,
        until: Optional[str],
        region_name: Optional[str] = None,
        region_level: str = "city",
    ) -> List[dict]:
        ...


@runtime_checkable
class PestForecastTrendRepository(Protocol):
    """Pest trend-series operations used by regional forecast flows."""

    def pest_trend(
        self,
        since: str,
        until: Optional[str],
        region_name: Optional[str] = None,
        region_level: str = "city",
    ) -> List[dict]:
        ...


@runtime_checkable
class SoilForecastTrendRepository(Protocol):
    """Soil trend-series operations used by regional forecast flows."""

    def soil_trend(
        self,
        since: str,
        until: Optional[str],
        region_name: Optional[str] = None,
        region_level: str = "city",
    ) -> List[dict]:
        ...


@runtime_checkable
class ForecastRankingRepository(Protocol):
    """Structured ranking operations used by top-region forecast flows."""

    def top_pest_regions(
        self,
        since: str,
        until: Optional[str] = None,
        region_level: str = "city",
        top_n: int = 5,
        city: Optional[str] = None,
        county: Optional[str] = None,
    ) -> List[dict]:
        ...

    def top_soil_regions(
        self,
        since: str,
        until: Optional[str] = None,
        region_level: str = "city",
        top_n: int = 5,
        anomaly_direction: Optional[str] = None,
        city: Optional[str] = None,
        county: Optional[str] = None,
    ) -> List[dict]:
        ...

    def soil_trend(
        self,
        since: str,
        until: Optional[str],
        region_name: Optional[str] = None,
        region_level: str = "city",
    ) -> List[dict]:
        ...

    def top_pest_regions(
        self,
        since: str,
        until: Optional[str] = None,
        region_level: str = "city",
        top_n: int = 5,
        city: Optional[str] = None,
        county: Optional[str] = None,
    ) -> List[dict]:
        ...

    def top_soil_regions(
        self,
        since: str,
        until: Optional[str] = None,
        region_level: str = "city",
        top_n: int = 5,
        anomaly_direction: Optional[str] = None,
        city: Optional[str] = None,
        county: Optional[str] = None,
    ) -> List[dict]:
        ...
