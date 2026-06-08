from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = "data/payments.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS payment_tags (
    batch_no TEXT PRIMARY KEY,
    provider TEXT,
    tagged_for_payment TEXT DEFAULT '',
    processor_name TEXT DEFAULT '',
    target_payment_date TEXT DEFAULT '',
    tagged_date TEXT DEFAULT '',
    payment_priority TEXT DEFAULT '',
    payment_remarks TEXT DEFAULT '',
    approval_status TEXT DEFAULT '',
    released_status TEXT DEFAULT '',
    paid_status TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payment_tag_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_no TEXT NOT NULL,
    action TEXT NOT NULL,
    field_name TEXT,
    old_value TEXT,
    new_value TEXT,
    actor TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


EDITABLE_FIELDS = {
    "tagged_for_payment",
    "processor_name",
    "target_payment_date",
    "tagged_date",
    "payment_priority",
    "payment_remarks",
    "approval_status",
    "released_status",
    "paid_status",
}


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> Path:
    path = Path(db_path)
    with connect(path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    return path


def get_all_tags(db_path: str | Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM payment_tags ORDER BY updated_at DESC").fetchall()
    return [dict(row) for row in rows]


def get_tag(batch_no: str, db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM payment_tags WHERE batch_no = ?", (batch_no,)).fetchone()
    return dict(row) if row else None


def upsert_tag(batch_no: str, values: dict[str, Any], db_path: str | Path = DEFAULT_DB_PATH, actor: str = "") -> dict[str, Any]:
    if not batch_no:
        raise ValueError("batch_no is required")

    init_db(db_path)
    allowed = {key: str(value or "") for key, value in values.items() if key in EDITABLE_FIELDS or key == "provider"}
    provider = str(values.get("provider", "") or "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with connect(db_path) as conn:
        existing = conn.execute("SELECT * FROM payment_tags WHERE batch_no = ?", (batch_no,)).fetchone()
        if not existing:
            conn.execute(
                """
                INSERT INTO payment_tags (batch_no, provider, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (batch_no, provider, now, now),
            )
            existing = conn.execute("SELECT * FROM payment_tags WHERE batch_no = ?", (batch_no,)).fetchone()

        before = dict(existing)
        for field, new_value in allowed.items():
            if field == "provider":
                continue
            old_value = str(before.get(field, "") or "")
            if old_value != new_value:
                conn.execute(f"UPDATE payment_tags SET {field} = ?, updated_at = ? WHERE batch_no = ?", (new_value, now, batch_no))
                conn.execute(
                    """
                    INSERT INTO payment_tag_history (batch_no, action, field_name, old_value, new_value, actor, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (batch_no, "UPDATE_FIELD", field, old_value, new_value, actor, now),
                )
        if provider and provider != str(before.get("provider", "") or ""):
            conn.execute("UPDATE payment_tags SET provider = ?, updated_at = ? WHERE batch_no = ?", (provider, now, batch_no))
        conn.commit()
        row = conn.execute("SELECT * FROM payment_tags WHERE batch_no = ?", (batch_no,)).fetchone()
    return dict(row)


def delete_tag(batch_no: str, db_path: str | Path = DEFAULT_DB_PATH, actor: str = "") -> None:
    init_db(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect(db_path) as conn:
        conn.execute("DELETE FROM payment_tags WHERE batch_no = ?", (batch_no,))
        conn.execute(
            """
            INSERT INTO payment_tag_history (batch_no, action, actor, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (batch_no, "DELETE_TAG", actor, now),
        )
        conn.commit()


def get_history(batch_no: str | None = None, db_path: str | Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    init_db(db_path)
    with connect(db_path) as conn:
        if batch_no:
            rows = conn.execute("SELECT * FROM payment_tag_history WHERE batch_no = ? ORDER BY created_at DESC", (batch_no,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM payment_tag_history ORDER BY created_at DESC LIMIT 1000").fetchall()
    return [dict(row) for row in rows]
