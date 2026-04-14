"""认证与会话管理模块。

本模块提供三层能力：
- 密码与令牌的安全处理（哈希、校验、生成）
- 基于 SQLite 的用户/会话存储
- 面向业务调用的认证服务（登录、鉴权、登出）
"""

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
    """返回带时区的 UTC 当前时间，避免时区歧义。"""
    return datetime.now(timezone.utc)


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """使用 scrypt 对密码做哈希，返回 `(hash_hex, salt_hex)`。"""
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
    """校验明文密码是否与已存储哈希匹配。"""
    candidate_hash, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate_hash, password_hash)


def hash_token(token: str) -> str:
    """对会话令牌做 SHA-256 哈希，避免在数据库落明文令牌。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_strong_password(length: int = 20) -> str:
    """生成强随机密码，最小长度固定为 16。"""
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(max(16, length)))


def load_or_create_credentials(path: str, usernames: list[str]) -> dict[str, str]:
    """读取或初始化账号密码文件，返回 `{username: password}` 映射。"""
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
        # 尽量收紧文件权限，降低凭据泄露风险（跨平台失败时忽略）。
        os.chmod(path, 0o600)
    except OSError:
        pass
    return credentials


class AuthRepository:
    """认证数据访问层：负责 users / sessions 表的读写。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """创建 SQLite 连接并启用按列名访问。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """初始化认证相关数据表。"""
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
        """按用户名查询用户，查无则返回 `None`。"""
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
        """创建用户并返回新用户信息。"""
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
        """更新指定用户密码哈希与盐值。"""
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
        """创建登录会话；数据库仅保存 token 哈希。"""
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
        """通过令牌查找会话对应用户，并刷新会话最近使用时间。"""
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
        """按令牌删除会话（用于登出）。"""
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))


class AuthService:
    """认证服务层：封装用户初始化、登录态生成与鉴权逻辑。"""

    def __init__(self, repo: AuthRepository, session_ttl_days: int = 7):
        self.repo = repo
        self.session_ttl_days = max(1, session_ttl_days)

    def ensure_users(self, credentials: Mapping[str, str]) -> int:
        """按给定凭据确保用户存在；返回新建用户数。"""
        created = 0
        for username, password in credentials.items():
            existing = self.repo.get_user_by_username(username)
            if existing:
                # 用户已存在但初始密码变化时，执行密码同步。
                if not verify_password(password, existing["password_hash"], existing["password_salt"]):
                    password_hash, salt = hash_password(password)
                    self.repo.update_user_password(int(existing["id"]), password_hash, salt)
                continue
            password_hash, salt = hash_password(password)
            self.repo.create_user(username, password_hash, salt)
            created += 1
        return created

    def login(self, username: str, password: str) -> dict | None:
        """用户名密码登录成功后返回令牌和过期时间。"""
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
        """校验会话令牌，成功时返回公开用户信息。"""
        if not token:
            return None
        user = self.repo.get_user_by_token(token)
        if not user:
            return None
        return self._public_user(user)

    def logout(self, token: str) -> None:
        """注销会话。"""
        if token:
            self.repo.delete_session(token)

    @staticmethod
    def _public_user(user: Mapping[str, object]) -> dict:
        """筛选可返回给前端的最小用户字段。"""
        return {
            "id": int(user["id"]),
            "username": str(user["username"]),
        }
