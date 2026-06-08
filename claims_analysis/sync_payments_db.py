from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from claims_analysis.payment_db import DEFAULT_DB_PATH, get_all_tags, init_db, upsert_reference


DEFAULT_REPORTS_DIR = "reports/latest"
SOURCE_FILE = "payment_schedule_by_batch.csv"
SYNC_SUMMARY_FILE = "payment_db_sync_summary.csv"
SYNCED_EXPORT_FILE = "payments_db_current_export.csv"


REFERENCE_COLUMNS = [
    "batch_no",
    "provider",
    "supplier_category_name",
    "region",
    "province",
    "city",
    "date_received",
    "aging_days",
    "aging_bucket",
    "credit_term",
    "term_days",
    "mpsu_tag",
    "payment_status",
    "payment_schedule_status",
    "payment_calendar_month",
    "calendar_payment_date",
    "scheduled_payment_date",
    "check_date",
    "claims_amount",
    "expected_check_amount",
    "check_amount",
    "difference",
    "cv_no",
    "check_no",
    "claim_documentation_type",
]


MANUAL_COLUMNS = [
    "tagged_for_payment",
    "processor_name",
    "target_payment_date",
    "tagged_date",
    "payment_priority",
    "payment_remarks",
    "approval_status",
    "released_status",
    "paid_status",
]


def _clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _norm(value: object) -> str:
    return _clean_text(value).upper()


def _money_text(value: object) -> str:
    if pd.isna(value) or str(value).strip() == "":
        return "0.00"
    number = pd.to_numeric(str(value).replace(",", ""), errors="coerce")
    if pd.isna(number):
        return "0.00"
    return f"{float(number):.2f}"


def _should_sync(row: pd.Series, include_paid: bool = False) -> bool:
    if include_paid:
        return True
    payment_status = _norm(row.get("payment_status", ""))
    schedule_status = _norm(row.get("payment_schedule_status", ""))
    check_no = _clean_text(row.get("check_no", ""))
    check_amount = float(_money_text(row.get("check_amount", "0")))

    # Main operational reference is unpaid/payment-candidate batches.
    if payment_status == "UNPAID":
        return True
    if schedule_status == "FOR PAYMENT TAGGING":
        return True
    if not check_no and check_amount == 0:
        return True
    return False


def _reference_values(row: pd.Series) -> dict[str, str]:
    values: dict[str, str] = {}
    for col in REFERENCE_COLUMNS:
        if col == "batch_no":
            continue
        if col in ["claims_amount", "expected_check_amount", "check_amount", "difference"]:
            values[col] = _money_text(row.get(col, "0"))
        else:
            values[col] = _clean_text(row.get(col, ""))
    return values


def _priority_score(row: pd.Series) -> int:
    score = 0
    aging = _norm(row.get("aging_bucket", ""))
    credit = _norm(row.get("credit_term", ""))
    mpsu = _norm(row.get("mpsu_tag", ""))
    amount = float(_money_text(row.get("expected_check_amount", "0")))

    if "ABOVE 120" in aging:
        score += 50
    elif "91-120" in aging or "90-120" in aging:
        score += 40
    elif "61-90" in aging or "60-90" in aging:
        score += 30
    elif "31-60" in aging or "30-60" in aging:
        score += 20
    elif "0-30" in aging:
        score += 10

    if "TOP 5" in credit or "TOP HOSPITAL" in mpsu:
        score += 30
    if "7 DAYS" in credit:
        score += 25
    elif "15 DAYS" in credit:
        score += 20
    elif "30 DAYS" in credit:
        score += 10

    if amount >= 1_000_000:
        score += 20
    elif amount >= 500_000:
        score += 15
    elif amount >= 100_000:
        score += 10

    return score


def _priority_label(score: int) -> str:
    if score >= 70:
        return "URGENT"
    if score >= 45:
        return "HIGH"
    if score >= 25:
        return "NORMAL"
    return "LOW"


def sync_payments_db(
    reports_dir: str | Path = DEFAULT_REPORTS_DIR,
    db_path: str | Path = DEFAULT_DB_PATH,
    include_paid: bool = False,
) -> dict[str, int]:
    reports_path = Path(reports_dir)
    source_path = reports_path / SOURCE_FILE
    if not source_path.exists():
        raise FileNotFoundError(f"Missing {source_path}. Run payment_schedule first.")

    init_db(db_path)
    df = pd.read_csv(source_path, dtype=str).fillna("")
    if "batch_no" not in df.columns:
        raise ValueError(f"{source_path} must contain batch_no")

    total_rows = len(df)
    candidates = df[df.apply(lambda row: _should_sync(row, include_paid=include_paid), axis=1)].copy()
    candidates["payment_priority_score"] = candidates.apply(_priority_score, axis=1)
    candidates["recommended_payment_priority"] = candidates["payment_priority_score"].apply(_priority_label)

    synced = 0
    skipped_missing_batch = 0
    for _, row in candidates.iterrows():
        batch_no = _clean_text(row.get("batch_no", ""))
        if not batch_no:
            skipped_missing_batch += 1
            continue
        values = _reference_values(row)
        values["payment_priority"] = _clean_text(row.get("payment_priority", "")) or row["recommended_payment_priority"]
        upsert_reference(batch_no, values, db_path=db_path)
        synced += 1

    current_tags = pd.DataFrame(get_all_tags(db_path))
    if not current_tags.empty:
        current_tags.to_csv(reports_path / SYNCED_EXPORT_FILE, index=False)
    else:
        pd.DataFrame(columns=["batch_no", *REFERENCE_COLUMNS, *MANUAL_COLUMNS]).to_csv(reports_path / SYNCED_EXPORT_FILE, index=False)

    summary = pd.DataFrame(
        [
            {"metric": "source_rows", "value": total_rows},
            {"metric": "candidate_rows", "value": len(candidates)},
            {"metric": "synced_rows", "value": synced},
            {"metric": "skipped_missing_batch", "value": skipped_missing_batch},
            {"metric": "include_paid", "value": include_paid},
            {"metric": "db_path", "value": str(db_path)},
        ]
    )
    summary.to_csv(reports_path / SYNC_SUMMARY_FILE, index=False)

    return {
        "source_rows": total_rows,
        "candidate_rows": len(candidates),
        "synced_rows": synced,
        "skipped_missing_batch": skipped_missing_batch,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync unpaid/payment-candidate batches into payments.db.")
    parser.add_argument("--reports-dir", default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--include-paid", action="store_true", help="Sync paid rows too. Default syncs unpaid/payment candidates only.")
    args = parser.parse_args()
    result = sync_payments_db(args.reports_dir, args.db, include_paid=args.include_paid)
    print("Payment DB sync completed")
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
