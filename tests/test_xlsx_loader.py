import os
import unittest

from doc_ai_agent.xlsx_loader import load_alerts_from_xlsx


class XlsxLoaderTests(unittest.TestCase):
    def test_load_alerts(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(repo_root, "处置建议发布任务.xlsx")
        rows = load_alerts_from_xlsx(path)
        self.assertGreater(len(rows), 0)

        first = rows[0]
        required = {
            "alert_content",
            "alert_type",
            "alert_subtype",
            "alert_time",
            "alert_level",
            "region_code",
            "region_name",
            "alert_value",
            "device_code",
            "device_name",
            "longitude",
            "latitude",
            "city",
            "county",
            "sms_content",
            "disposal_suggestion",
            "source_file",
            "source_sheet",
            "source_row",
        }
        self.assertTrue(required.issubset(set(first.keys())))


if __name__ == "__main__":
    unittest.main()
