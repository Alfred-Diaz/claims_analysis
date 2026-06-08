from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from claims_analysis.business_rules import aging_bucket, aging_days, credit_term_for_provider, mpsu_tag_for_provider


DEFAULT_SUPPLIERS_PATH = "data/master/EastWest-ERP-Suppliers-20260504_103929.csv"
ENRICHMENT_COLUMNS = [
    "supplier_master_name",
    "provider_code",
    "supplier_type",
    "supplier_category_source",
    "city",
    "province",
    "region",
    "payment_term",
]


def _money(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0).round(2)


def _scalar(value: object) -> object:
    if isinstance(value, pd.Series):
        for item in value.tolist():
            if not pd.isna(item) and str(item).strip() != "":
                return item
        return ""
    return value


def _norm(value: object) -> str:
    value = _scalar(value)
    return "" if pd.isna(value) else str(value).strip().upper()


def _norm_key(value: object) -> str:
    return " ".join(_norm(value).replace(".", "").replace(",", " ").split())


def _unique_count_from_joined(value: object) -> int:
    text = "" if pd.isna(value) else str(value).strip()
    if not text:
        return 0
    return len({part.strip() for part in text.split(",") if part.strip()})


def _payment_status(row: pd.Series) -> str:
    check_no = str(_scalar(row.get("check_no", "")) or "").strip()
    check_date = str(_scalar(row.get("check_date", "")) or "").strip()
    check_amount = float(_scalar(row.get("check_amount", 0)) or 0)
    if check_no or check_date or check_amount > 0:
        return "PAID"
    return "UNPAID"


def _load_claim_claims_fields(claims_path: str | Path | None) -> pd.DataFrame:
    columns = ["batch_no", "claim_documentation_type", "date_received"]
    if not claims_path:
        return pd.DataFrame(columns=columns)
    path = Path(claims_path)
    if not path.exists():
        return pd.DataFrame(columns=columns)

    header = pd.read_csv(path, nrows=0)
    normalized_cols = {str(col).strip().lower().replace(" ", "_"): col for col in header.columns}
    if "batch_no" not in normalized_cols:
        return pd.DataFrame(columns=columns)

    usecols = [normalized_cols["batch_no"]]
    for optional in ["claim_documentation_type", "date_received"]:
        if optional in normalized_cols:
            usecols.append(normalized_cols[optional])

    parts: list[pd.DataFrame] = []
    for chunk in pd.read_csv(path, dtype=str, usecols=usecols, chunksize=100000):
        chunk.columns = [str(col).strip().lower().replace(" ", "_") for col in chunk.columns]
        if "claim_documentation_type" not in chunk.columns:
            chunk["claim_documentation_type"] = "REGULAR"
        if "date_received" not in chunk.columns:
            chunk["date_received"] = ""
        part = chunk[columns].fillna("")
        part["batch_no"] = part["batch_no"].astype(str).str.strip()
        part["claim_documentation_type"] = part["claim_documentation_type"].astype(str).str.upper().str.strip()
        part["date_received"] = part["date_received"].astype(str).str.strip()
        parts.append(part)

    if not parts:
        return pd.DataFrame(columns=columns)

    out = pd.concat(parts, ignore_index=True)
    out = out[out["batch_no"] != ""]
    out = out.drop_duplicates(subset=["batch_no"], keep="first")
    return out


def _classify_supplier(provider: object, doc_type: object, supplier_type: object = "", category_name: object = "", source_category: object = "") -> str:
    doc = _norm(doc_type)
    supplier_type = _norm(supplier_type)
    category = _norm(category_name)
    source = _norm(source_category)
    provider_text = _norm(provider)

    if doc == "REIMBURSEMENT" or "REIMBURSE" in source or "REIMBURSE" in category:
        return "REIMBURSEMENT"
    if supplier_type == "IND" or category == "PROFESSIONAL" or "PROF" in category or "PROF" in source:
        return "PROFESSIONAL FEES"
    if "DENTAL CLINIC" in provider_text or "DENTAL CLINIC" in source:
        return "DENTAL CLINIC"
    if "DENTAL" in provider_text or "DENTIST" in provider_text or "DENTAL" in source or "DENTIST" in source:
        return "DENTAL CLINIC"
    if "CLINIC" in provider_text or "DIAGNOSTIC" in provider_text or "CLINIC" in source:
        return "CLINICS"
    return "HOSPITAL"


