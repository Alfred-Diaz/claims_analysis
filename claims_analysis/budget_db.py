from __future__ import annotations

import calendar
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "data/payments.db"
DEFAULT_MONTHLY_BUDGET = 83_000_000.0

DEFAULT_POOLS = [
    ("MEDICAL", "MAIN", "Medical", 65_000_000.0),
    ("REIMBURSEMENT", "MAIN", "Reimbursement", 3_000_000.0),
    ("DENTAL", "MAIN", "Dental", 3_000_000.0),
    ("PAMPANGA", "PAMPANGA", "Budget Pampanga", 12_000_000.0),
]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS budget_months (
    budget_month TEXT PRIMARY KEY,
    base_monthly_budget REAL DEFAULT 83000000,
    approved_additional_budget REAL DEFAULT 0,
    total_monthly_budget REAL DEFAULT 83000000,
    status TEXT DEFAULT 'ACTIVE',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS budget_pools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_month TEXT NOT NULL,
    pool_code TEXT NOT NULL,
    pool_group TEXT NOT NULL,
    pool_name TEXT NOT NULL,
    base_monthly_budget REAL DEFAULT 0,
    approved_additional_budget REAL DEFAULT 0,
    total_monthly_budget REAL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(budget_month, pool_code)
);
CREATE TABLE IF NOT EXISTS budget_weeks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_month TEXT NOT NULL,
    pool_code TEXT DEFAULT 'MEDICAL',
    week_no INTEGER NOT NULL,
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    allocated_budget REAL DEFAULT 0,
    used_budget REAL DEFAULT 0,
    remaining_budget REAL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(budget_month, pool_code, week_no)
);
CREATE TABLE IF NOT EXISTS weekly_budget_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_month TEXT NOT NULL,
    pool_code TEXT DEFAULT 'MEDICAL',
    target_week_no INTEGER NOT NULL,
    additional_amount REAL NOT NULL,
    reason TEXT DEFAULT '',
    created_by TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS monthly_budget_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_month TEXT NOT NULL,
    pool_code TEXT DEFAULT 'MEDICAL',
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


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _migrate_budget_weeks_unique_constraint(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='budget_weeks'").fetchone()
    if not row or not row["sql"]:
        return
    sql = row["sql"].replace("\n", " ").replace("  ", " ").upper()
    if "UNIQUE(BUDGET_MONTH, POOL_CODE, WEEK_NO)" in sql or "UNIQUE (BUDGET_MONTH, POOL_CODE, WEEK_NO)" in sql:
        return

    conn.execute("ALTER TABLE budget_weeks RENAME TO budget_weeks_old")
    conn.execute(
        """
        CREATE TABLE budget_weeks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            budget_month TEXT NOT NULL,
            pool_code TEXT DEFAULT 'MEDICAL',
            week_no INTEGER NOT NULL,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            allocated_budget REAL DEFAULT 0,
            used_budget REAL DEFAULT 0,
            remaining_budget REAL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(budget_month, pool_code, week_no)
        )
        """
    )
    old_cols = {row["name"] for row in conn.execute("PRAGMA table_info(budget_weeks_old)").fetchall()}
    pool_expr = "COALESCE(NULLIF(pool_code,''),'MEDICAL')" if "pool_code" in old_cols else "'MEDICAL'"
    conn.execute(
        f"""
        INSERT OR IGNORE INTO budget_weeks
        (budget_month, pool_code, week_no, week_start, week_end, allocated_budget, used_budget, remaining_budget, created_at, updated_at)
        SELECT budget_month,
               {pool_expr},
               week_no,
               week_start,
               week_end,
               allocated_budget,
               used_budget,
               remaining_budget,
               COALESCE(created_at, CURRENT_TIMESTAMP),
               COALESCE(updated_at, CURRENT_TIMESTAMP)
        FROM budget_weeks_old
        """
    )
    conn.execute("DROP TABLE budget_weeks_old")


def init_budget_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        _ensure_column(conn, "budget_weeks", "pool_code", "pool_code TEXT DEFAULT 'MEDICAL'")
        _migrate_budget_weeks_unique_constraint(conn)
        _ensure_column(conn, "weekly_budget_adjustments", "pool_code", "pool_code TEXT DEFAULT 'MEDICAL'")
        _ensure_column(conn, "monthly_budget_requests", "pool_code", "pool_code TEXT DEFAULT 'MEDICAL'")
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
    last_day = calendar.monthrange(year, month)[1]
    ranges = [(1, 7), (8, 14), (15, 21), (22, last_day)]
    return [(i + 1, date(year, month, start), date(year, month, end)) for i, (start, end) in enumerate(ranges)]


def _claim_amount_expr() -> str:
    return "CAST(COALESCE(NULLIF(claims_amount,''),'0') AS REAL)"


def pool_for_claim_sql() -> str:
    return """
    CASE
      WHEN UPPER(COALESCE(region,'')) LIKE '%PAMPANGA%' THEN 'PAMPANGA'
      WHEN UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%DENTAL%'
        OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%DENTIST%' THEN 'DENTAL'
      WHEN UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%REIMBURSE%' THEN 'REIMBURSEMENT'
      ELSE 'MEDICAL'
    END
    """


def _ensure_month_row(conn: sqlite3.Connection, budget_month: str, now: str) -> None:
    row = conn.execute("SELECT * FROM budget_months WHERE budget_month = ?", (budget_month,)).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO budget_months (budget_month, base_monthly_budget, approved_additional_budget, total_monthly_budget, created_at, updated_at) VALUES (?, ?, 0, ?, ?, ?)",
            (budget_month, DEFAULT_MONTHLY_BUDGET, DEFAULT_MONTHLY_BUDGET, now, now),
        )
    else:
        pool_total = conn.execute("SELECT SUM(total_monthly_budget) AS v FROM budget_pools WHERE budget_month = ?", (budget_month,)).fetchone()["v"]
        if pool_total:
            approved = conn.execute("SELECT SUM(approved_additional_budget) AS v FROM budget_pools WHERE budget_month = ?", (budget_month,)).fetchone()["v"] or 0
            base = conn.execute("SELECT SUM(base_monthly_budget) AS v FROM budget_pools WHERE budget_month = ?", (budget_month,)).fetchone()["v"] or 0
            conn.execute("UPDATE budget_months SET base_monthly_budget = ?, approved_additional_budget = ?, total_monthly_budget = ?, updated_at = ? WHERE budget_month = ?", (base, approved, pool_total, now, budget_month))


