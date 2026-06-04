"""Amount reconciliation reports for Claims Analysis.

Business rule:
- Match Claims Process.batch_no to Check Date Created.batch_no.
- Sum Claims Process.amount_payable per batch.
- Sum Check Date Created.check_amount per batch.
- Compare the two amounts.
- Summarize totals by provider.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


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


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    return df


def generate_reconciliation_reports(
    claims_path: str | Path,
    checks_path: str | Path,
    output_dir: str | Path,
    claims_amount_col: str = "amount_payable",
    checks_amount_col: str = "check_amount",
    chunksize: int = 100000,
) -> dict[str, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    claims_parts: list[pd.DataFrame] = []
    for chunk in pd.read_csv(claims_path, dtype=str, chunksize=chunksize):
        chunk = normalize_columns(chunk)
        part = pd.DataFrame(
            {
                "batch_no_key": chunk["batch_no"].fillna("").astype(str).str.lower().str.strip(),
                "batch_no": chunk["batch_no"].fillna("").astype(str).str.strip(),
                "provider": chunk["provider"].fillna("").astype(str).str.strip(),
                "claims_amount": clean_amount_series(chunk[claims_amount_col]),
            }
        )
        claims_parts.append(part)

    checks_parts: list[pd.DataFrame] = []
    for chunk in pd.read_csv(checks_path, dtype=str, chunksize=chunksize):
        chunk = normalize_columns(chunk)
        part = pd.DataFrame(
            {
                "batch_no_key": chunk["batch_no"].fillna("").astype(str).str.lower().str.strip(),
                "check_amount": clean_amount_series(chunk[checks_amount_col]),
            }
        )
        checks_parts.append(part)

    claims = pd.concat(claims_parts, ignore_index=True) if claims_parts else pd.DataFrame()
    checks = pd.concat(checks_parts, ignore_index=True) if checks_parts else pd.DataFrame()

    claims_batch = (
        claims.groupby("batch_no_key", dropna=False)
        .agg(
            batch_no=("batch_no", "first"),
            provider=("provider", "first"),
            claims_amount=("claims_amount", "sum"),
        )
        .reset_index()
    )

    checks_batch = (
        checks.groupby("batch_no_key", dropna=False)
        .agg(check_amount=("check_amount", "sum"))
        .reset_index()
    )

    reconciliation = claims_batch.merge(checks_batch, on="batch_no_key", how="left")
    reconciliation["check_amount"] = reconciliation["check_amount"].fillna(0)
    reconciliation["difference"] = reconciliation["claims_amount"] - reconciliation["check_amount"]
    reconciliation["reconciliation_status"] = reconciliation["difference"].apply(
        lambda value: "MATCHED" if round(float(value), 2) == 0 else "VARIANCE"
    )

    reconciliation = reconciliation[
        [
            "batch_no",
            "provider",
            "claims_amount",
            "check_amount",
            "difference",
            "reconciliation_status",
        ]
    ].copy()

    for col in ["claims_amount", "check_amount", "difference"]:
        reconciliation[col] = pd.to_numeric(reconciliation[col], errors="coerce").fillna(0).round(2)

    provider_reconciliation = (
        reconciliation.groupby("provider", dropna=False)
        .agg(
            batch_count=("batch_no", "count"),
            claims_amount=("claims_amount", "sum"),
            check_amount=("check_amount", "sum"),
            difference=("difference", "sum"),
            variance_batch_count=("reconciliation_status", lambda s: int((s == "VARIANCE").sum())),
        )
        .reset_index()
    )
    provider_reconciliation["provider"] = provider_reconciliation["provider"].replace("", "UNKNOWN")
    for col in ["claims_amount", "check_amount", "difference"]:
        provider_reconciliation[col] = pd.to_numeric(provider_reconciliation[col], errors="coerce").fillna(0).round(2)
    provider_reconciliation = provider_reconciliation.sort_values("claims_amount", ascending=False)

    summary = pd.DataFrame(
        [
            {"metric": "total_batches", "value": len(reconciliation)},
            {"metric": "matched_batches", "value": int((reconciliation["reconciliation_status"] == "MATCHED").sum())},
            {"metric": "variance_batches", "value": int((reconciliation["reconciliation_status"] == "VARIANCE").sum())},
            {"metric": "claims_total_amount", "value": round(float(reconciliation["claims_amount"].sum()), 2)},
            {"metric": "check_total_amount", "value": round(float(reconciliation["check_amount"].sum()), 2)},
            {"metric": "total_difference", "value": round(float(reconciliation["difference"].sum()), 2)},
            {"metric": "total_providers", "value": provider_reconciliation["provider"].nunique()},
        ]
    )

    reconciliation_path = output_path / "amount_reconciliation_by_batch.csv"
    provider_path = output_path / "provider_amount_reconciliation.csv"
    summary_path = output_path / "reconciliation_summary.csv"

    reconciliation.to_csv(reconciliation_path, index=False)
    provider_reconciliation.to_csv(provider_path, index=False)
    summary.to_csv(summary_path, index=False)

    return {
        "amount_reconciliation_by_batch": reconciliation_path,
        "provider_amount_reconciliation": provider_path,
        "reconciliation_summary": summary_path,
    }
