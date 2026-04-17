import unittest
from unittest.mock import patch
from types import SimpleNamespace

from doc_ai_agent.forecast_service import ForecastService, StatsForecastBackend


class FakeForecastRepo:
    def pest_trend(self, since, until, region_name, region_level="city"):
        return [
            {"date": "2026-03-28", "severity_score": 50},
            {"date": "2026-03-29", "severity_score": 60},
            {"date": "2026-03-30", "severity_score": 72},
            {"date": "2026-03-31", "severity_score": 84},
        ]

    def soil_trend(self, since, until, region_name, region_level="city"):
        return [
            {"date": "2026-03-28", "avg_anomaly_score": 45},
            {"date": "2026-03-29", "avg_anomaly_score": 55},
            {"date": "2026-03-30", "avg_anomaly_score": 70},
            {"date": "2026-03-31", "avg_anomaly_score": 82},
        ]

    def top_pest_regions(self, since, until, region_level="city", top_n=5, city=None, county=None):
        return [
            {"region_name": "徐州市", "severity_score": 90, "record_count": 18, "active_days": 7},
            {"region_name": "淮安市", "severity_score": 75, "record_count": 14, "active_days": 6},
        ][:top_n]

    def top_soil_regions(self, since, until, region_level="city", top_n=5, anomaly_direction=None, city=None, county=None):
        return [
            {"region_name": "宿迁市", "anomaly_score": 88, "abnormal_count": 16, "low_count": 11, "high_count": 0},
            {"region_name": "盐城市", "anomaly_score": 73, "abnormal_count": 12, "low_count": 8, "high_count": 1},
        ][:top_n]


class CountyForecastRepo(FakeForecastRepo):
    def top_pest_regions(self, since, until, region_level="city", top_n=5, city=None, county=None):
        if region_level == "county":
            return [
                {"region_name": "铜山区", "severity_score": 90, "record_count": 18, "active_days": 7},
                {"region_name": "沛县", "severity_score": 75, "record_count": 14, "active_days": 6},
            ][:top_n]
        return super().top_pest_regions(since, until, region_level=region_level, top_n=top_n, city=city, county=county)

    def top_soil_regions(self, since, until, region_level="city", top_n=5, anomaly_direction=None, city=None, county=None):
        if region_level == "county" and anomaly_direction == "low":
            return [
                {"region_name": "如东县", "anomaly_score": 62, "abnormal_count": 8, "low_count": 8, "high_count": 0, "active_days": 1},
            ][:top_n]
        if region_level == "county" and anomaly_direction == "high":
            return [
                {"region_name": "启东市", "anomaly_score": 58, "abnormal_count": 7, "low_count": 0, "high_count": 7, "active_days": 1},
            ][:top_n]
        return super().top_soil_regions(
            since,
            until,
            region_level=region_level,
            top_n=top_n,
            anomaly_direction=anomaly_direction,
            city=city,
            county=county,
        )


class ForecastServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = ForecastService(FakeForecastRepo())

    def test_forecast_region_pest_risk(self):
        result = self.service.forecast_region(
            {
                "query_type": "pest_forecast",
                "since": "2026-03-01 00:00:00",
                "city": "徐州市",
                "region_level": "city",
                "forecast_window": {"horizon_days": 14},
            }
        )

        self.assertEqual(result["forecast"]["domain"], "pest")
        self.assertEqual(result["forecast"]["horizon_days"], 14)
        self.assertEqual(result["forecast"]["history_points"], 4)
        self.assertIn(result["forecast"]["forecast_backend"], {"statsforecast", "manual_trend"})
        self.assertIn(result["forecast"]["model_name"], {"AutoETS", "rule_based"})
        if result["forecast"]["forecast_backend"] == "manual_trend":
            self.assertTrue(result["forecast"]["fallback"])
            self.assertIn(result["forecast"]["fallback_reason"], {"backend_unavailable", "backend_runtime_error"})
        else:
            self.assertFalse(result["forecast"]["fallback"])
        self.assertEqual(result["analysis_context"]["region_name"], "徐州市")
        self.assertIn("徐州市", result["answer"])

    def test_forecast_top_soil_risk_regions(self):
        result = self.service.forecast_top_regions(
            domain="soil",
            since="2026-03-01 00:00:00",
            horizon_days=30,
            region_level="city",
        )

        self.assertEqual(result["forecast"]["domain"], "soil")
        self.assertEqual(result["forecast"]["mode"], "ranking")
        self.assertEqual(result["forecast"]["horizon_days"], 30)
        self.assertEqual(result["forecast"]["forecast_backend"], "statsforecast")
        self.assertEqual(result["forecast"]["model_name"], "AutoETS")
        self.assertEqual(result["data"][0]["region_name"], "宿迁市")
        self.assertIn("宿迁市", result["answer"])

    def test_forecast_region_uses_requested_horizon_in_answer_text(self):
        result = self.service.forecast_region(
            {
                "query_type": "soil_forecast",
                "since": "2026-03-01 00:00:00",
                "city": "苏州市",
                "region_level": "city",
                "forecast_window": {"window_type": "months", "window_value": 1, "horizon_days": 30},
            }
        )

        self.assertEqual(result["forecast"]["horizon_days"], 30)
        self.assertIn("未来30天", result["answer"])

    def test_forecast_region_returns_confidence_and_key_factors(self):
        result = self.service.forecast_region(
            {
                "query_type": "pest_forecast",
                "since": "2026-03-01 00:00:00",
                "city": "徐州市",
                "region_level": "city",
                "forecast_window": {"horizon_days": 14},
            }
        )

        self.assertIn("confidence", result["forecast"])
        self.assertIn("top_factors", result["forecast"])
        self.assertGreater(result["forecast"]["confidence"], 0)
        self.assertTrue(result["forecast"]["top_factors"])
        self.assertIn("置信度", result["answer"])
        self.assertIn("依据", result["answer"])
        self.assertNotIn("预测得分约", result["answer"])

    def test_forecast_top_regions_returns_region_confidence(self):
        result = self.service.forecast_top_regions(
            domain="pest",
            since="2026-03-01 00:00:00",
            horizon_days=14,
            region_level="city",
        )

        self.assertIn("confidence", result["forecast"])
        self.assertTrue(result["data"])
        self.assertIn("confidence", result["data"][0])
        self.assertIn("risk_level", result["data"][0])
        self.assertIn("置信度", result["answer"])

    def test_forecast_top_regions_answer_includes_overall_evidence_summary(self):
        result = self.service.forecast_top_regions(
            domain="soil",
            since="2026-03-01 00:00:00",
            horizon_days=14,
            region_level="city",
        )

        self.assertIn("整体置信度", result["answer"])
        self.assertIn("依据：", result["answer"])

    def test_statsforecast_backend_unavailable_marks_projection_as_fallback(self):
        backend = StatsForecastBackend()

        with patch.dict("sys.modules", {"statsforecast": None, "statsforecast.models": None}):
            projection = backend.forecast_series(
                [
                    {"date": "2026-03-28", "severity_score": 50},
                    {"date": "2026-03-29", "severity_score": 60},
                    {"date": "2026-03-30", "severity_score": 72},
                    {"date": "2026-03-31", "severity_score": 84},
                ],
                date_key="date",
                value_key="severity_score",
                horizon_days=14,
            )

        self.assertTrue(projection.fallback)
        self.assertEqual(projection.fallback_reason, "backend_unavailable")

    def test_statsforecast_runtime_error_falls_back_to_manual_trend(self):
        backend = StatsForecastBackend()

        class FakeDataFrame:
            def __init__(self, payload):
                self.payload = payload

            def sort_values(self, key):
                return self

        class FakeStatsForecast:
            def __init__(self, models, freq):
                self.models = models
                self.freq = freq

            def forecast(self, df, h):
                raise NotImplementedError("tiny datasets")

        fake_pandas = SimpleNamespace(
            DataFrame=lambda payload: FakeDataFrame(payload),
            to_datetime=lambda values: values,
        )
        fake_statsforecast = SimpleNamespace(StatsForecast=FakeStatsForecast)
        fake_models = SimpleNamespace(AutoETS=lambda season_length=1: {"season_length": season_length})

        with patch.dict(
            "sys.modules",
            {
                "pandas": fake_pandas,
                "statsforecast": fake_statsforecast,
                "statsforecast.models": fake_models,
            },
        ):
            projection = backend.forecast_series(
                [
                    {"date": "2026-03-28", "severity_score": 50},
                    {"date": "2026-03-29", "severity_score": 60},
                    {"date": "2026-03-30", "severity_score": 72},
                    {"date": "2026-03-31", "severity_score": 84},
                ],
                date_key="date",
                value_key="severity_score",
                horizon_days=14,
            )

        self.assertTrue(projection.fallback)
        self.assertEqual(projection.forecast_backend, "manual_trend")
        self.assertEqual(projection.model_name, "rule_based")
        self.assertEqual(projection.fallback_reason, "backend_runtime_error")

    def test_forecast_region_with_insufficient_history_uses_conservative_wording(self):
        class ShortHistoryRepo:
            def pest_trend(self, since, until, region_name, region_level="city"):
                return [{"date": "2026-03-31", "severity_score": 84}]

        service = ForecastService(ShortHistoryRepo())
        result = service.forecast_region(
            {
                "query_type": "pest_forecast",
                "since": "2026-03-01 00:00:00",
                "city": "徐州市",
                "region_level": "city",
                "forecast_window": {"horizon_days": 14},
            }
        )

        self.assertTrue(result["forecast"]["fallback"])
        self.assertEqual(result["forecast"]["history_points"], 1)
        self.assertEqual(result["forecast"]["evidence_strength"], "weak")
        self.assertIn("暂以保守预测为主", result["answer"])
        self.assertIn("样本覆盖 1 个观测日", result["answer"])
        self.assertIn("回退预测", result["answer"])

    def test_forecast_region_with_no_history_avoids_strong_prediction(self):
        class EmptyHistoryRepo:
            def pest_trend(self, since, until, region_name, region_level="city"):
                return []

        service = ForecastService(EmptyHistoryRepo())
        result = service.forecast_region(
            {
                "query_type": "pest_forecast",
                "since": "2026-03-01 00:00:00",
                "city": "徐州市",
                "region_level": "city",
                "forecast_window": {"horizon_days": 14},
            }
        )

        self.assertTrue(result["forecast"]["fallback"])
        self.assertEqual(result["forecast"]["history_points"], 0)
        self.assertEqual(result["forecast"]["evidence_strength"], "weak")
        self.assertIn("暂不做强预测", result["answer"])
        self.assertIn("样本覆盖 0 个观测日", result["answer"])

    def test_forecast_region_uses_contract_without_hasattr_discovery(self):
        with patch("doc_ai_agent.forecast_service.hasattr", side_effect=AssertionError("forecast_service hasattr should not be used"), create=True):
            result = self.service.forecast_region(
                {
                    "query_type": "pest_forecast",
                    "since": "2026-03-01 00:00:00",
                    "city": "徐州市",
                    "region_level": "city",
                    "forecast_window": {"horizon_days": 14},
                }
            )

        self.assertEqual(result["forecast"]["domain"], "pest")
        self.assertEqual(result["analysis_context"]["region_name"], "徐州市")

    def test_forecast_top_regions_uses_contract_without_hasattr_discovery(self):
        with patch("doc_ai_agent.forecast_service.hasattr", side_effect=AssertionError("forecast_service hasattr should not be used"), create=True):
            result = self.service.forecast_top_regions(
                domain="soil",
                since="2026-03-01 00:00:00",
                horizon_days=14,
                region_level="city",
                top_n=2,
            )

        self.assertEqual(result["forecast"]["domain"], "soil")
        self.assertEqual(len(result["data"]), 2)

    def test_forecast_top_regions_county_scope_uses_county_results(self):
        service = ForecastService(CountyForecastRepo())

        result = service.forecast_top_regions(
            domain="pest",
            since="2026-03-01 00:00:00",
            horizon_days=10,
            region_level="county",
            top_n=2,
            city="徐州市",
        )

        self.assertEqual(result["analysis_context"]["region_level"], "county")
        self.assertEqual(result["data"][0]["region_name"], "铜山区")
        self.assertIn("铜山区", result["answer"])
        self.assertNotIn("徐州市", result["answer"])

    def test_forecast_top_regions_preserves_low_soil_direction(self):
        service = ForecastService(CountyForecastRepo())

        result = service.forecast_top_regions(
            domain="soil",
            since="2026-03-01 00:00:00",
            horizon_days=7,
            region_level="county",
            top_n=1,
            city="南通市",
            anomaly_direction="low",
        )

        self.assertEqual(result["data"][0]["region_name"], "如东县")
        self.assertIn("低墒", result["answer"])
        self.assertNotIn("高墒风险最高", result["answer"])

    def test_forecast_top_regions_preserves_high_soil_direction(self):
        service = ForecastService(CountyForecastRepo())

        result = service.forecast_top_regions(
            domain="soil",
            since="2026-03-01 00:00:00",
            horizon_days=7,
            region_level="county",
            top_n=1,
            city="南通市",
            anomaly_direction="high",
        )

        self.assertEqual(result["data"][0]["region_name"], "启东市")
        self.assertIn("高墒", result["answer"])
        self.assertNotIn("低墒风险最高", result["answer"])

    def test_forecast_top_regions_weak_evidence_uses_conservative_wording(self):
        service = ForecastService(CountyForecastRepo())

        result = service.forecast_top_regions(
            domain="soil",
            since="2026-03-01 00:00:00",
            horizon_days=7,
            region_level="county",
            top_n=1,
            city="南通市",
            anomaly_direction="low",
        )

        self.assertEqual(result["forecast"]["eligibility"]["reason"], "insufficient_history")
        self.assertIn("暂以保守判断为主", result["answer"])
        self.assertIn("样本覆盖较弱", result["answer"])


if __name__ == "__main__":
    unittest.main()
