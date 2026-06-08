from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


DEFAULT_CLAIMS_PATH = "data/raw/CLAIMS PROCESS-FINAL.csv"
DEFAULT_MASTER_PATH = "data/master/provider_region_master.csv"


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]
    return df


def generate_provider_region_master(
    claims_path: str | Path = DEFAULT_CLAIMS_PATH,
    output_path: str | Path = DEFAULT_MASTER_PATH,
) -> Path:
    claims_path = Path(claims_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not claims_path.exists():
        raise FileNotFoundError(f"Claims file not found: {claims_path}")

    header = pd.read_csv(claims_path, nrows=0)
    normalized = {str(col).strip().lower().replace(" ", "_"): col for col in header.columns}
    if "provider" not in normalized:
        raise ValueError("Claims file must contain a provider column.")

    usecols = [normalized["provider"]]
    if "claim_documentation_type" in normalized:
        usecols.append(normalized["claim_documentation_type"])
    if "supplier_category_name" in normalized:
        usecols.append(normalized["supplier_category_name"])

    parts: list[pd.DataFrame] = []
    for chunk in pd.read_csv(claims_path, dtype=str, usecols=usecols, chunksize=100000):
        chunk = _normalize_columns(chunk).fillna("")
        if "claim_documentation_type" not in chunk.columns:
            chunk["claim_documentation_type"] = ""
        if "supplier_category_name" not in chunk.columns:
            chunk["supplier_category_name"] = ""
        chunk["provider"] = chunk["provider"].astype(str).str.strip()
        chunk = chunk[chunk["provider"] != ""]
        parts.append(chunk[["provider", "claim_documentation_type", "supplier_category_name"]])

    if not parts:
        master = pd.DataFrame(columns=["provider", "region", "province", "city", "supplier_category_override", "credit_term_override", "mpsu_tag_override", "notes"])
    else:
        raw = pd.concat(parts, ignore_index=True)
        grouped = (
            raw.groupby("provider", dropna=False)
            .agg(
                claim_documentation_type=("claim_documentation_type", lambda s: ", ".join(sorted({str(x).strip() for x in s if str(x).strip()}))),
                supplier_category_source=("supplier_category_name", lambda s: ", ".join(sorted({str(x).strip() for x in s if str(x).strip()}))),
            )
            .reset_index()
            .sort_values("provider")
        )
        grouped.insert(1, "region", "")
        grouped.insert(2, "province", "")
        grouped.insert(3, "city", "")
        grouped["supplier_category_override"] = ""
        grouped["credit_term_override"] = ""
        grouped["mpsu_tag_override"] = ""
        grouped["notes"] = ""
        master = grouped

    if output_path.exists():
        existing = pd.read_csv(output_path, dtype=str).fillna("")
        if "provider" in existing.columns:
            preserve_cols = [col for col in ["provider", "region", "province", "city", "supplier_category_override", "credit_term_override", "mpsu_tag_override", "notes"] if col in existing.columns]
            master = master.merge(existing[preserve_cols].drop_duplicates("provider"), on="provider", how="left", suffixes=("", "_existing"))
            for col in ["region", "province", "city", "supplier_category_override", "credit_term_override", "mpsu_tag_override", "notes"]:
                existing_col = f"{col}_existing"
                if existing_col in master.columns:
                    master[col] = master[existing_col].fillna(master[col]).replace("", master[col])
                    master = master.drop(columns=[existing_col])

    master.to_csv(output_path, index=False)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate provider_region_master.csv from Claims Process providers.")
    parser.add_argument("--claims", default=DEFAULT_CLAIMS_PATH)
    parser.add_argument("--output", default=DEFAULT_MASTER_PATH)
    args = parser.parse_args()
    path = generate_provider_region_master(args.claims, args.output)
    print(f"Provider region master generated: {path}")
    print("Fill the region/province/city columns, then rerun enhanced_reports and html_dashboard.")


if __name__ == "__main__":
    main()
