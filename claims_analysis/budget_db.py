from __future__ import annotations

import calendar
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "data/payments.db"
DEFAULT_MONTHLY_BUDGET = 65_000_000.0

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS budget_months (
    budget_month TEXT PRIMARY KEY,
    base_monthly_budget REAL DEFAULT 65000000,
    approved_additional_budget REAL DEFAULT 0,
    total_monthly_budget REAL DEFAULT 65000000,
    status TEXT DEFAULT 'ACTIVE',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS budget_weeks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_month TEXT NOT NULL,
    week_no INTEGER NOT NULL,
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    allocated_budget REAL DEFAULT 0,
    used_budget REAL DEFAULT 0,
    remaining_budget REAL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(budget_month, week_no)
);

CREATE TABLE IF NOT EXISTS weekly_budget_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_month TEXT NOT NULL,
    target_week_no INTEGER NOT NULL,
    additional_amount REAL NOT NULL,
    reason TEXT DEFAULT '',
    created_by TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS monthly_budget_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_month TEXT NOT NULL,
    current_monthly_budget REAL DEFAULT 0,
    requested_additional_amount REAL DEFAULT 0,
    requested_total_budget REAL DEFAULT 0,
    reason TEXT DEFAULT '',
    status TEXT DEFAULT 'PENDING',
    requested_by TEXT DEFAULT '',
    approved_by TEXT DEFAULT '',
    approval_remarks TEXT DEFAULT '',
    requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
    approved_at TEXT DEFAULT ''
);
"""


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_budget_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


def month_key_from_date(value: str | date | None = None) -> str:
    if value is None:
        d = date.today()
    elif isinstance(value, date):
        d = value
    else:
        d = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    return f"{d.year:04d}-{d.month:02d}"


def calendar_weeks_for_month(budget_month: str) -> list[tuple[int, date, date]]:
    year, month = [int(x) for x in budget_month.split("-")]
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    weeks: list[tuple[int, date, date]] = []
    current = first
    week_no = 1
    while current <= last:
        days_until_sunday = 6 - current.weekday()
        week_end = min(current + timedelta(days=days_until_sunday), last)
        weeks.append((week_no, current, week_end))
        current = week_end + timedelta(days=1)
        week_no += 1
    return weeks


def ensure_month(budget_month: str | None = None, db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    init_budget_db(db_path)
    budget_month = budget_month or month_key_from_date()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    weeks = calendar_weeks_for_month(budget_month)
    weekly_amount = DEFAULT_MONTHLY_BUDGET / len(weeks)
    with connect(db_path) as conn:
        month = conn.execute("SELECT * FROM budget_months WHERE budget_month = ?", (budget_month,)).fetchone()
        if not month:
            conn.execute(
                """
                INSERT INTO budget_months (budget_month, base_monthly_budget, approved_additional_budget, total_monthly_budget, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?, ?)
                """,
                (budget_month, DEFAULT_MONTHLY_BUDGET, DEFAULT_MONTHLY_BUDGET, now, now),
            )
            for week_no, week_start, week_end in weeks:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO budget_weeks (budget_month, week_no, week_start, week_end, allocated_budget, used_budget, remaining_budget, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                    """,
                    (budget_month, week_no, week_start.isoformat(), week_end.isoformat(), weekly_amount, weekly_amount, now, now),
                )
        conn.commit()
    refresh_week_usage(budget_month, db_path)
    return get_month_summary(budget_month, db_path)


def _claim_amount_expr() -> str:
    return "CAST(COALESCE(NULLIF(claims_amount,''),'0') AS REAL)"


def refresh_week_usage(budget_month: str, db_path: str | Path = DEFAULT_DB_PATH) -> None:
    init_budget_db(db_path)
    with connect(db_path) as conn:
        weeks = conn.execute("SELECT * FROM budget_weeks WHERE budget_month = ? ORDER BY week_no", (budget_month,)).fetchall()
        for week in weeks:
            used = conn.execute(
                f"""
                SELECT SUM({_claim_amount_expr()}) AS used_budget
                FROM payment_tags
                WHERE UPPER(COALESCE(payment_status,'')) = 'UNPAID'
                  AND COALESCE(target_payment_date,'') BETWEEN ? AND ?
                """,
                (week["week_start"], week["week_end"]),
            ).fetchone()["used_budget"] or 0
            remaining = float(week["allocated_budget"] or 0) - float(used or 0)
            conn.execute(
                "UPDATE budget_weeks SET used_budget = ?, remaining_budget = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (used, remaining, week["id"]),
            )
        conn.commit()


