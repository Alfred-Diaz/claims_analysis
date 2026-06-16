from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/payments.db")
LARGE_STAGING_DB_PATH = Path("data/large_staging.db")


def log(message: str) -> None:
    print(f"[system_update] {message}")


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return column in {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if table_exists(conn, table) and not column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        log(f"Added column {table}.{column}")


def backup_db() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"payments_backup_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    log(f"Backup created: {backup_path}")


def migrate_budget_weeks(conn: sqlite3.Connection) -> None:
    if not table_exists(conn, "budget_weeks"):
        return
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='budget_weeks'").fetchone()
    sql = (row[0] or "").replace("\n", " ").upper() if row else ""
    has_new_unique = "UNIQUE(BUDGET_MONTH, POOL_CODE, WEEK_NO)" in sql or "UNIQUE (BUDGET_MONTH, POOL_CODE, WEEK_NO)" in sql
    if has_new_unique:
        log("budget_weeks unique constraint already updated")
        return

    log("Migrating budget_weeks unique constraint")
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
    old_cols = {row[1] for row in conn.execute("PRAGMA table_info(budget_weeks_old)").fetchall()}
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
    log("budget_weeks migration complete")


def ensure_payment_defaults(conn: sqlite3.Connection) -> None:
    if not table_exists(conn, "payment_tags"):
        log("payment_tags table not found; skipping payment defaults")
        return

    required_cols = [
        ("payment_status", "payment_status TEXT DEFAULT ''"),
        ("target_payment_date", "target_payment_date TEXT DEFAULT ''"),
        ("tagged_for_payment", "tagged_for_payment TEXT DEFAULT ''"),
        ("payment_priority", "payment_priority TEXT DEFAULT ''"),
        ("approval_status", "approval_status TEXT DEFAULT ''"),
        ("payment_remarks", "payment_remarks TEXT DEFAULT ''"),
        ("tagged_date", "tagged_date TEXT DEFAULT ''"),
    ]
    for column, ddl in required_cols:
        ensure_column(conn, "payment_tags", column, ddl)

    cur = conn.execute(
        """
        UPDATE payment_tags
        SET payment_status = 'UNPAID'
        WHERE payment_status IS NULL
           OR TRIM(payment_status) = ''
        """
    )
    log(f"payment_status blanks set to UNPAID: {cur.rowcount}")


def run_budget_initialization() -> None:
    try:
        from claims_analysis.budget_db import ensure_month, month_key_from_date

        summary = ensure_month(month_key_from_date(), DB_PATH)
        pools = len(summary.get("pools", []))
        weeks = len(summary.get("weeks", []))
        log(f"Budget initialized: {pools} pools, {weeks} weeks")
    except Exception as exc:
        log(f"Budget initialization failed: {exc}")
        raise


def verify_counts(conn: sqlite3.Connection) -> None:
    log("Verification report:")
    for table in ["payment_tags", "budget_months", "budget_pools", "budget_weeks", "monthly_budget_requests"]:
        if table_exists(conn, table):
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            log(f"  {table}: {count}")
        else:
            log(f"  {table}: missing")

    if LARGE_STAGING_DB_PATH.exists():
        with sqlite3.connect(LARGE_STAGING_DB_PATH) as stg:
            for table in ["stg_claims", "stg_checks"]:
                if table_exists(stg, table):
                    count = stg.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    log(f"  large_staging.{table}: {count}")
                else:
                    log(f"  large_staging.{table}: missing")


def main() -> None:
    log("Starting system-wide update")
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Cannot continue. Missing database: {DB_PATH}")

    backup_db()

    with sqlite3.connect(DB_PATH) as conn:
        migrate_budget_weeks(conn)
        ensure_payment_defaults(conn)
        conn.commit()

    run_budget_initialization()

    with sqlite3.connect(DB_PATH) as conn:
        verify_counts(conn)

    log("System update completed successfully")
    log("Next command: python .\\run_claims_portal.py")


if __name__ == "__main__":
    main()
