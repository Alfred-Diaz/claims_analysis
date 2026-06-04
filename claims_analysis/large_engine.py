"""Large dataset engine for Claims Analysis.

This mode is intended for very large ERP CSV exports. It avoids loading both
files fully into memory and avoids creating huge Excel workbooks.

Pipeline:
1. Read CSV files in chunks.
2. Normalize and stage only required columns into SQLite.
3. Aggregate claims by batch_no in SQL.
4. Aggregate checks by batch_no in SQL.
5. Join aggregated tables.
6. Generate lightweight CSV reports and a summary workbook.
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime
import logging
import sqlite3
import re

import pandas as pd
from rapidfuzz import fuzz


REQUIRED_CLAIMS_COLUMNS = ["batch_no", "provider", "payable_to"]
REQUIRED_CHECK_COLUMNS = ["batch_no", "payee_name", "cv_no", "check_no", "check_date"]


def setup_logger(run_dir: Path) -> logging.Logger:
    log_path = run_dir / "run_log.txt"
    logger = logging.getLogger("claims_analysis_large")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def normalize_column_name(value: str) -> str:
    return str(value).strip().lower().replace(" ", "_")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [normalize_column_name(col) for col in df.columns]
    return df


def batch_key_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.lower().str.strip()


def clean_amount_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.fillna("")
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("₱", "", regex=False)
        .str.replace("PHP", "", case=False, regex=False)
        .str.replace(r"[^0-9.\-]", "", regex=True)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0)


def safe_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def unique_join_sql(values: list[object]) -> str:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = safe_text(value)
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return ", ".join(output)


def payee_status(payable_to: object, payee_name: object, threshold: int) -> str:
    left = safe_text(payable_to)
    right = safe_text(payee_name)
    if not left or not right:
        return ""
    score = max(
        fuzz.token_set_ratio(left.lower(), right.lower()),
        fuzz.partial_ratio(left.lower(), right.lower()),
    )
    return "OK" if score >= threshold else "For Review"


def validate_columns(path: Path, required: list[str], amount_column: str | None, label: str) -> list[str]:
    header = pd.read_csv(path, nrows=0)
    columns = [normalize_column_name(col) for col in header.columns]
    missing = [col for col in required if col not in columns]
    if amount_column and amount_column not in columns:
        missing.append(amount_column)
    return missing


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def initialize_staging(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS stg_claims;
        DROP TABLE IF EXISTS stg_checks;
        DROP TABLE IF EXISTS agg_claims;
        DROP TABLE IF EXISTS agg_checks;

        CREATE TABLE stg_claims (
            batch_no_key TEXT,
            batch_no TEXT,
            provider TEXT,
            payable_to TEXT,
            amount REAL
        );

        CREATE TABLE stg_checks (
            batch_no_key TEXT,
            batch_no TEXT,
            payee_name TEXT,
            cv_no TEXT,
            check_no TEXT,
            check_date TEXT
        );

        CREATE INDEX idx_stg_claims_batch ON stg_claims(batch_no_key);
        CREATE INDEX idx_stg_checks_batch ON stg_checks(batch_no_key);
        CREATE INDEX idx_stg_checks_check_no ON stg_checks(check_no);
        CREATE INDEX idx_stg_checks_cv_no ON stg_checks(cv_no);
        """
    )
    conn.commit()


def stage_claims(
    conn: sqlite3.Connection,
    claims_path: Path,
    amount_column: str,
    chunksize: int,
    logger: logging.Logger,
) -> int:
    total_rows = 0
    for idx, chunk in enumerate(pd.read_csv(claims_path, dtype=str, chunksize=chunksize), start=1):
        chunk = normalize_columns(chunk)
        out = pd.DataFrame(
            {
                "batch_no_key": batch_key_series(chunk["batch_no"]),
                "batch_no": chunk["batch_no"].fillna("").astype(str).str.strip(),
                "provider": chunk["provider"].fillna("").astype(str).str.strip(),
                "payable_to": chunk["payable_to"].fillna("").astype(str).str.strip(),
                "amount": clean_amount_series(chunk[amount_column]),
            }
        )
        out.to_sql("stg_claims", conn, if_exists="append", index=False)
        total_rows += len(out)
        logger.info("Staged Claims chunk %s: total rows %s", idx, total_rows)
    return total_rows