def get_month_summary(budget_month: str | None = None, db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    budget_month = budget_month or month_key_from_date()
    init_budget_db(db_path)
    refresh_week_usage(budget_month, db_path)
    with connect(db_path) as conn:
        month = conn.execute("SELECT * FROM budget_months WHERE budget_month = ?", (budget_month,)).fetchone()
        weeks = conn.execute("SELECT * FROM budget_weeks WHERE budget_month = ? ORDER BY week_no", (budget_month,)).fetchall()
        requests = conn.execute("SELECT * FROM monthly_budget_requests WHERE budget_month = ? ORDER BY requested_at DESC", (budget_month,)).fetchall()
    if not month:
        return ensure_month(budget_month, db_path)
    return {"month": dict(month), "weeks": [dict(row) for row in weeks], "requests": [dict(row) for row in requests]}


def request_weekly_additional_funds(budget_month: str, target_week_no: int, additional_amount: float, reason: str = "", created_by: str = "Claims Manager", db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    ensure_month(budget_month, db_path)
    additional_amount = float(additional_amount or 0)
    if additional_amount <= 0:
        raise ValueError("additional_amount must be greater than zero")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect(db_path) as conn:
        weeks = conn.execute("SELECT * FROM budget_weeks WHERE budget_month = ? ORDER BY week_no", (budget_month,)).fetchall()
        target = [w for w in weeks if int(w["week_no"]) == int(target_week_no)]
        remaining_weeks = [w for w in weeks if int(w["week_no"]) != int(target_week_no)]
        if not target:
            raise ValueError("Target week not found")
        if not remaining_weeks:
            raise ValueError("No other weeks available for reallocation")
        deduction_each = additional_amount / len(remaining_weeks)
        for week in remaining_weeks:
            new_alloc = float(week["allocated_budget"] or 0) - deduction_each
            if new_alloc < 0:
                raise ValueError("Additional amount is too high for even reallocation")
            conn.execute("UPDATE budget_weeks SET allocated_budget = ?, updated_at = ? WHERE id = ?", (new_alloc, now, week["id"]))
        target_week = target[0]
        conn.execute("UPDATE budget_weeks SET allocated_budget = ?, updated_at = ? WHERE id = ?", (float(target_week["allocated_budget"] or 0) + additional_amount, now, target_week["id"]))
        conn.execute(
            """
            INSERT INTO weekly_budget_adjustments (budget_month, target_week_no, additional_amount, reason, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (budget_month, target_week_no, additional_amount, reason, created_by, now),
        )
        conn.commit()
    refresh_week_usage(budget_month, db_path)
    return get_month_summary(budget_month, db_path)


def create_monthly_budget_request(budget_month: str, requested_additional_amount: float, reason: str = "", requested_by: str = "Claims Manager", db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    summary = ensure_month(budget_month, db_path)
    current = float(summary["month"]["total_monthly_budget"] or DEFAULT_MONTHLY_BUDGET)
    requested_additional_amount = float(requested_additional_amount or 0)
    if requested_additional_amount <= 0:
        raise ValueError("requested_additional_amount must be greater than zero")
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO monthly_budget_requests
            (budget_month, current_monthly_budget, requested_additional_amount, requested_total_budget, reason, status, requested_by)
            VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
            """,
            (budget_month, current, requested_additional_amount, current + requested_additional_amount, reason, requested_by),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM monthly_budget_requests ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row)


def approve_monthly_budget_request(request_id: int, approved_by: str = "Finance Manager", approval_remarks: str = "", db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    init_budget_db(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect(db_path) as conn:
        request = conn.execute("SELECT * FROM monthly_budget_requests WHERE id = ?", (request_id,)).fetchone()
        if not request:
            raise ValueError("Budget request not found")
        if request["status"] != "PENDING":
            raise ValueError("Only pending requests can be approved")
        month = conn.execute("SELECT * FROM budget_months WHERE budget_month = ?", (request["budget_month"],)).fetchone()
        additional = float(request["requested_additional_amount"] or 0)
        new_approved = float(month["approved_additional_budget"] or 0) + additional
        new_total = float(month["base_monthly_budget"] or DEFAULT_MONTHLY_BUDGET) + new_approved
        conn.execute("UPDATE budget_months SET approved_additional_budget = ?, total_monthly_budget = ?, updated_at = ? WHERE budget_month = ?", (new_approved, new_total, now, request["budget_month"]))
        weeks = conn.execute("SELECT * FROM budget_weeks WHERE budget_month = ? ORDER BY week_no", (request["budget_month"],)).fetchall()
        add_each = additional / len(weeks)
        for week in weeks:
            conn.execute("UPDATE budget_weeks SET allocated_budget = allocated_budget + ?, updated_at = ? WHERE id = ?", (add_each, now, week["id"]))
        conn.execute("UPDATE monthly_budget_requests SET status = 'APPROVED', approved_by = ?, approval_remarks = ?, approved_at = ? WHERE id = ?", (approved_by, approval_remarks, now, request_id))
        conn.commit()
    refresh_week_usage(request["budget_month"], db_path)
    return get_month_summary(request["budget_month"], db_path)


def reject_monthly_budget_request(request_id: int, approved_by: str = "Finance Manager", approval_remarks: str = "", db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    init_budget_db(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect(db_path) as conn:
        request = conn.execute("SELECT * FROM monthly_budget_requests WHERE id = ?", (request_id,)).fetchone()
        if not request:
            raise ValueError("Budget request not found")
        conn.execute("UPDATE monthly_budget_requests SET status = 'REJECTED', approved_by = ?, approval_remarks = ?, approved_at = ? WHERE id = ?", (approved_by, approval_remarks, now, request_id))
        conn.commit()
    return get_month_summary(request["budget_month"], db_path)
