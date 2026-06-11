from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from claims_analysis.payment_db import DEFAULT_DB_PATH

DEFAULT_USERS = [
    ("admin", "admin123", "Administrator", "Admin"),
    ("claims", "claims123", "Claims Manager", "Claims Manager"),
    ("finance", "finance123", "Finance Manager", "Finance Manager"),
]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL,
    active INTEGER DEFAULT 1,
    force_password_reset INTEGER DEFAULT 0,
    last_login TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_status TEXT NOT NULL,
    message TEXT DEFAULT '',
    ip_address TEXT DEFAULT '',
    user_agent TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()


def make_password_hash(password: str) -> tuple[str, str]:
    salt = os.urandom(16).hex()
    return _hash_password(password, salt), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    return _hash_password(password, salt) == password_hash


def init_auth_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        for username, password, full_name, role in DEFAULT_USERS:
            existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if existing:
                continue
            password_hash, salt = make_password_hash(password)
            conn.execute(
                """
                INSERT INTO users (username, password_hash, salt, full_name, role, active, force_password_reset)
                VALUES (?, ?, ?, ?, ?, 1, 0)
                """,
                (username, password_hash, salt, full_name, role),
            )
        conn.commit()


def audit_auth_event(username: str, event_type: str, event_status: str, message: str = "", ip_address: str = "", user_agent: str = "", db_path: str | Path = DEFAULT_DB_PATH) -> None:
    init_auth_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO auth_audit_log (username, event_type, event_status, message, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, event_type, event_status, message, ip_address, user_agent),
        )
        conn.commit()


def authenticate_user(username: str, password: str, ip_address: str = "", user_agent: str = "", db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    init_auth_db(db_path)
    username = (username or "").strip().lower()
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            audit_auth_event(username, "LOGIN", "FAILED", "Unknown username", ip_address, user_agent, db_path)
            return None
        user = dict(row)
        if not int(user.get("active") or 0):
            audit_auth_event(username, "LOGIN", "FAILED", "Inactive user", ip_address, user_agent, db_path)
            return None
        if not verify_password(password or "", user["password_hash"], user["salt"]):
            audit_auth_event(username, "LOGIN", "FAILED", "Invalid password", ip_address, user_agent, db_path)
            return None
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE users SET last_login = ?, updated_at = ? WHERE id = ?", (now, now, user["id"]))
        conn.commit()
    audit_auth_event(username, "LOGIN", "SUCCESS", "Login successful", ip_address, user_agent, db_path)
    return {
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "force_password_reset": bool(user.get("force_password_reset")),
    }


def list_users(db_path: str | Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    init_auth_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, username, full_name, role, active, force_password_reset, last_login, created_at, updated_at
            FROM users
            ORDER BY username
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_auth_audit(limit: int = 200, db_path: str | Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    init_auth_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT username, event_type, event_status, message, ip_address, user_agent, created_at
            FROM auth_audit_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]
