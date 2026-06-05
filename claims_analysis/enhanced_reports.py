from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def _money(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0).round(2)


def _unique_count_from_joined(value: object) -> int:
    text = "" if pd.isna(value) else str(value).strip()
    if not text:
        return 0
    return len({part.strip() for part in text.split(",") if part.strip()})


def _payment_status(row: pd.Series) -> str:
    check_no = str(row.get("check_no", "") or "").strip()
    check_date = str(row.get("check_date", "") or "").strip()
    check_amount = float(row.get("check_amount", 0) or 0)
    if check_no or check_date or check_amount > 0:
        return "PAID"
    return "UNPAID"


def _load_claim_documentation_types(claims_path: str | Path | None) -> pd.DataFrame:
    if not claims_path:
        return pd.DataFrame(columns=["batch_no", "claim_documentation_type"])
    path = Path(claims_path)
    if not path.exists():
        return pd.DataFrame(columns=["batch_no", "claim_documentation_type"])

    header = pd.read_csv(path, nrows=0)
    normalized_cols = {str(col).strip().lower().replace(" ", "_"): col for col in header.columns}
    if "batch_no" not in normalized_cols or "claim_documentation_type" not in normalized_cols:
        return pd.DataFrame(columns=["batch_no", "claim_documentation_type"])

    usecols = [normalized_cols["batch_no"], normalized_cols["claim_documentation_type"]]
    parts: list[pd.DataFrame] = []
    for chunk in pd.read_csv(path, dtype=str, usecols=usecols, chunksize=100000):
        chunk.columns = [str(col).strip().lower().replace(" ", "_") for col in chunk.columns]
        part = chunk[["batch_no", "claim_documentation_type"]].fillna("")
        part["batch_no"] = part["batch_no"].astype(str).str.strip()
        part["claim_documentation_type"] = part["claim_documentation_type"].astype(str).str.upper().str.strip()
        parts.append(part)

    if not parts:
        return pd.DataFrame(columns=["batch_no", "claim_documentation_type"])

    doc_types = pd.concat(parts, ignore_index=True)
    doc_types = doc_types[doc_types["batch_no"] != ""]
    doc_types = doc_types.drop_duplicates(subset=["batch_no"], keep="first")
    return doc_types