def _ensure_pools(conn: sqlite3.Connection, budget_month: str, now: str) -> None:
    for code, group, name, base in DEFAULT_POOLS:
        row = conn.execute("SELECT * FROM budget_pools WHERE budget_month = ? AND pool_code = ?", (budget_month, code)).fetchone()
        if not row:
            conn.execute(
                """
                INSERT INTO budget_pools (budget_month, pool_code, pool_group, pool_name, base_monthly_budget, approved_additional_budget, total_monthly_budget, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (budget_month, code, group, name, base, base, now, now),
            )


def _ensure_weeks(conn: sqlite3.Connection, budget_month: str, pool_code: str, total_budget: float, now: str) -> None:
    existing = conn.execute("SELECT COUNT(*) AS c FROM budget_weeks WHERE budget_month = ? AND pool_code = ?", (budget_month, pool_code)).fetchone()["c"]
    if existing == 4:
        return
    conn.execute("DELETE FROM budget_weeks WHERE budget_month = ? AND pool_code = ?", (budget_month, pool_code))
    weekly_amount = total_budget / 4
    for week_no, week_start, week_end in calendar_weeks_for_month(budget_month):
        conn.execute(
            """
            INSERT INTO budget_weeks (budget_month, pool_code, week_no, week_start, week_end, allocated_budget, used_budget, remaining_budget, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (budget_month, pool_code, week_no, week_start.isoformat(), week_end.isoformat(), weekly_amount, weekly_amount, now, now),
        )


def ensure_month(budget_month: str | None = None, db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    init_budget_db(db_path)
    budget_month = budget_month or month_key_from_date()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect(db_path) as conn:
        _ensure_month_row(conn, budget_month, now)
        _ensure_pools(conn, budget_month, now)
        pools = conn.execute("SELECT * FROM budget_pools WHERE budget_month = ?", (budget_month,)).fetchall()
        for pool in pools:
            _ensure_weeks(conn, budget_month, pool["pool_code"], float(pool["total_monthly_budget"] or 0), now)
        _ensure_month_row(conn, budget_month, now)
        conn.commit()
    refresh_week_usage(budget_month, db_path)
    return get_month_summary(budget_month, db_path)


def refresh_week_usage(budget_month: str, db_path: str | Path = DEFAULT_DB_PATH) -> None:
    init_budget_db(db_path)
    with connect(db_path) as conn:
        weeks = conn.execute("SELECT * FROM budget_weeks WHERE budget_month = ? ORDER BY pool_code, week_no", (budget_month,)).fetchall()
        for week in weeks:
            used = conn.execute(
                f"""
                SELECT SUM({_claim_amount_expr()}) AS used_budget
                FROM payment_tags
                WHERE UPPER(COALESCE(payment_status,'')) = 'UNPAID'
                  AND COALESCE(target_payment_date,'') BETWEEN ? AND ?
                  AND ({pool_for_claim_sql()}) = ?
                """,
                (week["week_start"], week["week_end"], week["pool_code"]),
            ).fetchone()["used_budget"] or 0
            remaining = float(week["allocated_budget"] or 0) - float(used or 0)
            conn.execute("UPDATE budget_weeks SET used_budget = ?, remaining_budget = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (used, remaining, week["id"]))
        conn.commit()


def get_month_summary(budget_month: str | None = None, db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    budget_month = budget_month or month_key_from_date()
    init_budget_db(db_path)
    with connect(db_path) as conn:
        month = conn.execute("SELECT * FROM budget_months WHERE budget_month = ?", (budget_month,)).fetchone()
        if not month:
            return ensure_month(budget_month, db_path)
    refresh_week_usage(budget_month, db_path)
    with connect(db_path) as conn:
        month = conn.execute("SELECT * FROM budget_months WHERE budget_month = ?", (budget_month,)).fetchone()
        pools = conn.execute("SELECT * FROM budget_pools WHERE budget_month = ? ORDER BY CASE pool_code WHEN 'MEDICAL' THEN 1 WHEN 'REIMBURSEMENT' THEN 2 WHEN 'DENTAL' THEN 3 WHEN 'PAMPANGA' THEN 4 ELSE 9 END", (budget_month,)).fetchall()
        weeks = conn.execute("SELECT * FROM budget_weeks WHERE budget_month = ? ORDER BY pool_code, week_no", (budget_month,)).fetchall()
        requests = conn.execute("SELECT * FROM monthly_budget_requests WHERE budget_month = ? ORDER BY requested_at DESC", (budget_month,)).fetchall()
    pool_list = [dict(row) for row in pools]
    week_list = [dict(row) for row in weeks]
    for pool in pool_list:
        pool["weeks"] = [w for w in week_list if w.get("pool_code") == pool["pool_code"]]
        pool["used_budget"] = sum(float(w.get("used_budget") or 0) for w in pool["weeks"])
        pool["remaining_budget"] = sum(float(w.get("remaining_budget") or 0) for w in pool["weeks"])
    return {"month": dict(month), "pools": pool_list, "weeks": week_list, "requests": [dict(row) for row in requests]}


def request_weekly_additional_funds(budget_month: str, target_week_no: int, additional_amount: float, reason: str = "", created_by: str = "Claims Manager", db_path: str | Path = DEFAULT_DB_PATH, pool_code: str = "MEDICAL") -> dict[str, Any]:
    ensure_month(budget_month, db_path)
    pool_code = (pool_code or "MEDICAL").upper()
    additional_amount = float(additional_amount or 0)
    if additional_amount <= 0:
        raise ValueError("additional_amount must be greater than zero")
    if int(target_week_no) not in {1, 2, 3, 4}:
        raise ValueError("Week number must be 1, 2, 3, or 4")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect(db_path) as conn:
        weeks = conn.execute("SELECT * FROM budget_weeks WHERE budget_month = ? AND pool_code = ? ORDER BY week_no", (budget_month, pool_code)).fetchall()
        if len(weeks) != 4:
            raise ValueError("Budget pool weeks not found")
        target = [w for w in weeks if int(w["week_no"]) == int(target_week_no)][0]
        other_weeks = [w for w in weeks if int(w["week_no"]) != int(target_week_no)]
        deduction_each = additional_amount / len(other_weeks)
        for week in other_weeks:
            new_alloc = float(week["allocated_budget"] or 0) - deduction_each
            if new_alloc < 0:
                raise ValueError("Additional amount is too high for even reallocation")
            conn.execute("UPDATE budget_weeks SET allocated_budget = ?, updated_at = ? WHERE id = ?", (new_alloc, now, week["id"]))
        conn.execute("UPDATE budget_weeks SET allocated_budget = ?, updated_at = ? WHERE id = ?", (float(target["allocated_budget"] or 0) + additional_amount, now, target["id"]))
        conn.execute("INSERT INTO weekly_budget_adjustments (budget_month, pool_code, target_week_no, additional_amount, reason, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (budget_month, pool_code, target_week_no, additional_amount, reason, created_by, now))
        conn.commit()
    refresh_week_usage(budget_month, db_path)
    return get_month_summary(budget_month, db_path)


def create_monthly_budget_request(budget_month: str, requested_additional_amount: float, reason: str = "", requested_by: str = "Claims Manager", db_path: str | Path = DEFAULT_DB_PATH, pool_code: str = "MEDICAL") -> dict[str, Any]:
    summary = ensure_month(budget_month, db_path)
    pool_code = (pool_code or "MEDICAL").upper()
    pool = next((p for p in summary["pools"] if p["pool_code"] == pool_code), None)
    if not pool:
        raise ValueError("Budget pool not found")
    current = float(pool["total_monthly_budget"] or 0)
    requested_additional_amount = float(requested_additional_amount or 0)
    if requested_additional_amount <= 0:
        raise ValueError("requested_additional_amount must be greater than zero")
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO monthly_budget_requests
            (budget_month, pool_code, current_monthly_budget, requested_additional_amount, requested_total_budget, reason, status, requested_by)
            VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)
            """,
            (budget_month, pool_code, current, requested_additional_amount, current + requested_additional_amount, reason, requested_by),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM monthly_budget_requests ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row)


def approve_monthly_budget_request(request_id: int, approved_by: str = "Finance Manager", approval_remarks: str = "", db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    init_budget_db(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect(db_path) as conn:
        req = conn.execute("SELECT * FROM monthly_budget_requests WHERE id = ?", (request_id,)).fetchone()
        if not req:
            raise ValueError("Budget request not found")
        if req["status"] != "PENDING":
            raise ValueError("Only pending requests can be approved")
        pool_code = req["pool_code"] or "MEDICAL"
        pool = conn.execute("SELECT * FROM budget_pools WHERE budget_month = ? AND pool_code = ?", (req["budget_month"], pool_code)).fetchone()
        if not pool:
            raise ValueError("Budget pool not found")
        additional = float(req["requested_additional_amount"] or 0)
        new_approved = float(pool["approved_additional_budget"] or 0) + additional
        new_total = float(pool["base_monthly_budget"] or 0) + new_approved
        conn.execute("UPDATE budget_pools SET approved_additional_budget = ?, total_monthly_budget = ?, updated_at = ? WHERE id = ?", (new_approved, new_total, now, pool["id"]))
        conn.execute("UPDATE budget_weeks SET allocated_budget = allocated_budget + ?, updated_at = ? WHERE budget_month = ? AND pool_code = ?", (additional / 4, now, req["budget_month"], pool_code))
        conn.execute("UPDATE monthly_budget_requests SET status = 'APPROVED', approved_by = ?, approval_remarks = ?, approved_at = ? WHERE id = ?", (approved_by, approval_remarks, now, request_id))
        conn.commit()
    return ensure_month(req["budget_month"], db_path)


def reject_monthly_budget_request(request_id: int, approved_by: str = "Finance Manager", approval_remarks: str = "", db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    init_budget_db(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect(db_path) as conn:
        req = conn.execute("SELECT * FROM monthly_budget_requests WHERE id = ?", (request_id,)).fetchone()
        if not req:
            raise ValueError("Budget request not found")
        conn.execute("UPDATE monthly_budget_requests SET status = 'REJECTED', approved_by = ?, approval_remarks = ?, approved_at = ? WHERE id = ?", (approved_by, approval_remarks, now, request_id))
        conn.commit()
    return get_month_summary(req["budget_month"], db_path)
