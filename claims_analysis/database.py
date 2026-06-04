"""SQLite data warehouse layer for Claims Analysis.

Stores every analysis run and its output so operations can search history,
build dashboards, and audit old ERP exports without reopening raw CSV files.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import pandas as pd


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_folder TEXT NOT NULL,
    run_timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    claims_file TEXT,
    checks_file TEXT,
    total_batches INTEGER DEFAULT 0,
    total_amount REAL DEFAULT 0,
    hospital_count INTEGER DEFAULT 0,
    professional_count INTEGER DEFAULT 0,
    for_review_count INTEGER DEFAULT 0,
    unmatched_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS claims_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    batch_no TEXT,
    provider TEXT,
    total_amount_per_batch REAL,
    cv_no TEXT,
    check_no TEXT,
    supplier_category_name TEXT,
    check_date TEXT,
    payee_match_status TEXT,
    FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id)
);

CREATE TABLE IF NOT EXISTS exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    exception_type TEXT NOT NULL,
    batch_no TEXT,
    provider TEXT,
    details TEXT,
    FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id)
);

CREATE TABLE IF NOT EXISTS duplicate_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    check_no TEXT,
    duplicate_count INTEGER,
    FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id)
);

CREATE TABLE IF NOT EXISTS duplicate_cv (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    cv_no TEXT,
    duplicate_count INTEGER,
    FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_claims_batches_batch_no ON claims_batches(batch_no);
CREATE INDEX IF NOT EXISTS idx_claims_batches_provider ON claims_batches(provider);
CREATE INDEX IF NOT EXISTS idx_claims_batches_status ON claims_batches(payee_match_status);
CREATE INDEX IF NOT EXISTS idx_exceptions_run_type ON exceptions(run_id, exception_type);
"""


def connect(db_path: str | Path = "data/claims_analysis.db") -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database(db_path: str | Path = "data/claims_analysis.db") -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path, dtype=str).fillna("")
    return pd.DataFrame()


def save_run_to_database(
    run_dir: str | Path,
    claims_file: str | Path | None = None,
    checks_file: str | Path | None = None,
    db_path: str | Path = "data/claims_analysis.db",
) -> int:
    """Persist generated report files from a run folder into SQLite."""
    initialize_database(db_path)
    run_path = Path(run_dir)

    results = _read_csv_if_exists(run_path / "claims_analysis_output.csv")
    summary = _read_csv_if_exists(run_path / "summary.csv")
    for_review = _read_csv_if_exists(run_path / "for_review.csv")
    unmatched = _read_csv_if_exists(run_path / "unmatched_batches.csv")
    duplicate_checks = _read_csv_if_exists(run_path / "duplicate_checks.csv")
    duplicate_cv = _read_csv_if_exists(run_path / "duplicate_cv.csv")

    summary_map = {}
    if not summary.empty and {"metric", "value"}.issubset(summary.columns):
        summary_map = dict(zip(summary["metric"], summary["value"]))

    def metric_number(name: str) -> float:
        try:
            return float(summary_map.get(name, 0) or 0)
        except ValueError:
            return 0

    with connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO analysis_runs (
                run_folder,
                claims_file,
                checks_file,
                total_batches,
                total_amount,
                hospital_count,
                professional_count,
                for_review_count,
                unmatched_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(run_path),
                str(claims_file or ""),
                str(checks_file or ""),
                int(metric_number("total_batches")),
                metric_number("total_amount"),
                int(metric_number("hospital_count")),
                int(metric_number("professional_count")),
                int(metric_number("for_review_payees")),
                int(metric_number("unmatched_batches")),
            ),
        )
        run_id = int(cursor.lastrowid)

        if not results.empty:
            rows = []
            for _, row in results.iterrows():
                rows.append(
                    (
                        run_id,
                        row.get("batch_no", ""),
                        row.get("provider", ""),
                        float(row.get("total_amount_per_batch", 0) or 0),
                        row.get("cv_no", ""),
                        row.get("check_no", ""),
                        row.get("supplier_category_name", ""),
                        row.get("check_date", ""),
                        row.get("payee_match_status", ""),
                    )
                )
            cursor.executemany(
                """
                INSERT INTO claims_batches (
                    run_id, batch_no, provider, total_amount_per_batch, cv_no,
                    check_no, supplier_category_name, check_date, payee_match_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        exception_rows = []
        for _, row in for_review.iterrows():
            exception_rows.append(
                (
                    run_id,
                    "PAYEE_FOR_REVIEW",
                    row.get("batch_no", ""),
                    row.get("provider", ""),
                    "payable_to and payee_name require review",
                )
            )
        for _, row in unmatched.iterrows():
            exception_rows.append(
                (
                    run_id,
                    "UNMATCHED_BATCH",
                    row.get("batch_no", ""),
                    row.get("provider", ""),
                    "batch_no from Claims Process has no matching check record",
                )
            )

        if exception_rows:
            cursor.executemany(
                """
                INSERT INTO exceptions (run_id, exception_type, batch_no, provider, details)
                VALUES (?, ?, ?, ?, ?)
                """,
                exception_rows,
            )

        if not duplicate_checks.empty and "check_no" in duplicate_checks.columns:
            cursor.executemany(
                "INSERT INTO duplicate_checks (run_id, check_no, duplicate_count) VALUES (?, ?, ?)",
                [
                    (run_id, row.get("check_no", ""), int(float(row.get("count", 0) or 0)))
                    for _, row in duplicate_checks.iterrows()
                ],
            )

        if not duplicate_cv.empty and "cv_no" in duplicate_cv.columns:
            cursor.executemany(
                "INSERT INTO duplicate_cv (run_id, cv_no, duplicate_count) VALUES (?, ?, ?)",
                [
                    (run_id, row.get("cv_no", ""), int(float(row.get("count", 0) or 0)))
                    for _, row in duplicate_cv.iterrows()
                ],
            )

        conn.commit()
        return run_id


def search_batch(batch_no: str, db_path: str | Path = "data/claims_analysis.db") -> pd.DataFrame:
    initialize_database(db_path)
    with connect(db_path) as conn:
        return pd.read_sql_query(
            """
            SELECT
                r.run_timestamp,
                b.batch_no,
                b.provider,
                b.total_amount_per_batch,
                b.cv_no,
                b.check_no,
                b.supplier_category_name,
                b.check_date,
                b.payee_match_status,
                r.run_folder
            FROM claims_batches b
            JOIN analysis_runs r ON r.run_id = b.run_id
            WHERE b.batch_no = ?
            ORDER BY r.run_timestamp DESC
            """,
            conn,
            params=(batch_no,),
        )
