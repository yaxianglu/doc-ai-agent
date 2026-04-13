import os
import tempfile
import unittest

from doc_ai_agent.repository import AlertRepository


class RepositoryTests(unittest.TestCase):
    def test_count_and_top_city(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "alerts.db")
            repo = AlertRepository(db)
            repo.init_schema()
            repo.insert_alerts(
                [
                    {
                        "alert_content": "a",
                        "alert_type": "墒情预警",
                        "alert_subtype": "土壤",
                        "alert_time": "2026-01-02 00:00:00",
                        "alert_level": "重旱",
                        "region_code": "1",
                        "region_name": "x",
                        "alert_value": "10",
                        "device_code": "d1",
                        "device_name": "n1",
                        "longitude": "1",
                        "latitude": "2",
                        "city": "淮安市",
                        "county": "A",
                        "sms_content": "",
                        "disposal_suggestion": "",
                        "source_file": "f.xlsx",
                        "source_sheet": "sheet1",
                        "source_row": 2,
                    },
                    {
                        "alert_content": "b",
                        "alert_type": "墒情预警",
                        "alert_subtype": "土壤",
                        "alert_time": "2026-01-03 00:00:00",
                        "alert_level": "重旱",
                        "region_code": "2",
                        "region_name": "x",
                        "alert_value": "11",
                        "device_code": "d2",
                        "device_name": "n2",
                        "longitude": "1",
                        "latitude": "2",
                        "city": "淮安市",
                        "county": "B",
                        "sms_content": "",
                        "disposal_suggestion": "",
                        "source_file": "f.xlsx",
                        "source_sheet": "sheet1",
                        "source_row": 3,
                    },
                    {
                        "alert_content": "c",
                        "alert_type": "虫情预警",
                        "alert_subtype": "虫情",
                        "alert_time": "2026-02-03 00:00:00",
                        "alert_level": "中",
                        "region_code": "3",
                        "region_name": "x",
                        "alert_value": "12",
                        "device_code": "d3",
                        "device_name": "n3",
                        "longitude": "1",
                        "latitude": "2",
                        "city": "徐州市",
                        "county": "C",
                        "sms_content": "",
                        "disposal_suggestion": "",
                        "source_file": "f.xlsx",
                        "source_sheet": "sheet1",
                        "source_row": 4,
                    },
                ]
            )
            self.assertEqual(repo.count_since("2026-01-01 00:00:00"), 3)
            top = repo.top_n("city", 5, "2026-01-01 00:00:00")
            self.assertEqual(top[0]["name"], "淮安市")
            self.assertEqual(top[0]["count"], 2)
            samples = repo.sample_alerts("2026-01-01 00:00:00", 2)
            self.assertEqual(len(samples), 2)
            self.assertIn("alert_content", samples[0])

    def test_available_alert_time_range(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "alerts.db")
            repo = AlertRepository(db)
            repo.init_schema()
            repo.insert_alerts(
                [
                    {
                        "alert_content": "a",
                        "alert_type": "墒情预警",
                        "alert_subtype": "土壤",
                        "alert_time": "2026-01-02 00:00:00",
                        "alert_level": "重旱",
                        "region_code": "1",
                        "region_name": "x",
                        "alert_value": "10",
                        "device_code": "d1",
                        "device_name": "n1",
                        "longitude": "1",
                        "latitude": "2",
                        "city": "淮安市",
                        "county": "A",
                        "sms_content": "",
                        "disposal_suggestion": "",
                        "source_file": "f.xlsx",
                        "source_sheet": "sheet1",
                        "source_row": 2,
                    },
                    {
                        "alert_content": "b",
                        "alert_type": "虫情预警",
                        "alert_subtype": "虫情",
                        "alert_time": "2026-02-03 00:00:00",
                        "alert_level": "中",
                        "region_code": "2",
                        "region_name": "x",
                        "alert_value": "12",
                        "device_code": "d2",
                        "device_name": "n2",
                        "longitude": "1",
                        "latitude": "2",
                        "city": "徐州市",
                        "county": "B",
                        "sms_content": "",
                        "disposal_suggestion": "",
                        "source_file": "f.xlsx",
                        "source_sheet": "sheet1",
                        "source_row": 3,
                    },
                ]
            )

            time_range = repo.available_alert_time_range()
            self.assertEqual(
                time_range,
                {"min_time": "2026-01-02 00:00:00", "max_time": "2026-02-03 00:00:00"},
            )

    def test_avg_by_level_and_consecutive_devices(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "alerts.db")
            repo = AlertRepository(db)
            repo.init_schema()
            repo.insert_alerts(
                [
                    {
                        "alert_content": "a",
                        "alert_type": "墒情预警",
                        "alert_subtype": "土壤",
                        "alert_time": "2026-01-02 00:00:00",
                        "alert_level": "重旱",
                        "region_code": "1",
                        "region_name": "x",
                        "alert_value": "10",
                        "device_code": "d1",
                        "device_name": "n1",
                        "longitude": "1",
                        "latitude": "2",
                        "city": "淮安市",
                        "county": "A",
                        "sms_content": "",
                        "disposal_suggestion": "",
                        "source_file": "f.xlsx",
                        "source_sheet": "sheet1",
                        "source_row": 2,
                    },
                    {
                        "alert_content": "b",
                        "alert_type": "墒情预警",
                        "alert_subtype": "土壤",
                        "alert_time": "2026-01-03 00:00:00",
                        "alert_level": "重旱",
                        "region_code": "2",
                        "region_name": "x",
                        "alert_value": "20",
                        "device_code": "d2",
                        "device_name": "n2",
                        "longitude": "1",
                        "latitude": "2",
                        "city": "淮安市",
                        "county": "B",
                        "sms_content": "",
                        "disposal_suggestion": "",
                        "source_file": "f.xlsx",
                        "source_sheet": "sheet1",
                        "source_row": 3,
                    },
                    {
                        "alert_content": "c",
                        "alert_type": "墒情预警",
                        "alert_subtype": "土壤",
                        "alert_time": "2026-01-03 08:00:00",
                        "alert_level": "涝渍",
                        "region_code": "3",
                        "region_name": "x",
                        "alert_value": "30",
                        "device_code": "d1",
                        "device_name": "n1",
                        "longitude": "1",
                        "latitude": "2",
                        "city": "徐州市",
                        "county": "C",
                        "sms_content": "",
                        "disposal_suggestion": "",
                        "source_file": "f.xlsx",
                        "source_sheet": "sheet1",
                        "source_row": 4,
                    },
                ]
            )

            avg_rows = repo.avg_alert_value_by_level("2026-01-01 00:00:00")
            self.assertEqual(avg_rows[0]["level"], "涝渍")
            self.assertEqual(avg_rows[0]["avg_alert_value"], 30.0)
            self.assertEqual(avg_rows[1]["level"], "重旱")
            self.assertEqual(avg_rows[1]["avg_alert_value"], 15.0)

            devices = repo.devices_triggered_on_multiple_days("2026-01-01 00:00:00", min_days=2)
            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0]["device_code"], "d1")
            self.assertEqual(devices[0]["active_days"], 2)

    def test_device_activity_and_unmatched_region_queries(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "alerts.db")
            repo = AlertRepository(db)
            repo.init_schema()
            repo.insert_alerts(
                [
                    {
                        "alert_content": "a",
                        "alert_type": "墒情预警",
                        "alert_subtype": "土壤",
                        "alert_time": "2026-01-02 00:00:00",
                        "alert_level": "重旱",
                        "region_code": "1",
                        "region_name": "x",
                        "alert_value": "10",
                        "device_code": "d1",
                        "device_name": "n1",
                        "longitude": "1",
                        "latitude": "2",
                        "city": "淮安市",
                        "county": "A",
                        "sms_content": "",
                        "disposal_suggestion": "",
                        "source_file": "f.xlsx",
                        "source_sheet": "sheet1",
                        "source_row": 2,
                    },
                    {
                        "alert_content": "b",
                        "alert_type": "墒情预警",
                        "alert_subtype": "土壤",
                        "alert_time": "2026-01-03 00:00:00",
                        "alert_level": "重旱",
                        "region_code": "2",
                        "region_name": "x",
                        "alert_value": "20",
                        "device_code": "d1",
                        "device_name": "n1",
                        "longitude": "1",
                        "latitude": "2",
                        "city": "淮安市",
                        "county": "A",
                        "sms_content": "",
                        "disposal_suggestion": "",
                        "source_file": "f.xlsx",
                        "source_sheet": "sheet1",
                        "source_row": 3,
                    },
                    {
                        "alert_content": "c",
                        "alert_type": "虫情预警",
                        "alert_subtype": "虫情",
                        "alert_time": "2026-01-04 00:00:00",
                        "alert_level": "中",
                        "region_code": "3",
                        "region_name": "",
                        "alert_value": "30",
                        "device_code": "d2",
                        "device_name": "n2",
                        "longitude": "1",
                        "latitude": "2",
                        "city": "",
                        "county": "",
                        "sms_content": "",
                        "disposal_suggestion": "",
                        "source_file": "f.xlsx",
                        "source_sheet": "sheet1",
                        "source_row": 4,
                    },
                    {
                        "alert_content": "d",
                        "alert_type": "虫情预警",
                        "alert_subtype": "虫情",
                        "alert_time": "2026-01-05 00:00:00",
                        "alert_level": "中",
                        "region_code": "4",
                        "region_name": "",
                        "alert_value": "40",
                        "device_code": "d3",
                        "device_name": "n3",
                        "longitude": "1",
                        "latitude": "2",
                        "city": "",
                        "county": None,
                        "sms_content": "ok",
                        "disposal_suggestion": "",
                        "source_file": "f.xlsx",
                        "source_sheet": "sheet1",
                        "source_row": 5,
                    },
                ]
            )

            activity = repo.top_active_devices("1970-01-01 00:00:00", limit=2)
            self.assertEqual(activity[0]["device_code"], "d1")
            self.assertEqual(activity[0]["alert_count"], 2)

            unknown_devices = repo.unknown_region_devices(limit=5)
            self.assertEqual({row["device_code"] for row in unknown_devices}, {"d2", "d3"})

            empty_county = repo.empty_county_records(limit=5)
            self.assertEqual(len(empty_county), 2)

            unmatched = repo.unmatched_region_records(limit=5)
            self.assertEqual(len(unmatched), 2)


if __name__ == "__main__":
    unittest.main()
