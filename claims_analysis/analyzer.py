"""Core Claims Analysis engine.

Workflow:
1. Read ERP exports from data/raw.
2. Match Claims Process and Check Date Created by batch_no.
3. Validate payable_to vs payee_name using fuzzy matching.
4. Aggregate one output row per batch_no.
5. Generate exception and summary reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import logging
import shutil

import pandas as pd
from rapidfuzz import fuzz


@dataclass
class AnalysisConfig:
    amount_column: str = "amount"
    fuzzy_threshold: int = 80
    archive_raw_files: bool = False


REQUIRED_CLAIMS_COLUMNS = ["batch_no", "provider", "payable_to"]
REQUIRED_CHECK_COLUMNS = ["batch_no", "payee_name", "cv_no", "check_no", "check_date"]


OUTPUT_COLUMNS = [
    "batch_no",
    "provider",
    "total_amount_per_batch",
    "cv_no",
    "check_no",
    "supplier_category_name",
    "check_date",
    "payee_match_status",
]


def setup_logger(run_dir: Path) -> logging.Logger:
    log_path = run_dir / "run_log.txt"
    logger = logging.getLogger("claims_analysis")
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


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    return df.map(lambda value: value.strip() if isinstance(value, str) else value)


def load_csv(path: Path, label: str, logger: logging.Logger) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{label} file not found: {path}")

    df = pd.read_csv(path, dtype=str)
    df = normalize_columns(df)
    logger.info("Loaded %s: %s rows, %s columns", label, len(df), len(df.columns))
    logger.info("%s columns: %s", label, list(df.columns))
    return df


def validate_required_columns(df: pd.DataFrame, required: list[str], label: str) -> list[str]:
    return [column for column in required if column not in df.columns]


def clean_amount_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.fillna("")
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("₱", "", regex=False)
        .str.replace("PHP", "", case=False, regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0)


def unique_join(series: pd.Series) -> str:
    values = series.dropna().astype(str).str.strip()
    values = values[values != ""].drop_duplicates().tolist()
    return ", ".join(values)


def unique_count(series: pd.Series) -> int:
    values = series.dropna().astype(str).str.strip()
    values = values[values != ""].drop_duplicates()
    return len(values)


def payee_match_status(payable_to: object, payee_name: object, threshold: int) -> str:
    left = str(payable_to).strip() if pd.notna(payable_to) else ""
    right = str(payee_name).strip() if pd.notna(payee_name) else ""

    if not left or not right:
        return ""

    token_score = fuzz.token_set_ratio(left.lower(), right.lower())
    partial_score = fuzz.partial_ratio(left.lower(), right.lower())
    score = max(token_score, partial_score)
    return "OK" if score >= threshold else "For Review"


def supplier_category(cv_series: pd.Series, check_series: pd.Series) -> str:
    if unique_count(cv_series) <= 1 and unique_count(check_series) <= 1:
        return "Hospital"
    return "Professional"


def duplicate_report(df: pd.DataFrame, column: str, source_label: str) -> pd.DataFrame:
    if column not in df.columns:
        return pd.DataFrame(columns=[source_label, column, "count"])

    normalized = df[column].dropna().astype(str).str.strip()
    normalized = normalized[normalized != ""]
    duplicated_values = normalized[normalized.duplicated(keep=False)]

    if duplicated_values.empty:
        return pd.DataFrame(columns=[source_label, column, "count"])

    counts = duplicated_values.value_counts().reset_index()
    counts.columns = [column, "count"]
    counts.insert(0, "source", source_label)
    return counts


def run_analysis(
    claims_path: str | Path,
    checks_path: str | Path,
    output_root: str | Path = "reports/history",
    config: AnalysisConfig | None = None,
) -> Path:
    config = config or AnalysisConfig()

    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = Path(output_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logger(run_dir)
    logger.info("Claims Analysis run started")

    claims_path = Path(claims_path)
    checks_path = Path(checks_path)

    claims = load_csv(claims_path, "Claims Process", logger)
    checks = load_csv(checks_path, "Check Date Created", logger)

    missing_claims = validate_required_columns(claims, REQUIRED_CLAIMS_COLUMNS, "Claims Process")
    missing_checks = validate_required_columns(checks, REQUIRED_CHECK_COLUMNS, "Check Date Created")

    if config.amount_column not in claims.columns:
        missing_claims.append(config.amount_column)

    if missing_claims or missing_checks:
        errors = []
        if missing_claims:
            errors.append(f"Claims Process missing columns: {missing_claims}")
        if missing_checks:
            errors.append(f"Check Date Created missing columns: {missing_checks}")
        error_message = " | ".join(errors)
        logger.error(error_message)
        raise ValueError(error_message)

    claims["batch_no_key"] = claims["batch_no"].fillna("").astype(str).str.lower().str.strip()
    checks["batch_no_key"] = checks["batch_no"].fillna("").astype(str).str.lower().str.strip()

    merged = claims.merge(
        checks,
        on="batch_no_key",
        how="left",
        suffixes=("_claims", "_checks"),
        indicator=True,
    )

    merged["batch_no"] = merged.get("batch_no_claims", merged.get("batch_no"))
    merged["_payee_status"] = merged.apply(
        lambda row: payee_match_status(
            row.get("payable_to", ""),
            row.get("payee_name", ""),
            config.fuzzy_threshold,
        ),
        axis=1,
    )

    records: list[dict[str, object]] = []

    for batch_key, group in merged.groupby("batch_no_key", sort=False):
        batch_no_values = group["batch_no"].dropna().astype(str).str.strip()
        batch_no = batch_no_values.iloc[0] if not batch_no_values.empty else batch_key

        provider_values = group["provider"].dropna().astype(str).str.strip()
        provider = provider_values.iloc[0] if not provider_values.empty else ""

        total_amount = clean_amount_series(group[config.amount_column]).sum()
        cv_no = unique_join(group["cv_no"])
        check_no = unique_join(group["check_no"])
        check_date = unique_join(group["check_date"])
        supplier = supplier_category(group["cv_no"], group["check_no"])

        statuses = group["_payee_status"].tolist()
        if "For Review" in statuses:
            payee_status = "For Review"
        elif all(status == "" for status in statuses):
            payee_status = ""
        else:
            payee_status = "OK"

        records.append(
            {
                "batch_no": batch_no,
                "provider": provider,
                "total_amount_per_batch": round(float(total_amount), 2),
                "cv_no": cv_no,
                "check_no": check_no,
                "supplier_category_name": supplier,
                "check_date": check_date,
                "payee_match_status": payee_status,
            }
        )

    output_df = pd.DataFrame(records, columns=OUTPUT_COLUMNS)

    unmatched_batches = output_df[output_df["check_no"].fillna("").astype(str).str.strip() == ""]
    for_review = output_df[output_df["payee_match_status"] == "For Review"]
    duplicate_checks = duplicate_report(checks, "check_no", "Check Date Created")
    duplicate_cv = duplicate_report(checks, "cv_no", "Check Date Created")

    total_amount = output_df["total_amount_per_batch"].sum()
    summary = pd.DataFrame(
        [
            {"metric": "total_batches", "value": len(output_df)},
            {"metric": "hospital_count", "value": int((output_df["supplier_category_name"] == "Hospital").sum())},
            {"metric": "professional_count", "value": int((output_df["supplier_category_name"] == "Professional").sum())},
            {"metric": "matched_payees", "value": int((output_df["payee_match_status"] == "OK").sum())},
            {"metric": "for_review_payees", "value": int((output_df["payee_match_status"] == "For Review").sum())},
            {"metric": "blank_payee_match_status", "value": int((output_df["payee_match_status"] == "").sum())},
            {"metric": "unmatched_batches", "value": len(unmatched_batches)},
            {"metric": "duplicate_check_numbers", "value": len(duplicate_checks)},
            {"metric": "duplicate_cv_numbers", "value": len(duplicate_cv)},
            {"metric": "total_amount", "value": round(float(total_amount), 2)},
        ]
    )

    output_df.to_csv(run_dir / "claims_analysis_output.csv", index=False)
    for_review.to_csv(run_dir / "for_review.csv", index=False)
    unmatched_batches.to_csv(run_dir / "unmatched_batches.csv", index=False)
    duplicate_checks.to_csv(run_dir / "duplicate_checks.csv", index=False)
    duplicate_cv.to_csv(run_dir / "duplicate_cv.csv", index=False)
    summary.to_csv(run_dir / "summary.csv", index=False)

    excel_path = run_dir / "summary_report.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        output_df.to_excel(writer, sheet_name="Results", index=False)
        for_review.to_excel(writer, sheet_name="For Review", index=False)
        unmatched_batches.to_excel(writer, sheet_name="Unmatched Batches", index=False)
        duplicate_checks.to_excel(writer, sheet_name="Duplicate Checks", index=False)
        duplicate_cv.to_excel(writer, sheet_name="Duplicate CV", index=False)

    latest_dir = Path("reports/latest")
    latest_dir.mkdir(parents=True, exist_ok=True)
    for file_path in run_dir.iterdir():
        if file_path.is_file():
            shutil.copy2(file_path, latest_dir / file_path.name)

    logger.info("Claims Analysis run completed")
    logger.info("Report folder: %s", run_dir)
    logger.info("Total batches: %s", len(output_df))
    logger.info("For review payees: %s", len(for_review))
    logger.info("Unmatched batches: %s", len(unmatched_batches))

    return run_dir