def stage_checks(
    conn: sqlite3.Connection,
    checks_path: Path,
    chunksize: int,
    logger: logging.Logger,
) -> int:
    total_rows = 0
    for idx, chunk in enumerate(pd.read_csv(checks_path, dtype=str, chunksize=chunksize), start=1):
        chunk = normalize_columns(chunk)
        out = pd.DataFrame(
            {
                "batch_no_key": batch_key_series(chunk["batch_no"]),
                "batch_no": chunk["batch_no"].fillna("").astype(str).str.strip(),
                "payee_name": chunk["payee_name"].fillna("").astype(str).str.strip(),
                "cv_no": chunk["cv_no"].fillna("").astype(str).str.strip(),
                "check_no": chunk["check_no"].fillna("").astype(str).str.strip(),
                "check_date": chunk["check_date"].fillna("").astype(str).str.strip(),
            }
        )
        out.to_sql("stg_checks", conn, if_exists="append", index=False)
        total_rows += len(out)
        logger.info("Staged Checks chunk %s: total rows %s", idx, total_rows)
    return total_rows


def aggregate_to_reports(
    conn: sqlite3.Connection,
    run_dir: Path,
    fuzzy_threshold: int,
    logger: logging.Logger,
) -> None:
    logger.info("Aggregating claims by batch_no")
    conn.executescript(
        """
        CREATE TABLE agg_claims AS
        SELECT
            batch_no_key,
            MIN(NULLIF(batch_no, '')) AS batch_no,
            MIN(NULLIF(provider, '')) AS provider,
            MIN(NULLIF(payable_to, '')) AS payable_to,
            SUM(amount) AS total_amount_per_batch
        FROM stg_claims
        WHERE batch_no_key IS NOT NULL AND batch_no_key <> ''
        GROUP BY batch_no_key;

        CREATE INDEX idx_agg_claims_batch ON agg_claims(batch_no_key);
        """
    )
    conn.commit()

    logger.info("Aggregating check data by batch_no")
    check_rows = pd.read_sql_query(
        """
        SELECT batch_no_key, payee_name, cv_no, check_no, check_date
        FROM stg_checks
        WHERE batch_no_key IS NOT NULL AND batch_no_key <> ''
        ORDER BY batch_no_key
        """,
        conn,
    )

    if check_rows.empty:
        agg_checks = pd.DataFrame(columns=["batch_no_key", "payee_name", "cv_no", "check_no", "check_date", "cv_count", "check_count"])
    else:
        grouped = check_rows.groupby("batch_no_key", sort=False)
        agg_checks = grouped.agg(
            payee_name=("payee_name", unique_join_sql),
            cv_no=("cv_no", unique_join_sql),
            check_no=("check_no", unique_join_sql),
            check_date=("check_date", unique_join_sql),
            cv_count=("cv_no", lambda s: len(set(v for v in s.astype(str).str.strip() if v))),
            check_count=("check_no", lambda s: len(set(v for v in s.astype(str).str.strip() if v))),
        ).reset_index()

    agg_checks.to_sql("agg_checks", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agg_checks_batch ON agg_checks(batch_no_key)")
    conn.commit()

    logger.info("Joining batch summaries")
    result = pd.read_sql_query(
        """
        SELECT
            c.batch_no,
            c.provider,
            c.payable_to,
            c.total_amount_per_batch,
            COALESCE(k.payee_name, '') AS payee_name,
            COALESCE(k.cv_no, '') AS cv_no,
            COALESCE(k.check_no, '') AS check_no,
            COALESCE(k.check_date, '') AS check_date,
            COALESCE(k.cv_count, 0) AS cv_count,
            COALESCE(k.check_count, 0) AS check_count
        FROM agg_claims c
        LEFT JOIN agg_checks k ON k.batch_no_key = c.batch_no_key
        ORDER BY c.batch_no
        """,
        conn,
    )

    logger.info("Calculating classifications and payee status")
    result["supplier_category_name"] = result.apply(
        lambda row: "Hospital" if int(row.get("cv_count", 0) or 0) <= 1 and int(row.get("check_count", 0) or 0) <= 1 else "Professional",
        axis=1,
    )
    result["payee_match_status"] = result.apply(
        lambda row: payee_status(row.get("payable_to", ""), row.get("payee_name", ""), fuzzy_threshold),
        axis=1,
    )

    output = result[
        [
            "batch_no",
            "provider",
            "total_amount_per_batch",
            "cv_no",
            "check_no",
            "supplier_category_name",
            "check_date",
            "payee_match_status",
        ]
    ].copy()
    output["total_amount_per_batch"] = pd.to_numeric(output["total_amount_per_batch"], errors="coerce").fillna(0).round(2)

    for_review = output[output["payee_match_status"] == "For Review"]
    unmatched = output[output["check_no"].fillna("").astype(str).str.strip() == ""]

    duplicate_checks = pd.read_sql_query(
        """
        SELECT check_no, COUNT(*) AS count
        FROM stg_checks
        WHERE check_no IS NOT NULL AND TRIM(check_no) <> ''
        GROUP BY check_no
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        """,
        conn,
    )
    duplicate_cv = pd.read_sql_query(
        """
        SELECT cv_no, COUNT(*) AS count
        FROM stg_checks
        WHERE cv_no IS NOT NULL AND TRIM(cv_no) <> ''
        GROUP BY cv_no
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        """,
        conn,
    )

    summary = pd.DataFrame(
        [
            {"metric": "total_batches", "value": len(output)},
            {"metric": "hospital_count", "value": int((output["supplier_category_name"] == "Hospital").sum())},
            {"metric": "professional_count", "value": int((output["supplier_category_name"] == "Professional").sum())},
            {"metric": "matched_payees", "value": int((output["payee_match_status"] == "OK").sum())},
            {"metric": "for_review_payees", "value": len(for_review)},
            {"metric": "blank_payee_match_status", "value": int((output["payee_match_status"] == "").sum())},
            {"metric": "unmatched_batches", "value": len(unmatched)},
            {"metric": "duplicate_check_numbers", "value": len(duplicate_checks)},
            {"metric": "duplicate_cv_numbers", "value": len(duplicate_cv)},
            {"metric": "total_amount", "value": round(float(output["total_amount_per_batch"].sum()), 2)},
        ]
    )

    logger.info("Writing CSV reports")
    output.to_csv(run_dir / "claims_analysis_output.csv", index=False)
    for_review.to_csv(run_dir / "for_review.csv", index=False)
    unmatched.to_csv(run_dir / "unmatched_batches.csv", index=False)
    duplicate_checks.to_csv(run_dir / "duplicate_checks.csv", index=False)
    duplicate_cv.to_csv(run_dir / "duplicate_cv.csv", index=False)
    summary.to_csv(run_dir / "summary.csv", index=False)

    logger.info("Writing lightweight Excel summary workbook")
    with pd.ExcelWriter(run_dir / "summary_report.xlsx", engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        for_review.head(100000).to_excel(writer, sheet_name="For Review", index=False)
        unmatched.head(100000).to_excel(writer, sheet_name="Unmatched", index=False)
        duplicate_checks.head(100000).to_excel(writer, sheet_name="Duplicate Checks", index=False)
        duplicate_cv.head(100000).to_excel(writer, sheet_name="Duplicate CV", index=False)


def run_large_analysis(
    claims_path: str | Path,
    checks_path: str | Path,
    output_root: str | Path = "reports/history",
    db_path: str | Path = "data/large_staging.db",
    amount_column: str = "amount",
    fuzzy_threshold: int = 80,
    chunksize: int = 100000,
) -> Path:
    claims_path = Path(claims_path)
    checks_path = Path(checks_path)
    amount_column = normalize_column_name(amount_column)

    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = Path(output_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logger(run_dir)
    logger.info("Large Claims Analysis run started")
    logger.info("Claims file: %s", claims_path)
    logger.info("Checks file: %s", checks_path)

    missing_claims = validate_columns(claims_path, REQUIRED_CLAIMS_COLUMNS, amount_column, "Claims Process")
    missing_checks = validate_columns(checks_path, REQUIRED_CHECK_COLUMNS, None, "Check Date Created")
    if missing_claims or missing_checks:
        message = f"Missing columns. Claims: {missing_claims}; Checks: {missing_checks}"
        logger.error(message)
        raise ValueError(message)

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    with connect(db_path) as conn:
        initialize_staging(conn)
        claims_rows = stage_claims(conn, claims_path, amount_column, chunksize, logger)
        checks_rows = stage_checks(conn, checks_path, chunksize, logger)
        logger.info("Total staged claims rows: %s", claims_rows)
        logger.info("Total staged check rows: %s", checks_rows)
        aggregate_to_reports(conn, run_dir, fuzzy_threshold, logger)

    logger.info("Large Claims Analysis run completed")
    logger.info("Report folder: %s", run_dir)
    return run_dir