def enhance_reports(
    reports_dir: str | Path = "reports/latest",
    withholding_rate: float = 0.02,
    tolerance: float = 0.01,
    claims_path: str | Path | None = "data/raw/CLAIMS PROCESS-FINAL.csv",
) -> Path:
    reports_path = Path(reports_dir)
    results_path = reports_path / "claims_analysis_output.csv"
    if not results_path.exists():
        raise FileNotFoundError(f"Missing {results_path}. Run the analysis first.")

    df = pd.read_csv(results_path, dtype=str).fillna("")

    if "claim_documentation_type" not in df.columns:
        doc_types = _load_claim_documentation_types(claims_path)
        if not doc_types.empty and "batch_no" in df.columns:
            df = df.merge(doc_types, on="batch_no", how="left")
        else:
            df["claim_documentation_type"] = "REGULAR"
    df["claim_documentation_type"] = df["claim_documentation_type"].fillna("REGULAR").astype(str).str.upper().str.strip()
    df.loc[df["claim_documentation_type"] == "", "claim_documentation_type"] = "REGULAR"

    if "claims_amount" not in df.columns and "total_amount_per_batch" in df.columns:
        df["claims_amount"] = df["total_amount_per_batch"]
    if "check_amount" not in df.columns:
        df["check_amount"] = 0

    df["claims_amount"] = _money(df["claims_amount"])
    df["check_amount"] = _money(df["check_amount"])
    df["check_count"] = df["check_no"].apply(_unique_count_from_joined) if "check_no" in df.columns else 0

    # Revised business rule: multiple CVs are allowed. Only multiple checks make it Professional.
    df["supplier_category_name"] = df["check_count"].apply(lambda count: "Hospital" if int(count) <= 1 else "Professional")

    # Paid/unpaid is based on Check Date Created data populating check confirmation fields.
    df["payment_status"] = df.apply(_payment_status, axis=1)

    # Hospital only: 2% withholding. Professionals: no hospital WHT rule.
    df["withholding_tax"] = df.apply(
        lambda row: float(row["claims_amount"]) * withholding_rate if row["supplier_category_name"] == "Hospital" else 0,
        axis=1,
    )
    df["expected_check_amount"] = df["claims_amount"] - df["withholding_tax"]
    df["difference"] = df["check_amount"] - df["expected_check_amount"]
    for col in ["withholding_tax", "expected_check_amount", "difference"]:
        df[col] = _money(df[col])

    df["reconciliation_status"] = df["difference"].apply(
        lambda value: "MATCHED" if abs(round(float(value), 2)) <= tolerance else "VARIANCE"
    )

    preferred_cols = [
        "batch_no",
        "provider",
        "claim_documentation_type",
        "payment_status",
        "supplier_category_name",
        "claims_amount",
        "withholding_tax",
        "expected_check_amount",
        "check_amount",
        "difference",
        "reconciliation_status",
        "cv_no",
        "check_no",
        "check_date",
        "payee_match_status",
    ]
    existing_cols = [col for col in preferred_cols if col in df.columns]
    other_cols = [col for col in df.columns if col not in existing_cols]
    df = df[existing_cols + other_cols]

    regular = df[df["claim_documentation_type"] == "REGULAR"].copy()
    reimbursement = df[df["claim_documentation_type"] == "REIMBURSEMENT"].copy()
    paid = df[df["payment_status"] == "PAID"].copy()
    unpaid = df[df["payment_status"] == "UNPAID"].copy()
    variances = df[df["reconciliation_status"] == "VARIANCE"].copy()

    provider_totals = (
        df.groupby(["claim_documentation_type", "provider"], dropna=False)
        .agg(
            batch_count=("batch_no", "count"),
            paid_batches=("payment_status", lambda s: int((s == "PAID").sum())),
            unpaid_batches=("payment_status", lambda s: int((s == "UNPAID").sum())),
            claims_amount=("claims_amount", "sum"),
            withholding_tax=("withholding_tax", "sum"),
            expected_check_amount=("expected_check_amount", "sum"),
            check_amount=("check_amount", "sum"),
            difference=("difference", "sum"),
            variance_batch_count=("reconciliation_status", lambda s: int((s == "VARIANCE").sum())),
        )
        .reset_index()
    )
    provider_totals["provider"] = provider_totals["provider"].replace("", "UNKNOWN")
    for col in ["claims_amount", "withholding_tax", "expected_check_amount", "check_amount", "difference"]:
        provider_totals[col] = _money(provider_totals[col])
    provider_totals = provider_totals.sort_values("claims_amount", ascending=False)

    date_summary = (
        df.groupby(["claim_documentation_type", "check_date"], dropna=False)
        .agg(
            batch_count=("batch_no", "count"),
            paid_batches=("payment_status", lambda s: int((s == "PAID").sum())),
            unpaid_batches=("payment_status", lambda s: int((s == "UNPAID").sum())),
            claims_amount=("claims_amount", "sum"),
            check_amount=("check_amount", "sum"),
            difference=("difference", "sum"),
        )
        .reset_index()
    )
    date_summary["check_date"] = date_summary["check_date"].replace("", "NO CHECK DATE")
    for col in ["claims_amount", "check_amount", "difference"]:
        date_summary[col] = _money(date_summary[col])

    summary_base = regular
    summary = pd.DataFrame(
        [
            {"metric": "total_batches", "value": len(df)},
            {"metric": "regular_batches", "value": len(regular)},
            {"metric": "reimbursement_batches_excluded", "value": len(reimbursement)},
            {"metric": "paid_batches", "value": int((summary_base["payment_status"] == "PAID").sum())},
            {"metric": "unpaid_batches", "value": int((summary_base["payment_status"] == "UNPAID").sum())},
            {"metric": "hospital_count", "value": int((summary_base["supplier_category_name"] == "Hospital").sum())},
            {"metric": "professional_count", "value": int((summary_base["supplier_category_name"] == "Professional").sum())},
            {"metric": "matched_batches", "value": int((summary_base["reconciliation_status"] == "MATCHED").sum())},
            {"metric": "variance_batches", "value": int((summary_base["reconciliation_status"] == "VARIANCE").sum())},
            {"metric": "claims_total_amount", "value": round(float(summary_base["claims_amount"].sum()), 2)},
            {"metric": "withholding_tax_total", "value": round(float(summary_base["withholding_tax"].sum()), 2)},
            {"metric": "expected_check_total", "value": round(float(summary_base["expected_check_amount"].sum()), 2)},
            {"metric": "actual_check_total", "value": round(float(summary_base["check_amount"].sum()), 2)},
            {"metric": "total_difference", "value": round(float(summary_base["difference"].sum()), 2)},
            {"metric": "total_providers", "value": summary_base["provider"].nunique()},
        ]
    )

    df.to_csv(reports_path / "claims_analysis_output.csv", index=False)
    regular.to_csv(reports_path / "regular_claims.csv", index=False)
    reimbursement.to_csv(reports_path / "reimbursement_claims_excluded.csv", index=False)
    df.to_csv(reports_path / "amount_reconciliation_by_batch.csv", index=False)
    paid.to_csv(reports_path / "paid_batches.csv", index=False)
    unpaid.to_csv(reports_path / "unpaid_batches.csv", index=False)
    variances.to_csv(reports_path / "batch_variances.csv", index=False)
    provider_totals.to_csv(reports_path / "provider_amount_reconciliation.csv", index=False)
    date_summary.to_csv(reports_path / "date_created_summary.csv", index=False)
    summary.to_csv(reports_path / "summary.csv", index=False)
    summary.to_csv(reports_path / "reconciliation_summary.csv", index=False)

    return reports_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Enhance generated Claims Analysis reports with payment status, provider totals, date summaries, and documentation type filtering.")
    parser.add_argument("--reports-dir", default="reports/latest")
    parser.add_argument("--withholding-rate", type=float, default=0.02)
    parser.add_argument("--tolerance", type=float, default=0.01)
    parser.add_argument("--claims", default="data/raw/CLAIMS PROCESS-FINAL.csv", help="Claims Process CSV used to add claim_documentation_type")
    args = parser.parse_args()
    path = enhance_reports(args.reports_dir, args.withholding_rate, args.tolerance, args.claims)
    print(f"Enhanced reports written to: {path}")


if __name__ == "__main__":
    main()
