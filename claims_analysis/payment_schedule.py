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


def _first_valid_date(value: object):
    if pd.isna(value):
        return pd.NaT
    text = str(value).strip()
    if not text:
        return pd.NaT
    # Some fields contain multiple dates joined by comma. Use the latest actual date.
    parts = [part.strip() for part in text.split(",") if part.strip()]
    dates = pd.to_datetime(parts or [text], errors="coerce")
    dates = pd.Series(dates).dropna()
    if dates.empty:
        return pd.NaT
    return dates.max()


def _schedule_date(row: pd.Series):
    received = pd.to_datetime(row.get("date_received", ""), errors="coerce")
    term_days = row.get("term_days")
    if pd.isna(received) or pd.isna(term_days):
        return pd.NaT
    return received + pd.to_timedelta(int(term_days), unit="D")


def _effective_payment_date(row: pd.Series):
    scheduled = _first_valid_date(row.get("scheduled_payment_date", ""))
    if not pd.isna(scheduled):
        return scheduled
    check_date = _first_valid_date(row.get("check_date", ""))
    if not pd.isna(check_date):
        return check_date
    return pd.NaT


def _calendar_bucket(value) -> str:
    date_value = pd.to_datetime(value, errors="coerce")
    if pd.isna(date_value):
        return "NO PAYMENT DATE"
    return date_value.strftime("%Y-%m")


def _fmt_date(value) -> str:
    date_value = pd.to_datetime(value, errors="coerce")
    if pd.isna(date_value):
        return ""
    return date_value.strftime("%Y-%m-%d")


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

    for col in ["payment_status", "credit_term", "date_received", "check_date", "provider", "batch_no"]:
        if col not in df.columns:
            df[col] = ""

    df["term_days"] = df["credit_term"].apply(_term_days)
    df["scheduled_payment_date"] = df.apply(_schedule_date, axis=1)
    df["scheduled_payment_date"] = df["scheduled_payment_date"].apply(_fmt_date)

    # Calendar date rule:
    # 1. Use scheduled_payment_date when credit terms/date received can produce it.
    # 2. If missing, use check_date as fallback.
    df["calendar_payment_date"] = df.apply(_effective_payment_date, axis=1).apply(_fmt_date)
    df["payment_calendar_month"] = df["calendar_payment_date"].apply(_calendar_bucket)

    df["payment_schedule_status"] = df.apply(
        lambda row: "PAID" if str(row.get("payment_status", "")).upper() == "PAID" else "FOR PAYMENT TAGGING",
        axis=1,
    )
    df["workflow_action"] = df.apply(
        lambda row: "No action - already paid" if row["payment_schedule_status"] == "PAID" else "Processor to tag payment and target payment date",
        axis=1,
    )

    # Processor workflow fields. These are intentionally blank so processors can fill them in Excel.
    df["tagged_for_payment"] = ""
    df["processor_name"] = ""
    df["target_payment_date"] = ""
    df["tagged_date"] = ""
    df["payment_priority"] = ""
    df["payment_remarks"] = ""

    preferred = [
        "payment_calendar_month",
        "calendar_payment_date",
        "scheduled_payment_date",
        "check_date",
        "payment_schedule_status",
        "workflow_action",
        "tagged_for_payment",
        "processor_name",
        "target_payment_date",
        "tagged_date",
        "payment_priority",
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
    ]
    existing = [col for col in preferred if col in df.columns]
    schedule = df[existing + [col for col in df.columns if col not in existing]].copy()
    schedule.to_csv(reports_path / "payment_schedule_by_batch.csv", index=False)

    provider_schedule = (
        schedule.groupby(["provider", "supplier_category_name", "region", "credit_term", "payment_schedule_status"], dropna=False)
        .agg(
            latest_payment_date=("calendar_payment_date", lambda s: _fmt_date(pd.to_datetime(s, errors="coerce").dropna().max() if not pd.to_datetime(s, errors="coerce").dropna().empty else pd.NaT)),
            batch_count=("batch_no", "count"),
            claims_amount=("claims_amount", "sum"),
            expected_check_amount=("expected_check_amount", "sum"),
            check_amount=("check_amount", "sum"),
            difference=("difference", "sum"),
        )
        .reset_index()
        .sort_values(["latest_payment_date", "provider"], ascending=[False, True])
    )
    provider_schedule["payment_calendar_month"] = provider_schedule["latest_payment_date"].apply(_calendar_bucket)
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
