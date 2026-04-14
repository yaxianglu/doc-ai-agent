import unittest

from doc_ai_agent.query_engine import QueryEngine


class FakeAlertRepo:
    def __init__(self):
        self.last_pest_top_kwargs = {}
        self.last_soil_top_kwargs = {}

    def top_pest_regions(self, since, until=None, region_level="city", top_n=5, city=None, county=None):
        self.last_pest_top_kwargs = {
            "since": since,
            "until": until,
            "region_level": region_level,
            "top_n": top_n,
            "city": city,
            "county": county,
        }
        return [
            {
                "region_name": "溧阳市",
                "severity_score": 9,
                "record_count": 3,
                "active_days": 2,
            }
        ][:top_n]

    def top_soil_regions(self, since, until=None, region_level="city", top_n=5, anomaly_direction=None, city=None, county=None):
        self.last_soil_top_kwargs = {
            "since": since,
            "until": until,
            "region_level": region_level,
            "top_n": top_n,
            "anomaly_direction": anomaly_direction,
            "city": city,
            "county": county,
        }
        return [
            {
                "region_name": "常熟市",
                "anomaly_score": 7,
                "abnormal_count": 4,
                "low_count": 1,
                "high_count": 3,
            }
        ][:top_n]

    def sample_pest_records(self, since, until, limit=3):
        return []

    def sample_soil_records(self, since, until, limit=3):
        return []

    def top_active_devices(self, since, until=None, limit=10):
        return [
            {
                "device_code": "SNS001",
                "device_name": "设备1",
                "alert_count": 5,
                "active_days": 3,
                "last_alert_time": "2026-04-13 10:00:00",
            },
            {
                "device_code": "SNS002",
                "device_name": "设备2",
                "alert_count": 4,
                "active_days": 2,
                "last_alert_time": "2026-04-12 10:00:00",
            },
        ][:limit]

    def unknown_region_devices(self, limit=20):
        return [
            {
                "device_code": "SNS009",
                "device_name": "未知设备",
                "alert_count": 3,
                "last_alert_time": "2026-04-12 08:00:00",
            }
        ][:limit]

    def empty_county_records(self, limit=20):
        return [
            {
                "alert_time": "2026-04-12 08:00:00",
                "city": "",
                "county": "",
                "region_name": "",
                "device_code": "SNS009",
                "device_name": "未知设备",
                "alert_level": "重旱",
            }
        ][:limit]

    def unmatched_region_records(self, limit=20):
        return [
            {
                "alert_time": "2026-04-12 08:00:00",
                "city": "",
                "county": "",
                "region_name": "",
                "device_code": "SNS009",
                "device_name": "未知设备",
                "alert_level": "重旱",
            }
        ][:limit]


class TrendRepo(FakeAlertRepo):
    def pest_trend(self, since, until, region_name, region_level="city"):
        return [
            {"date": "2026-03-28", "severity_score": 58},
            {"date": "2026-03-29", "severity_score": 64},
            {"date": "2026-03-30", "severity_score": 70},
            {"date": "2026-03-31", "severity_score": 78},
            {"date": "2026-04-01", "severity_score": 86},
        ]

    def soil_trend(self, since, until, region_name, region_level="city"):
        return [
            {"date": "2026-03-28", "avg_anomaly_score": 45},
            {"date": "2026-03-29", "avg_anomaly_score": 56},
            {"date": "2026-03-30", "avg_anomaly_score": 70},
            {"date": "2026-03-31", "avg_anomaly_score": 81},
        ]


class EmptyTrendRepo(TrendRepo):
    def available_pest_time_range(self):
        return {
            "min_time": "2026-01-05 00:00:00",
            "max_time": "2026-04-08 00:00:00",
        }

    def pest_trend(self, since, until, region_name, region_level="city"):
        return []

    def available_soil_time_range(self, anomaly_direction=None):
        return {
            "min_time": "2026-01-07 00:00:00",
            "max_time": "2026-04-09 00:00:00",
        }

    def soil_trend(self, since, until, region_name, region_level="city"):
        return []


class QueryEngineTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeAlertRepo()
        self.engine = QueryEngine(self.repo)

    def test_active_devices_answer_lists_top_devices(self):
        result = self.engine.answer(
            "给我列出最近最活跃的10台设备。",
            plan={"query_type": "active_devices", "top_n": 10, "since": "1970-01-01 00:00:00"},
        )

        self.assertIn("最活跃的Top10台设备", result.answer)
        self.assertIn("SNS001", result.answer)
        self.assertEqual(result.data[0]["device_code"], "SNS001")

    def test_unknown_region_devices_answer_lists_devices(self):
        result = self.engine.answer(
            "未知区域对应的是哪些设备？",
            plan={"query_type": "unknown_region_devices", "since": "1970-01-01 00:00:00"},
        )

        self.assertIn("未知区域对应的设备", result.answer)
        self.assertIn("SNS009", result.answer)

    def test_empty_county_records_answer_mentions_county_field(self):
        result = self.engine.answer(
            "哪些记录的县字段为空？",
            plan={"query_type": "empty_county_records", "since": "1970-01-01 00:00:00"},
        )

        self.assertIn("县字段为空", result.answer)
        self.assertNotIn("sms_content", result.answer)

    def test_unmatched_region_records_answer_mentions_region_match(self):
        result = self.engine.answer(
            "哪些数据没有匹配到区域？",
            plan={"query_type": "unmatched_region_records", "since": "1970-01-01 00:00:00"},
        )

        self.assertIn("没有匹配到区域", result.answer)
        self.assertIn("SNS009", result.answer)

    def test_pest_top_passes_city_scope_filter_to_repo(self):
        self.engine.answer(
            "常州市下面虫情最严重的县有哪些？",
            plan={
                "query_type": "pest_top",
                "since": "2025-11-14 00:00:00",
                "region_level": "county",
                "city": "常州市",
                "county": None,
                "top_n": 5,
            },
        )

        self.assertEqual(self.repo.last_pest_top_kwargs["city"], "常州市")
        self.assertEqual(self.repo.last_pest_top_kwargs["region_level"], "county")

    def test_soil_top_passes_city_scope_filter_to_repo(self):
        self.engine.answer(
            "苏州市下面墒情异常最多的县有哪些？",
            plan={
                "query_type": "soil_top",
                "since": "2025-11-14 00:00:00",
                "region_level": "county",
                "city": "苏州市",
                "county": None,
                "top_n": 5,
            },
        )

        self.assertEqual(self.repo.last_soil_top_kwargs["city"], "苏州市")
        self.assertEqual(self.repo.last_soil_top_kwargs["region_level"], "county")

    def test_soil_top_treats_piandi_as_low_anomaly_direction(self):
        result = self.engine.answer(
            "对墒情偏低最严重的区域应该怎么处理？",
            plan={
                "query_type": "soil_top",
                "since": "2025-11-14 00:00:00",
                "region_level": "city",
                "city": None,
                "county": None,
                "top_n": 5,
            },
        )

        self.assertEqual(self.repo.last_soil_top_kwargs["anomaly_direction"], "low")
        self.assertIn("低墒", result.answer)

    def test_pest_top_can_answer_city_then_county_breakdown(self):
        result = self.engine.answer(
            "江苏范围内，虫情最高的是哪些市？再细到县。",
            plan={
                "query_type": "pest_top",
                "since": "1970-01-01 00:00:00",
                "region_level": "county",
                "city": None,
                "county": None,
                "top_n": 5,
            },
        )

        self.assertIn("Top", result.answer)
        self.assertIn("市为", result.answer)
        self.assertIn("再细到县", result.answer)
        self.assertIn("区县", result.answer)

    def test_pest_trend_answers_direction_with_metrics(self):
        engine = QueryEngine(TrendRepo())

        result = engine.answer(
            "过去5个月虫情总体是上升还是下降？",
            plan={"query_type": "pest_trend", "since": "2025-11-14 00:00:00"},
        )

        self.assertIn("虫情趋势：整体上升", result.answer)
        self.assertIn("起点", result.answer)
        self.assertIn("最近", result.answer)
        self.assertIn("峰值", result.answer)
        self.assertIn("共覆盖5个观测日", result.answer)

    def test_soil_trend_answers_relief_question_with_clear_judgment(self):
        engine = QueryEngine(TrendRepo())

        result = engine.answer(
            "近两个月墒情有没有缓解？",
            plan={"query_type": "soil_trend", "since": "2026-02-14 00:00:00"},
        )

        self.assertIn("墒情趋势：整体上升", result.answer)
        self.assertIn("暂未缓解", result.answer)
        self.assertIn("起点", result.answer)
        self.assertIn("最近", result.answer)
        self.assertIn("峰值", result.answer)

    def test_pest_trend_no_data_answer_includes_reason_range_and_retry(self):
        engine = QueryEngine(EmptyTrendRepo())

        result = engine.answer(
            "南京近三周虫害走势怎么样？",
            plan={
                "query_type": "pest_trend",
                "since": "2026-03-20 00:00:00",
                "city": "南京市",
                "region_level": "city",
            },
        )

        self.assertIn("暂无可用虫情趋势数据", result.answer)
        self.assertIn("原因：南京市在当前时间窗内暂无虫情监测数据样本", result.answer)
        self.assertIn("当前可用虫情监测数据范围为 2026-01-05 至 2026-04-08", result.answer)
        self.assertIn("建议：先去掉南京市", result.answer)
        self.assertNotIn("1970-01-01", result.answer)


if __name__ == "__main__":
    unittest.main()
