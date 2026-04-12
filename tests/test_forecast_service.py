import unittest

from doc_ai_agent.forecast_service import ForecastService


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

    def top_pest_regions(self, since, until, region_level="city", top_n=5):
        return [
            {"region_name": "徐州市", "severity_score": 90, "record_count": 18, "active_days": 7},
            {"region_name": "淮安市", "severity_score": 75, "record_count": 14, "active_days": 6},
        ][:top_n]

    def top_soil_regions(self, since, until, region_level="city", top_n=5, anomaly_direction=None):
        return [
            {"region_name": "宿迁市", "anomaly_score": 88, "abnormal_count": 16, "low_count": 11, "high_count": 0},
            {"region_name": "盐城市", "anomaly_score": 73, "abnormal_count": 12, "low_count": 8, "high_count": 1},
        ][:top_n]


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
        self.assertEqual(result["forecast"]["forecast_backend"], "statsforecast")
        self.assertEqual(result["forecast"]["model_name"], "AutoETS")
        self.assertEqual(result["forecast"]["history_points"], 4)
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


if __name__ == "__main__":
    unittest.main()
