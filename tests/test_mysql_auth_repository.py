import json
import unittest

from doc_ai_agent.mysql_repository import MySQLRepository


class InspectableMySQLRepository(MySQLRepository):
    def __init__(self):
        super().__init__("mysql://tester:secret@127.0.0.1:3306/doc-cloud")
        self.calls: list[tuple[str, bool]] = []
        self.outputs: list[str] = []

    def queue_output(self, payload: object) -> None:
        if isinstance(payload, str):
            self.outputs.append(payload)
            return
        self.outputs.append(json.dumps(payload, ensure_ascii=False))

    def _run_sql(self, sql: str, *, expect_output: bool = False) -> str:
        self.calls.append((sql, expect_output))
        if expect_output:
            return self.outputs.pop(0) if self.outputs else ""
        return ""


class MySQLAuthRepositoryTests(unittest.TestCase):
    def test_create_tables_contains_auth_schema(self):
        repo = InspectableMySQLRepository()

        repo.create_tables()

        emitted_sql = "\n".join(sql for sql, _ in repo.calls)
        self.assertIn("CREATE TABLE IF NOT EXISTS auth_user", emitted_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS auth_session", emitted_sql)

    def test_get_user_by_username_reads_from_auth_user(self):
        repo = InspectableMySQLRepository()
        repo.queue_output(
            {
                "id": 1,
                "username": "gago-1",
                "password_hash": "hash",
                "password_salt": "salt",
                "is_active": 1,
            }
        )

        user = repo.get_user_by_username("gago-1")

        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "gago-1")
        self.assertIn("FROM auth_user", repo.calls[0][0])

    def test_get_user_by_token_reads_from_auth_session_and_updates_last_used(self):
        repo = InspectableMySQLRepository()
        repo.queue_output(
            {
                "id": 1,
                "username": "gago-1",
                "is_active": 1,
                "session_id": 7,
            }
        )

        user = repo.get_user_by_token("plain-token")

        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "gago-1")
        self.assertIn("FROM auth_session s", repo.calls[0][0])
        self.assertIn("UPDATE auth_session SET last_used_at", repo.calls[1][0])

    def test_create_and_delete_session_target_auth_session(self):
        repo = InspectableMySQLRepository()

        token = repo.create_session(5, "plain-token", "2026-04-22T00:00:00+00:00")
        repo.delete_session("plain-token")

        self.assertEqual(token, "plain-token")
        self.assertIn("INSERT INTO auth_session", repo.calls[0][0])
        self.assertIn("DELETE FROM auth_session", repo.calls[1][0])


if __name__ == "__main__":
    unittest.main()
