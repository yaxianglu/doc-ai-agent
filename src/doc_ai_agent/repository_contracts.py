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
