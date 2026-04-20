import unittest

from doc_ai_agent.mysql_repository import MySQLRepository


class RecordingMySQLRepository(MySQLRepository):
    def __init__(self):
        super().__init__("mysql://tester:secret@127.0.0.1:3306/doc-cloud")
        self.calls = []
        self.outputs = []

    def _run_sql(self, sql: str, *, expect_output: bool = False) -> str:
        self.calls.append((sql, expect_output))
        if expect_output and self.outputs:
            return self.outputs.pop(0)
        return ""


class SoilAdminRepositoryTests(unittest.TestCase):
    def test_create_tables_contains_admin_audit_schema(self):
        repo = RecordingMySQLRepository()

        repo.create_tables()

        emitted_sql = "\n".join(call[0] for call in repo.calls)
        self.assertIn("CREATE TABLE IF NOT EXISTS admin_change_log", emitted_sql)
        self.assertIn("target_table", emitted_sql)
        self.assertIn("operator_username", emitted_sql)

    def test_admin_list_soil_records_is_paginated_and_filtered(self):
        repo = RecordingMySQLRepository()
        repo.outputs = ["123", '[{"record_id":"r1","device_sn":"SNS1"}]']

        result = repo.admin_list_soil_records(
            filters={"city_name": "徐州市", "device_sn": "SNS1", "soil_anomaly_type": "low"},
            page=3,
            page_size=50,
        )

        self.assertEqual(result["total"], 123)
        self.assertEqual(result["page"], 3)
        self.assertEqual(result["page_size"], 50)
        self.assertEqual(result["rows"], [{"record_id": "r1", "device_sn": "SNS1"}])
        emitted_sql = "\n".join(call[0] for call in repo.calls)
        self.assertIn("COUNT(*)", emitted_sql)
        self.assertIn("city_name = '徐州市'", emitted_sql)
        self.assertIn("device_sn = 'SNS1'", emitted_sql)
        self.assertIn("soil_anomaly_type = 'low'", emitted_sql)
        self.assertIn("LIMIT 50 OFFSET 100", emitted_sql)

    def test_admin_update_soil_field_rejects_non_whitelisted_field(self):
        repo = RecordingMySQLRepository()

        with self.assertRaises(ValueError):
            repo.admin_update_soil_field("r1", "record_id", "evil", {"username": "gago-1"})

        self.assertEqual(repo.calls, [])

    def test_admin_update_soil_field_records_old_and_new_value(self):
        repo = RecordingMySQLRepository()
        repo.outputs = ['{"record_id":"r1","city_name":"徐州市"}']

        result = repo.admin_update_soil_field("r1", "city_name", "南京市", {"username": "gago-1"})

        self.assertEqual(result["record_id"], "r1")
        self.assertEqual(result["field"], "city_name")
        self.assertEqual(result["old_value"], "徐州市")
        self.assertEqual(result["new_value"], "南京市")
        emitted_sql = "\n".join(call[0] for call in repo.calls)
        self.assertIn("UPDATE fact_soil_moisture", emitted_sql)
        self.assertIn("city_name = '南京市'", emitted_sql)
        self.assertIn("INSERT INTO admin_change_log", emitted_sql)
        self.assertIn("gago-1", emitted_sql)

    def test_admin_delete_soil_records_writes_audit_and_limits_to_ids(self):
        repo = RecordingMySQLRepository()
        repo.outputs = ['[{"record_id":"r1"},{"record_id":"r2"}]']

        result = repo.admin_delete_soil_records(["r1", "r2"], {"username": "gago-1"})

        self.assertEqual(result["deleted_count"], 2)
        emitted_sql = "\n".join(call[0] for call in repo.calls)
        self.assertIn("WHERE record_id IN ('r1', 'r2')", emitted_sql)
        self.assertIn("DELETE FROM fact_soil_moisture", emitted_sql)
        self.assertIn("INSERT INTO admin_change_log", emitted_sql)

    def test_incremental_insert_uses_insert_ignore_not_upsert(self):
        repo = RecordingMySQLRepository()

        inserted = repo.bulk_insert_soil_incremental([
            {
                "record_id": "r1",
                "batch_id": "b1",
                "device_sn": "SNS1",
                "source_file": "soil.xlsx",
                "source_sheet": "Sheet1",
                "source_row": 2,
            }
        ])

        self.assertEqual(inserted, 1)
        emitted_sql = "\n".join(call[0] for call in repo.calls)
        self.assertIn("INSERT IGNORE INTO fact_soil_moisture", emitted_sql)
        self.assertNotIn("ON DUPLICATE KEY UPDATE", emitted_sql)


if __name__ == "__main__":
    unittest.main()
