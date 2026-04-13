import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from doc_ai_agent.auth import (
    AuthRepository,
    AuthService,
    hash_password,
    verify_password,
)


class AuthTests(unittest.TestCase):
    def test_hash_password_and_verify(self):
        password_hash, salt = hash_password("StrongPass!123")

        self.assertTrue(verify_password("StrongPass!123", password_hash, salt))
        self.assertFalse(verify_password("WrongPass!123", password_hash, salt))

    def test_bootstrap_users_are_created_once(self):
        with tempfile.TemporaryDirectory() as td:
            repo = AuthRepository(os.path.join(td, "auth.db"))
            repo.init_schema()
            service = AuthService(repo)

            created_first = service.ensure_users(
                {
                    "gago-1": "Pw1",
                    "gago-2": "Pw2",
                }
            )
            created_second = service.ensure_users(
                {
                    "gago-1": "Pw1",
                    "gago-2": "Pw2",
                }
            )

            self.assertEqual(created_first, 2)
            self.assertEqual(created_second, 0)
            self.assertIsNotNone(repo.get_user_by_username("gago-1"))
            self.assertIsNotNone(repo.get_user_by_username("gago-2"))

    def test_login_creates_session_and_authenticate_resolves_user(self):
        with tempfile.TemporaryDirectory() as td:
            repo = AuthRepository(os.path.join(td, "auth.db"))
            repo.init_schema()
            service = AuthService(repo)
            service.ensure_users({"gago-1": "StrongPass!123"})

            login = service.login("gago-1", "StrongPass!123")
            authenticated = service.authenticate(login["token"])

            self.assertEqual(login["user"]["username"], "gago-1")
            self.assertIsNotNone(authenticated)
            self.assertEqual(authenticated["username"], "gago-1")

    def test_login_returns_none_for_wrong_password(self):
        with tempfile.TemporaryDirectory() as td:
            repo = AuthRepository(os.path.join(td, "auth.db"))
            repo.init_schema()
            service = AuthService(repo)
            service.ensure_users({"gago-1": "StrongPass!123"})

            self.assertIsNone(service.login("gago-1", "WrongPass!123"))

    def test_logout_invalidates_session(self):
        with tempfile.TemporaryDirectory() as td:
            repo = AuthRepository(os.path.join(td, "auth.db"))
            repo.init_schema()
            service = AuthService(repo)
            service.ensure_users({"gago-1": "StrongPass!123"})

            login = service.login("gago-1", "StrongPass!123")
            self.assertIsNotNone(service.authenticate(login["token"]))

            service.logout(login["token"])

            self.assertIsNone(service.authenticate(login["token"]))

    def test_expired_session_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = AuthRepository(os.path.join(td, "auth.db"))
            repo.init_schema()
            service = AuthService(repo)
            service.ensure_users({"gago-1": "StrongPass!123"})
            user = repo.get_user_by_username("gago-1")
            token = repo.create_session(
                user_id=int(user["id"]),
                token="session-token",
                expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            )

            self.assertEqual(token, "session-token")
            self.assertIsNone(service.authenticate("session-token"))


if __name__ == "__main__":
    unittest.main()
