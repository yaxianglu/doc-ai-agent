from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Mapping


PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*_-+=."


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=bytes.fromhex(salt_value),
        n=2**14,
        r=8,
        p=1,
    )
    return digest.hex(), salt_value


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    candidate_hash, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate_hash, password_hash)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_strong_password(length: int = 20) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(max(16, length)))


def load_or_create_credentials(path: str, usernames: list[str]) -> dict[str, str]:
    if os.path.exists(path):
        credentials: dict[str, str] = {}
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw or raw.startswith("#") or ":" not in raw:
                    continue
                username, password = raw.split(":", 1)
                credentials[username.strip()] = password.strip()
        if credentials:
            return credentials

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    credentials = {username: generate_strong_password() for username in usernames}
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("# Initial doc-cloud auth credentials\n")
        for username, password in credentials.items():
            handle.write(f"{username}: {password}\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return credentials


class AuthRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
                """
            )

    def get_user_by_username(self, username: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, password_hash, password_salt, is_active, created_at, updated_at
                FROM users
                WHERE username = ?
                """,
                (username,),
            ).fetchone()
        return dict(row) if row else None

    def create_user(self, username: str, password_hash: str, password_salt: str) -> dict:
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (username, password_hash, password_salt, is_active, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (username, password_hash, password_salt, now, now),
            )
        user = self.get_user_by_username(username)
        if user is None:
            raise RuntimeError("user creation failed")
        return user

    def update_user_password(self, user_id: int, password_hash: str, password_salt: str) -> None:
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET password_hash = ?, password_salt = ?, updated_at = ?
                WHERE id = ?
                """,
                (password_hash, password_salt, now, user_id),
            )

    def create_session(self, user_id: int, token: str, expires_at: str) -> str:
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (user_id, token_hash, created_at, expires_at, last_used_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, hash_token(token), now, expires_at, now),
            )
        return token

    def get_user_by_token(self, token: str) -> dict | None:
        now = utc_now().isoformat()
        token_hash = hash_token(token)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.id, u.username, u.is_active, s.id AS session_id, s.expires_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = 1
                """,
                (token_hash, now),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE sessions SET last_used_at = ? WHERE id = ?",
                    (now, row["session_id"]),
                )
        return {"id": row["id"], "username": row["username"], "is_active": bool(row["is_active"])} if row else None

    def delete_session(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))


class AuthService:
    def __init__(self, repo: AuthRepository, session_ttl_days: int = 7):
        self.repo = repo
        self.session_ttl_days = max(1, session_ttl_days)

    def ensure_users(self, credentials: Mapping[str, str]) -> int:
        created = 0
        for username, password in credentials.items():
            existing = self.repo.get_user_by_username(username)
            if existing:
                if not verify_password(password, existing["password_hash"], existing["password_salt"]):
                    password_hash, salt = hash_password(password)
                    self.repo.update_user_password(int(existing["id"]), password_hash, salt)
                continue
            password_hash, salt = hash_password(password)
            self.repo.create_user(username, password_hash, salt)
            created += 1
        return created

    def login(self, username: str, password: str) -> dict | None:
        user = self.repo.get_user_by_username(username)
        if not user or not bool(user["is_active"]):
            return None
        if not verify_password(password, user["password_hash"], user["password_salt"]):
            return None
        token = secrets.token_urlsafe(32)
        expires_at = (utc_now() + timedelta(days=self.session_ttl_days)).isoformat()
        self.repo.create_session(int(user["id"]), token, expires_at)
        return {"token": token, "user": self._public_user(user), "expires_at": expires_at}

    def authenticate(self, token: str) -> dict | None:
        if not token:
            return None
        user = self.repo.get_user_by_token(token)
        if not user:
            return None
        return self._public_user(user)

    def logout(self, token: str) -> None:
        if token:
            self.repo.delete_session(token)

    @staticmethod
    def _public_user(user: Mapping[str, object]) -> dict:
        return {
            "id": int(user["id"]),
            "username": str(user["username"]),
        }
