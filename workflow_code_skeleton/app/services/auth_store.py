from __future__ import annotations

import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from .runtime_paths import get_runtime_data_dir


USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{2,20}$")
COMMON_PASSWORDS = {
    "000000",
    "111111",
    "123123",
    "123456",
    "1234567",
    "12345678",
    "123456789",
    "1234567890",
    "abc123",
    "admin",
    "admin123",
    "iloveyou",
    "password",
    "password123",
    "qwerty",
    "qwerty123",
}


@dataclass(frozen=True, slots=True)
class UserAccount:
    id: int
    username: str
    created_at: str


def normalize_username(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def validate_username(username: str) -> str:
    if not username:
        return "请输入用户名"
    if not USERNAME_RE.match(username):
        return "用户名需为 2-20 位，可使用中文、字母、数字、下划线或短横线"
    return ""


def validate_password(password: str) -> str:
    value = str(password or "")
    if len(value) < 8:
        return "密码至少需要 8 位"
    normalized = value.strip().lower()
    if normalized in COMMON_PASSWORDS:
        return "这个密码过于常见，容易被浏览器标记为泄露，请换一个更独特的密码"
    has_letter = any(ch.isalpha() for ch in value)
    has_digit = any(ch.isdigit() for ch in value)
    if not has_letter or not has_digit:
        return "密码需要同时包含字母和数字，降低被误判为弱密码或泄露密码的概率"
    return ""


class AuthStore:
    def __init__(self) -> None:
        self.base_dir = get_runtime_data_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / "users.db"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _row_to_user(self, row: sqlite3.Row | None) -> UserAccount | None:
        if row is None:
            return None
        return UserAccount(
            id=int(row["id"]),
            username=str(row["username"]),
            created_at=str(row["created_at"]),
        )

    def get_user(self, user_id: int | None) -> UserAccount | None:
        if not user_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, created_at FROM users WHERE id = ?",
                (int(user_id),),
            ).fetchone()
        return self._row_to_user(row)

    def get_user_by_username(self, username: str) -> UserAccount | None:
        normalized = normalize_username(username)
        if not normalized:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, created_at FROM users WHERE username = ?",
                (normalized,),
            ).fetchone()
        return self._row_to_user(row)

    def register_user(self, username: str, password: str) -> UserAccount:
        normalized = normalize_username(username)
        username_error = validate_username(normalized)
        if username_error:
            raise ValueError(username_error)

        password_error = validate_password(password)
        if password_error:
            raise ValueError(password_error)

        created_at = datetime.now(timezone.utc).astimezone().isoformat()
        password_hash = generate_password_hash(str(password))
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO users (username, password_hash, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (normalized, password_hash, created_at),
                )
                conn.commit()
                user_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValueError("该用户名已被使用，请换一个用户名") from exc

        return UserAccount(id=user_id, username=normalized, created_at=created_at)

    def authenticate(self, username: str, password: str) -> UserAccount | None:
        normalized = normalize_username(username)
        if not normalized or not password:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, password_hash, created_at
                FROM users
                WHERE username = ?
                """,
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        if not check_password_hash(str(row["password_hash"]), str(password)):
            return None
        return self._row_to_user(row)

    def create_session_token(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        created_at = datetime.now(timezone.utc).astimezone().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_sessions (token, user_id, created_at)
                VALUES (?, ?, ?)
                """,
                (token, int(user_id), created_at),
            )
            conn.commit()
        return token

    def get_user_by_token(self, token: str | None) -> UserAccount | None:
        value = str(token or "").strip()
        if not value:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.id, u.username, u.created_at
                FROM auth_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token = ?
                """,
                (value,),
            ).fetchone()
        return self._row_to_user(row)

    def update_username(self, user_id: int, username: str) -> UserAccount:
        normalized = normalize_username(username)
        username_error = validate_username(normalized)
        if username_error:
            raise ValueError(username_error)
        with self._connect() as conn:
            current = conn.execute(
                "SELECT username FROM users WHERE id = ?",
                (int(user_id),),
            ).fetchone()
            if current is None:
                raise ValueError("用户不存在")
            if str(current["username"]) == normalized:
                return self.get_user(user_id)
            duplicate = conn.execute(
                "SELECT id FROM users WHERE username = ? AND id <> ?",
                (normalized, int(user_id)),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("该用户名已被使用，请换一个用户名")
            conn.execute(
                "UPDATE users SET username = ? WHERE id = ?",
                (normalized, int(user_id)),
            )
            conn.commit()
        user = self.get_user(user_id)
        if user is None:
            raise ValueError("用户不存在")
        return user

    def update_password(
        self,
        user_id: int,
        current_password: str,
        new_password: str,
    ) -> None:
        password_error = validate_password(new_password)
        if password_error:
            raise ValueError(password_error)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE id = ?",
                (int(user_id),),
            ).fetchone()
            if row is None:
                raise ValueError("用户不存在")
            if not check_password_hash(str(row["password_hash"]), str(current_password)):
                raise ValueError("当前密码不正确")
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(str(new_password)), int(user_id)),
            )
            conn.commit()


auth_store = AuthStore()