def _load_supplier_master(suppliers_path: str | Path | None) -> pd.DataFrame:
    if not suppliers_path:
        return pd.DataFrame()
    path = Path(suppliers_path)
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path, dtype=str).fillna("")
    df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]
    for col in ["name", "org_name", "type", "category_name", "city", "state", "region", "payment_term", "provider_code"]:
        if col not in df.columns:
            df[col] = ""

    df["supplier_display_name"] = df.apply(lambda r: r["org_name"] if str(r["org_name"]).strip() else r["name"], axis=1)
    df["supplier_key"] = df["supplier_display_name"].apply(_norm_key)
    df = df[df["supplier_key"] != ""]
    df = df.drop_duplicates(subset=["supplier_key"], keep="first")
    return df[["supplier_key", "supplier_display_name", "provider_code", "type", "category_name", "city", "state", "region", "payment_term"]]


def _drop_existing_enrichment_columns(df: pd.DataFrame) -> pd.DataFrame:
    drop_cols = [col for col in ENRICHMENT_COLUMNS + ["provider_key", "supplier_key"] if col in df.columns]
    if drop_cols:
        return df.drop(columns=drop_cols)
    return df


def _enrich_with_supplier_master(df: pd.DataFrame, suppliers_path: str | Path | None) -> pd.DataFrame:
    master = _load_supplier_master(suppliers_path)
    df = _drop_existing_enrichment_columns(df.copy())
    df["provider_key"] = df["provider"].apply(_norm_key)

    if master.empty:
        for col in ENRICHMENT_COLUMNS:
            df[col] = ""
        return df.drop(columns=["provider_key"])

    enriched = df.merge(master, left_on="provider_key", right_on="supplier_key", how="left")
    enriched = enriched.rename(
        columns={
            "supplier_display_name": "supplier_master_name",
            "type": "supplier_type",
            "category_name": "supplier_category_source",
            "state": "province",
        }
    )
    for col in ENRICHMENT_COLUMNS:
        if col not in enriched.columns:
            enriched[col] = ""
        enriched[col] = enriched[col].fillna("").astype(str).str.strip()
    return enriched.drop(columns=[col for col in ["provider_key", "supplier_key"] if col in enriched.columns])


