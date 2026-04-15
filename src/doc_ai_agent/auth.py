"""认证与会话管理模块。

本模块提供三层能力：
- 密码与令牌的安全处理（哈希、校验、生成）
- 基于内存或数据库仓储的用户/会话存储
- 面向业务调用的认证服务（登录、鉴权、登出）
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Mapping, Protocol


PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*_-+=."
FIXED_BOOTSTRAP_CREDENTIALS = {
    "gago-1": "2aZ8gx-pbXQsxXv4Mf9Q",
    "gago-2": "F_jGYw8BMhF@j&*bgp_A",
    "gago-3": "2A4Qt7miqT!xsnSv5gV2",
    "gago-4": "%@5#=vgP=v%mb9LzK$Nh",
    "gago-5": "3*u8a4ph.Z&x+4gP5XvF",
}


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


def fixed_bootstrap_credentials() -> dict[str, str]:
    """返回固定的系统种子账号，避免启动时随机改密。"""
    return dict(FIXED_BOOTSTRAP_CREDENTIALS)


class AuthRepositoryLike(Protocol):
    def get_user_by_username(self, username: str) -> dict | None: ...
    def create_user(self, username: str, password_hash: str, password_salt: str) -> dict: ...
    def update_user_password(self, user_id: int, password_hash: str, password_salt: str) -> None: ...
    def create_session(self, user_id: int, token: str, expires_at: str) -> str: ...
    def get_user_by_token(self, token: str) -> dict | None: ...
    def delete_session(self, token: str) -> None: ...


class MemoryAuthRepository:
    def __init__(self):
        self._users: dict[int, dict] = {}
        self._user_index: dict[str, int] = {}
        self._sessions: dict[str, dict] = {}
        self._next_user_id = 1
        self._next_session_id = 1

    def get_user_by_username(self, username: str) -> dict | None:
        user_id = self._user_index.get(username)
        if user_id is None:
            return None
        return dict(self._users[user_id])

    def create_user(self, username: str, password_hash: str, password_salt: str) -> dict:
        now = utc_now().isoformat()
        user = {
            "id": self._next_user_id,
            "username": username,
            "password_hash": password_hash,
            "password_salt": password_salt,
            "is_active": 1,
            "created_at": now,
            "updated_at": now,
        }
        self._users[self._next_user_id] = user
        self._user_index[username] = self._next_user_id
        self._next_user_id += 1
        return dict(user)

    def update_user_password(self, user_id: int, password_hash: str, password_salt: str) -> None:
        user = self._users[user_id]
        user["password_hash"] = password_hash
        user["password_salt"] = password_salt
        user["updated_at"] = utc_now().isoformat()

    def create_session(self, user_id: int, token: str, expires_at: str) -> str:
        token_hash = hash_token(token)
        now = utc_now().isoformat()
        self._sessions[token_hash] = {
            "id": self._next_session_id,
            "user_id": user_id,
            "expires_at": expires_at,
            "last_used_at": now,
        }
        self._next_session_id += 1
        return token

    def get_user_by_token(self, token: str) -> dict | None:
        token_hash = hash_token(token)
        session = self._sessions.get(token_hash)
        if session is None:
            return None
        if session["expires_at"] <= utc_now().isoformat():
            return None
        user = self._users.get(int(session["user_id"]))
        if user is None or not bool(user["is_active"]):
            return None
        session["last_used_at"] = utc_now().isoformat()
        return {"id": user["id"], "username": user["username"], "is_active": bool(user["is_active"])}

    def delete_session(self, token: str) -> None:
        self._sessions.pop(hash_token(token), None)


class AuthService:
    """认证服务层：封装用户初始化、登录态生成与鉴权逻辑。"""

    def __init__(self, repo: AuthRepositoryLike, session_ttl_days: int = 7):
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
