from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


TERM_RE = re.compile(r"(\d+)\s*DAYS?", re.IGNORECASE)


def _money(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0).round(2)


def _term_days(value: object) -> int | None:
    text = "" if pd.isna(value) else str(value).strip()
    match = TERM_RE.search(text)
    if match:
        return int(match.group(1))
    return None


def _schedule_date(row: pd.Series):
    received = pd.to_datetime(row.get("date_received", ""), errors="coerce")
    term_days = row.get("term_days")
    if pd.isna(received) or pd.isna(term_days):
        return pd.NaT
    return received + pd.to_timedelta(int(term_days), unit="D")


def _calendar_bucket(value) -> str:
    date_value = pd.to_datetime(value, errors="coerce")
    if pd.isna(date_value):
        return "NO SCHEDULE DATE"
    return date_value.strftime("%Y-%m")


def generate_payment_schedule(reports_dir: str | Path = "reports/latest") -> Path:
    reports_path = Path(reports_dir)
    source = reports_path / "claims_analysis_output.csv"
    if not source.exists():
        raise FileNotFoundError(f"Missing {source}. Run enhanced_reports first.")

    df = pd.read_csv(source, dtype=str).fillna("")
    for col in ["claims_amount", "expected_check_amount", "check_amount", "difference"]:
        if col in df.columns:
            df[col] = _money(df[col])
        else:
            df[col] = 0

    if "payment_status" not in df.columns:
        df["payment_status"] = ""
    if "credit_term" not in df.columns:
        df["credit_term"] = ""
    if "date_received" not in df.columns:
        df["date_received"] = ""

    df["term_days"] = df["credit_term"].apply(_term_days)
    df["scheduled_payment_date"] = df.apply(_schedule_date, axis=1)
    df["scheduled_payment_date"] = pd.to_datetime(df["scheduled_payment_date"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    df["payment_calendar_month"] = df["scheduled_payment_date"].apply(_calendar_bucket)

    df["payment_schedule_status"] = df.apply(
        lambda row: "PAID" if str(row.get("payment_status", "")).upper() == "PAID" else "FOR PAYMENT TAGGING",
        axis=1,
    )
    df["workflow_action"] = df.apply(
        lambda row: "No action - already paid" if row["payment_schedule_status"] == "PAID" else "Review and tag for payment",
        axis=1,
    )
    df["tagged_for_payment"] = ""
    df["tagged_by"] = ""
    df["tagged_date"] = ""
    df["payment_remarks"] = ""

    preferred = [
        "payment_calendar_month",
        "scheduled_payment_date",
        "payment_schedule_status",
        "workflow_action",
        "tagged_for_payment",
        "tagged_by",
        "tagged_date",
        "payment_remarks",
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
        "claims_amount",
        "expected_check_amount",
        "check_amount",
        "difference",
        "cv_no",
        "check_no",
        "check_date",
    ]
    existing = [col for col in preferred if col in df.columns]
    schedule = df[existing + [col for col in df.columns if col not in existing]].copy()
    schedule.to_csv(reports_path / "payment_schedule_by_batch.csv", index=False)

    provider_schedule = (
        schedule.groupby(["payment_calendar_month", "scheduled_payment_date", "provider", "supplier_category_name", "region", "credit_term", "payment_schedule_status"], dropna=False)
        .agg(
            batch_count=("batch_no", "count"),
            claims_amount=("claims_amount", "sum"),
            expected_check_amount=("expected_check_amount", "sum"),
            check_amount=("check_amount", "sum"),
            difference=("difference", "sum"),
        )
        .reset_index()
        .sort_values(["scheduled_payment_date", "provider"])
    )
    for col in ["claims_amount", "expected_check_amount", "check_amount", "difference"]:
        provider_schedule[col] = _money(provider_schedule[col])
    provider_schedule.to_csv(reports_path / "payment_schedule_by_provider.csv", index=False)

    workflow = schedule[schedule["payment_schedule_status"] == "FOR PAYMENT TAGGING"].copy()
    workflow.to_csv(reports_path / "tagged_for_payment_workflow.csv", index=False)

    return reports_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate payment calendar and tagging workflow sheets.")
    parser.add_argument("--reports-dir", default="reports/latest")
    args = parser.parse_args()
    path = generate_payment_schedule(args.reports_dir)
    print(f"Payment schedule generated: {path}")


if __name__ == "__main__":
    main()