def enhance_reports(
    reports_dir: str | Path = "reports/latest",
    withholding_rate: float = 0.02,
    tolerance: float = 0.01,
    claims_path: str | Path | None = "data/raw/CLAIMS PROCESS-FINAL.csv",
    suppliers_path: str | Path | None = DEFAULT_SUPPLIERS_PATH,
) -> Path:
    reports_path = Path(reports_dir)
    results_path = reports_path / "claims_analysis_output.csv"
    if not results_path.exists():
        raise FileNotFoundError(f"Missing {results_path}. Run the analysis first.")

    df = pd.read_csv(results_path, dtype=str).fillna("")

    claims_fields = _load_claim_claims_fields(claims_path)
    if not claims_fields.empty and "batch_no" in df.columns:
        for col in ["claim_documentation_type", "date_received"]:
            if col in df.columns:
                df = df.drop(columns=[col])
        df = df.merge(claims_fields, on="batch_no", how="left")

    if "claim_documentation_type" not in df.columns:
        df["claim_documentation_type"] = "REGULAR"
    if "date_received" not in df.columns:
        df["date_received"] = ""
    df["claim_documentation_type"] = df["claim_documentation_type"].fillna("REGULAR").astype(str).str.upper().str.strip()
    df.loc[df["claim_documentation_type"] == "", "claim_documentation_type"] = "REGULAR"

    if "claims_amount" not in df.columns and "total_amount_per_batch" in df.columns:
        df["claims_amount"] = df["total_amount_per_batch"]
    if "check_amount" not in df.columns:
        df["check_amount"] = 0

    source_supplier_category = df["supplier_category_name"].copy() if "supplier_category_name" in df.columns else pd.Series([""] * len(df))
    df = _enrich_with_supplier_master(df, suppliers_path)
    df["source_supplier_category"] = source_supplier_category.values

    df["claims_amount"] = _money(df["claims_amount"])
    df["check_amount"] = _money(df["check_amount"])
    df["check_count"] = df["check_no"].apply(_unique_count_from_joined) if "check_no" in df.columns else 0

    df["supplier_category_name"] = df.apply(
        lambda row: _classify_supplier(
            row.get("provider", ""),
            row.get("claim_documentation_type", ""),
            row.get("supplier_type", ""),
            row.get("supplier_category_source", ""),
            row.get("source_supplier_category", ""),
        ),
        axis=1,
    )

    df["credit_term"] = df.apply(
        lambda row: str(_scalar(row.get("payment_term", ""))).strip() or credit_term_for_provider(row.get("provider", "")),
        axis=1,
    )
    df["mpsu_tag"] = df.apply(lambda row: mpsu_tag_for_provider(row.get("provider", "")), axis=1)
    df["aging_days"] = df["date_received"].apply(aging_days)
    df["aging_bucket"] = df["date_received"].apply(aging_bucket)

    df["payment_status"] = df.apply(_payment_status, axis=1)
    df["withholding_tax"] = df.apply(
        lambda row: float(row["claims_amount"]) * withholding_rate if row["supplier_category_name"] == "HOSPITAL" else 0,
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
        "supplier_master_name",
        "provider_code",
        "claim_documentation_type",
        "supplier_category_name",
        "supplier_type",
        "supplier_category_source",
        "region",
        "province",
        "city",
        "date_received",
        "aging_days",
        "aging_bucket",
        "credit_term",
        "mpsu_tag",
        "payment_status",
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
    other_cols = [col for col in df.columns if col not in existing_cols and col != "source_supplier_category"]
    df = df[existing_cols + other_cols]

    regular = df[df["claim_documentation_type"] == "REGULAR"].copy()
    reimbursement = df[df["claim_documentation_type"] == "REIMBURSEMENT"].copy()
    paid = df[df["payment_status"] == "PAID"].copy()
    unpaid = df[df["payment_status"] == "UNPAID"].copy()
    variances = df[df["reconciliation_status"] == "VARIANCE"].copy()

    group_cols = ["claim_documentation_type", "supplier_category_name", "region", "credit_term", "mpsu_tag", "provider"]
    provider_totals = (
        df.groupby(group_cols, dropna=False)
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
        df.groupby(["claim_documentation_type", "supplier_category_name", "region", "aging_bucket", "date_received"], dropna=False)
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
    for col in ["claims_amount", "check_amount", "difference"]:
        date_summary[col] = _money(date_summary[col])

    aging_summary = (
        df.groupby(["claim_documentation_type", "aging_bucket"], dropna=False)
        .agg(batch_count=("batch_no", "count"), claims_amount=("claims_amount", "sum"), check_amount=("check_amount", "sum"))
        .reset_index()
    )
    for col in ["claims_amount", "check_amount"]:
        aging_summary[col] = _money(aging_summary[col])

    summary_base = regular
    summary = pd.DataFrame(
        [
            {"metric": "total_batches", "value": len(df)},
            {"metric": "regular_batches", "value": len(regular)},
            {"metric": "reimbursement_batches_excluded", "value": len(reimbursement)},
            {"metric": "paid_batches", "value": int((summary_base["payment_status"] == "PAID").sum())},
            {"metric": "unpaid_batches", "value": int((summary_base["payment_status"] == "UNPAID").sum())},
            {"metric": "hospital_count", "value": int((summary_base["supplier_category_name"] == "HOSPITAL").sum())},
            {"metric": "clinic_count", "value": int((summary_base["supplier_category_name"] == "CLINICS").sum())},
            {"metric": "dental_clinic_count", "value": int((summary_base["supplier_category_name"] == "DENTAL CLINIC").sum())},
            {"metric": "professional_fees_count", "value": int((summary_base["supplier_category_name"] == "PROFESSIONAL FEES").sum())},
            {"metric": "above_120_days", "value": int((summary_base["aging_bucket"] == "ABOVE 120 DAYS").sum())},
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
    aging_summary.to_csv(reports_path / "aging_analysis.csv", index=False)
    summary.to_csv(reports_path / "summary.csv", index=False)
    summary.to_csv(reports_path / "reconciliation_summary.csv", index=False)

    return reports_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Enhance generated Claims Analysis reports with supplier master, region, aging, and payment terms.")
    parser.add_argument("--reports-dir", default="reports/latest")
    parser.add_argument("--withholding-rate", type=float, default=0.02)
    parser.add_argument("--tolerance", type=float, default=0.01)
    parser.add_argument("--claims", default="data/raw/CLAIMS PROCESS-FINAL.csv")
    parser.add_argument("--suppliers", default=DEFAULT_SUPPLIERS_PATH)
    args = parser.parse_args()
    path = enhance_reports(args.reports_dir, args.withholding_rate, args.tolerance, args.claims, args.suppliers)
    print(f"Enhanced reports written to: {path}")


if __name__ == "__main__":
    main()
