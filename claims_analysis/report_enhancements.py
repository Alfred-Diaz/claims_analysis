"""Additional business-summary reports for Claims Analysis.

These reports focus on the original operations concern:
- total amount of all matched batch numbers
- total amount per provider
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def _read_results(run_dir: Path) -> pd.DataFrame:
    path = run_dir / "claims_analysis_output.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


def generate_business_reports(run_dir: str | Path) -> dict[str, Path]:
    """Create matched-batch total and provider-total CSV files."""
    run_path = Path(run_dir)
    df = _read_results(run_path)

    matched_summary_path = run_path / "matched_batch_totals.csv"
    provider_totals_path = run_path / "provider_totals.csv"

    if df.empty:
        pd.DataFrame(
            [{"metric": "matched_batch_count", "value": 0}, {"metric": "matched_total_amount", "value": 0}]
        ).to_csv(matched_summary_path, index=False)
        pd.DataFrame(columns=["provider", "batch_count", "total_amount"]).to_csv(provider_totals_path, index=False)
        return {"matched_batch_totals": matched_summary_path, "provider_totals": provider_totals_path}

    df["total_amount_per_batch"] = pd.to_numeric(df["total_amount_per_batch"], errors="coerce").fillna(0)

    matched = df[df["check_no"].fillna("").astype(str).str.strip() != ""].copy()

    matched_summary = pd.DataFrame(
        [
            {"metric": "matched_batch_count", "value": len(matched)},
            {"metric": "matched_total_amount", "value": round(float(matched["total_amount_per_batch"].sum()), 2)},
        ]
    )
    matched_summary.to_csv(matched_summary_path, index=False)

    provider_totals = (
        df.groupby("provider", dropna=False)
        .agg(
            batch_count=("batch_no", "count"),
            total_amount=("total_amount_per_batch", "sum"),
        )
        .reset_index()
    )
    provider_totals["provider"] = provider_totals["provider"].replace("", "UNKNOWN")
    provider_totals["total_amount"] = provider_totals["total_amount"].round(2)
    provider_totals = provider_totals.sort_values("total_amount", ascending=False)
    provider_totals.to_csv(provider_totals_path, index=False)

    return {"matched_batch_totals": matched_summary_path, "provider_totals": provider_totals_path}
