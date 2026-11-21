"""Users and server-side sessions in SQLite.

Session tokens are random 256-bit values. Only their SHA-256 is stored, so a
leaked database does not hand out live sessions.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import secrets
import sqlite3
from dataclasses import dataclass
from threading import Lock

from app.auth.passwords import DUMMY_HASH, hash_password, verify_password

ROLES = ("admin", "reviewer", "viewer")
SESSION_HOURS = 8


@dataclass(frozen=True)
class User:
    id: int
    email: str
    role: str


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


class UserStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get("AEGIS_USERS_DB_PATH", "users.db")
        self._lock = Lock()
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, check_same_thread=False)
        db.row_factory = sqlite3.Row
        return db

    # ------------------------------------------------------------ users
    def create_user(self, email: str, password: str, role: str) -> User:
        if role not in ROLES:
            raise ValueError(f"role must be one of {', '.join(ROLES)}")
        email = normalize_email(email)
        with self._lock, self._connect() as db:
            cur = db.execute(
                "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                (email, hash_password(password), role, _now().isoformat()),
            )
            return User(cur.lastrowid, email, role)

    def set_password(self, email: str, password: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE users SET password_hash = ? WHERE email = ?",
                       (hash_password(password), normalize_email(email)))
            db.execute("DELETE FROM sessions WHERE user_id = "
                       "(SELECT id FROM users WHERE email = ?)", (normalize_email(email),))

    def delete_user(self, email: str) -> bool:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT id FROM users WHERE email = ?", (normalize_email(email),)).fetchone()
            if row is None:
                return False
            db.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
            db.execute("DELETE FROM users WHERE id = ?", (row["id"],))
            return True

    def get(self, email: str) -> User | None:
        with self._connect() as db:
            row = db.execute("SELECT id, email, role FROM users WHERE email = ? AND disabled = 0",
                             (normalize_email(email),)).fetchone()
        return User(row["id"], row["email"], row["role"]) if row else None

    def list_users(self) -> list[User]:
        with self._connect() as db:
            rows = db.execute("SELECT id, email, role FROM users WHERE disabled = 0 ORDER BY id").fetchall()
        return [User(r["id"], r["email"], r["role"]) for r in rows]

    def authenticate(self, email: str, password: str) -> User | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT id, email, role, password_hash FROM users WHERE email = ? AND disabled = 0",
                (normalize_email(email),),
            ).fetchone()
        if row is None:
            verify_password(password, DUMMY_HASH)  # same cost as a real check
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        return User(row["id"], row["email"], row["role"])

    # --------------------------------------------------------- sessions
    def create_session(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        now = _now()
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))
            db.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (_token_hash(token), user.id, now.isoformat(),
                 (now + dt.timedelta(hours=SESSION_HOURS)).isoformat()),
            )
        return token

    def session_user(self, token: str) -> User | None:
        if not token:
            return None
        with self._connect() as db:
            row = db.execute(
                "SELECT u.id, u.email, u.role, s.expires_at FROM sessions s "
                "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND u.disabled = 0",
                (_token_hash(token),),
            ).fetchone()
        if row is None or row["expires_at"] < _now().isoformat():
            return None
        return User(row["id"], row["email"], row["role"])

    def delete_session(self, token: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
