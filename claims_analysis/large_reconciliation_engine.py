from __future__ import annotations

from pathlib import Path
from datetime import datetime
import logging
import shutil
import sqlite3

import pandas as pd
from rapidfuzz import fuzz


REQUIRED_CLAIMS_COLUMNS = ["batch_no", "provider", "payable_to"]
REQUIRED_CHECK_COLUMNS = ["batch_no", "payee_name", "cv_no", "check_no", "check_date"]


def setup_logger(run_dir: Path) -> logging.Logger:
    log_path = run_dir / "run_log.txt"
    logger = logging.getLogger("claims_reconciliation_large")
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


def unique_join(values: pd.Series) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = safe_text(value)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return ", ".join(out)


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


def validate_columns(path: Path, required: list[str], amount_column: str | None) -> list[str]:
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

        CREATE TABLE stg_claims (
            batch_no_key TEXT,
            batch_no TEXT,
            provider TEXT,
            payable_to TEXT,
            claims_amount REAL
        );

        CREATE TABLE stg_checks (
            batch_no_key TEXT,
            batch_no TEXT,
            payee_name TEXT,
            cv_no TEXT,
            check_no TEXT,
            check_date TEXT,
            check_amount REAL
        );

        CREATE INDEX idx_stg_claims_batch ON stg_claims(batch_no_key);
        CREATE INDEX idx_stg_checks_batch ON stg_checks(batch_no_key);
        CREATE INDEX idx_stg_checks_check_no ON stg_checks(check_no);
        CREATE INDEX idx_stg_checks_cv_no ON stg_checks(cv_no);
        """
    )
    conn.commit()


def stage_claims(conn: sqlite3.Connection, claims_path: Path, amount_column: str, chunksize: int, logger: logging.Logger) -> int:
    total = 0
    for idx, chunk in enumerate(pd.read_csv(claims_path, dtype=str, chunksize=chunksize), start=1):
        chunk = normalize_columns(chunk)
        out = pd.DataFrame(
            {
                "batch_no_key": chunk["batch_no"].fillna("").astype(str).str.lower().str.strip(),
                "batch_no": chunk["batch_no"].fillna("").astype(str).str.strip(),
                "provider": chunk["provider"].fillna("").astype(str).str.strip(),
                "payable_to": chunk["payable_to"].fillna("").astype(str).str.strip(),
                "claims_amount": clean_amount_series(chunk[amount_column]),
            }
        )
        out.to_sql("stg_claims", conn, if_exists="append", index=False)
        total += len(out)
        logger.info("Staged Claims chunk %s: total rows %s", idx, total)
    return total


def stage_checks(conn: sqlite3.Connection, checks_path: Path, check_amount_column: str, chunksize: int, logger: logging.Logger) -> int:
    total = 0
    for idx, chunk in enumerate(pd.read_csv(checks_path, dtype=str, chunksize=chunksize), start=1):
        chunk = normalize_columns(chunk)
        out = pd.DataFrame(
            {
                "batch_no_key": chunk["batch_no"].fillna("").astype(str).str.lower().str.strip(),
                "batch_no": chunk["batch_no"].fillna("").astype(str).str.strip(),
                "payee_name": chunk["payee_name"].fillna("").astype(str).str.strip(),
                "cv_no": chunk["cv_no"].fillna("").astype(str).str.strip(),
                "check_no": chunk["check_no"].fillna("").astype(str).str.strip(),
                "check_date": chunk["check_date"].fillna("").astype(str).str.strip(),
                "check_amount": clean_amount_series(chunk[check_amount_column]),
            }
        )
        out.to_sql("stg_checks", conn, if_exists="append", index=False)
        total += len(out)
        logger.info("Staged Checks chunk %s: total rows %s", idx, total)
    return total


def aggregate_checks(conn: sqlite3.Connection, logger: logging.Logger) -> pd.DataFrame:
    logger.info("Loading check rows for batch aggregation")
    checks = pd.read_sql_query(
        """
        SELECT batch_no_key, payee_name, cv_no, check_no, check_date, check_amount
        FROM stg_checks
        WHERE batch_no_key IS NOT NULL AND batch_no_key <> ''
        ORDER BY batch_no_key
        """,
        conn,
    )
    if checks.empty:
        return pd.DataFrame(columns=["batch_no_key", "payee_name", "cv_no", "check_no", "check_date", "check_amount", "cv_count", "check_count"])

    grouped = checks.groupby("batch_no_key", sort=False)
    return grouped.agg(
        payee_name=("payee_name", unique_join),
        cv_no=("cv_no", unique_join),
        check_no=("check_no", unique_join),
        check_date=("check_date", unique_join),
        check_amount=("check_amount", "sum"),
        cv_count=("cv_no", lambda s: len(set(v for v in s.astype(str).str.strip() if v))),
        check_count=("check_no", lambda s: len(set(v for v in s.astype(str).str.strip() if v))),
    ).reset_index()


def write_reports(conn: sqlite3.Connection, run_dir: Path, fuzzy_threshold: int, withholding_rate: float, tolerance: float, logger: logging.Logger) -> None:
    logger.info("Aggregating claims by batch_no")
    claims = pd.read_sql_query(
        """
        SELECT
            batch_no_key,
            MIN(NULLIF(batch_no, '')) AS batch_no,
            MIN(NULLIF(provider, '')) AS provider,
            MIN(NULLIF(payable_to, '')) AS payable_to,
            SUM(claims_amount) AS claims_amount
        FROM stg_claims
        WHERE batch_no_key IS NOT NULL AND batch_no_key <> ''
        GROUP BY batch_no_key
        ORDER BY batch_no_key
        """,
        conn,
    )

    checks = aggregate_checks(conn, logger)
    logger.info("Joining claim and check batch summaries")
    result = claims.merge(checks, on="batch_no_key", how="left")
    result["check_amount"] = pd.to_numeric(result["check_amount"], errors="coerce").fillna(0)
    result["claims_amount"] = pd.to_numeric(result["claims_amount"], errors="coerce").fillna(0)
    result["cv_count"] = pd.to_numeric(result["cv_count"], errors="coerce").fillna(0).astype(int)
    result["check_count"] = pd.to_numeric(result["check_count"], errors="coerce").fillna(0).astype(int)

    for col in ["payee_name", "cv_no", "check_no", "check_date"]:
        result[col] = result[col].fillna("")

    result["supplier_category_name"] = result.apply(
        lambda row: "Hospital" if int(row["cv_count"]) <= 1 and int(row["check_count"]) <= 1 else "Professional",
        axis=1,
    )
    result["withholding_tax"] = result.apply(
        lambda row: float(row["claims_amount"]) * withholding_rate if row["supplier_category_name"] == "Hospital" else 0.0,
        axis=1,
    )
    result["expected_check_amount"] = result["claims_amount"] - result["withholding_tax"]
    result["difference"] = result["check_amount"] - result["expected_check_amount"]
    result["reconciliation_status"] = result["difference"].apply(lambda v: "MATCHED" if abs(round(float(v), 2)) <= tolerance else "VARIANCE")
    result["payee_match_status"] = result.apply(lambda r: payee_status(r.get("payable_to", ""), r.get("payee_name", ""), fuzzy_threshold), axis=1)

    money_cols = ["claims_amount", "withholding_tax", "expected_check_amount", "check_amount", "difference"]
    for col in money_cols:
        result[col] = pd.to_numeric(result[col], errors="coerce").fillna(0).round(2)

    output = result[
        [
            "batch_no",
            "provider",
            "claims_amount",
            "withholding_tax",
            "expected_check_amount",
            "check_amount",
            "difference",
            "reconciliation_status",
            "cv_no",
            "check_no",
            "supplier_category_name",
            "check_date",
            "payee_match_status",
        ]
    ].copy()
    output.insert(2, "total_amount_per_batch", output["claims_amount"])

    provider_reconciliation = output.groupby("provider", dropna=False).agg(
        batch_count=("batch_no", "count"),
        claims_amount=("claims_amount", "sum"),
        withholding_tax=("withholding_tax", "sum"),
        expected_check_amount=("expected_check_amount", "sum"),
        check_amount=("check_amount", "sum"),
        difference=("difference", "sum"),
        variance_batch_count=("reconciliation_status", lambda s: int((s == "VARIANCE").sum())),
    ).reset_index()
    provider_reconciliation["provider"] = provider_reconciliation["provider"].replace("", "UNKNOWN")
    for col in ["claims_amount", "withholding_tax", "expected_check_amount", "check_amount", "difference"]:
        provider_reconciliation[col] = pd.to_numeric(provider_reconciliation[col], errors="coerce").fillna(0).round(2)
    provider_reconciliation = provider_reconciliation.sort_values("difference", key=lambda s: s.abs(), ascending=False)

    variance = output[output["reconciliation_status"] == "VARIANCE"].copy()
    for_review = output[output["payee_match_status"] == "For Review"].copy()
    unmatched = output[output["check_no"].fillna("").astype(str).str.strip() == ""].copy()

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
            {"metric": "matched_batches", "value": int((output["reconciliation_status"] == "MATCHED").sum())},
            {"metric": "variance_batches", "value": len(variance)},
            {"metric": "hospital_count", "value": int((output["supplier_category_name"] == "Hospital").sum())},
            {"metric": "professional_count", "value": int((output["supplier_category_name"] == "Professional").sum())},
            {"metric": "claims_total_amount", "value": round(float(output["claims_amount"].sum()), 2)},
            {"metric": "withholding_tax_total", "value": round(float(output["withholding_tax"].sum()), 2)},
            {"metric": "expected_check_total", "value": round(float(output["expected_check_amount"].sum()), 2)},
            {"metric": "actual_check_total", "value": round(float(output["check_amount"].sum()), 2)},
            {"metric": "total_difference", "value": round(float(output["difference"].sum()), 2)},
            {"metric": "for_review_payees", "value": len(for_review)},
            {"metric": "unmatched_batches", "value": len(unmatched)},
            {"metric": "duplicate_check_numbers", "value": len(duplicate_checks)},
            {"metric": "duplicate_cv_numbers", "value": len(duplicate_cv)},
            {"metric": "total_providers", "value": provider_reconciliation["provider"].nunique()},
        ]
    )

    logger.info("Writing reconciliation reports")
    output.to_csv(run_dir / "claims_analysis_output.csv", index=False)
    output.to_csv(run_dir / "amount_reconciliation_by_batch.csv", index=False)
    provider_reconciliation.to_csv(run_dir / "provider_amount_reconciliation.csv", index=False)
    variance.to_csv(run_dir / "batch_variances.csv", index=False)
    for_review.to_csv(run_dir / "for_review.csv", index=False)
    unmatched.to_csv(run_dir / "unmatched_batches.csv", index=False)
    duplicate_checks.to_csv(run_dir / "duplicate_checks.csv", index=False)
    duplicate_cv.to_csv(run_dir / "duplicate_cv.csv", index=False)
    summary.to_csv(run_dir / "summary.csv", index=False)
    summary.to_csv(run_dir / "reconciliation_summary.csv", index=False)

    logger.info("Writing Excel summary workbook")
    with pd.ExcelWriter(run_dir / "summary_report.xlsx", engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        provider_reconciliation.head(100000).to_excel(writer, sheet_name="Provider Recon", index=False)
        variance.head(100000).to_excel(writer, sheet_name="Batch Variances", index=False)
        for_review.head(100000).to_excel(writer, sheet_name="For Review", index=False)
        unmatched.head(100000).to_excel(writer, sheet_name="Unmatched", index=False)
        duplicate_checks.head(100000).to_excel(writer, sheet_name="Duplicate Checks", index=False)
        duplicate_cv.head(100000).to_excel(writer, sheet_name="Duplicate CV", index=False)


def refresh_latest_reports(run_dir: Path, latest_dir: str | Path = "reports/latest") -> Path:
    latest_path = Path(latest_dir)
    latest_path.mkdir(parents=True, exist_ok=True)
    for existing in latest_path.iterdir():
        if existing.is_file():
            existing.unlink()
    for file_path in run_dir.iterdir():
        if file_path.is_file():
            shutil.copy2(file_path, latest_path / file_path.name)
    return latest_path


def run_large_reconciliation(
    claims_path: str | Path,
    checks_path: str | Path,
    output_root: str | Path = "reports/history",
    db_path: str | Path = "data/large_staging.db",
    amount_column: str = "amount_payable",
    check_amount_column: str = "check_amount",
    fuzzy_threshold: int = 80,
    chunksize: int = 100000,
    hospital_withholding_rate: float = 0.02,
    tolerance: float = 0.01,
) -> Path:
    claims_path = Path(claims_path)
    checks_path = Path(checks_path)
    amount_column = normalize_column_name(amount_column)
    check_amount_column = normalize_column_name(check_amount_column)

    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = Path(output_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logger(run_dir)
    logger.info("Large reconciliation run started")
    logger.info("Claims file: %s", claims_path)
    logger.info("Checks file: %s", checks_path)
    logger.info("Hospital withholding rate: %.2f%%", hospital_withholding_rate * 100)

    missing_claims = validate_columns(claims_path, REQUIRED_CLAIMS_COLUMNS, amount_column)
    missing_checks = validate_columns(checks_path, REQUIRED_CHECK_COLUMNS, check_amount_column)
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
        checks_rows = stage_checks(conn, checks_path, check_amount_column, chunksize, logger)
        logger.info("Total staged claims rows: %s", claims_rows)
        logger.info("Total staged check rows: %s", checks_rows)
        write_reports(conn, run_dir, fuzzy_threshold, hospital_withholding_rate, tolerance, logger)

    latest_path = refresh_latest_reports(run_dir)
    logger.info("Latest reports refreshed: %s", latest_path)
    logger.info("Large reconciliation run completed")
    logger.info("Report folder: %s", run_dir)
    return run_dir
