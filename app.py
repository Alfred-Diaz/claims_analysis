from __future__ import annotations

import argparse

from claims_analysis.analyzer import AnalysisConfig, run_analysis
from claims_analysis.large_reconciliation_engine import run_large_reconciliation


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Claims Analysis reports.")
    parser.add_argument("--claims", required=True, help="Path to Claims Process CSV export")
    parser.add_argument("--checks", required=True, help="Path to Check Date Created CSV export")
    parser.add_argument("--amount-col", default="amount_payable", help="Amount column in Claims Process export")
    parser.add_argument("--check-amount-col", default="check_amount", help="Amount column in Check Date Created export")
    parser.add_argument("--fuzzy-threshold", type=int, default=80, help="Payee fuzzy match threshold")
    parser.add_argument("--output-root", default="reports/history", help="Folder for timestamped reports")
    parser.add_argument("--large", action="store_true", help="Use large reconciliation processing mode")
    parser.add_argument("--chunksize", type=int, default=100000, help="Rows per chunk in large mode")
    parser.add_argument("--staging-db", default="data/large_staging.db", help="SQLite staging database path")
    parser.add_argument("--hospital-wht-rate", type=float, default=0.02, help="Hospital withholding tax rate")
    parser.add_argument("--tolerance", type=float, default=0.01, help="Allowed amount variance")

    args = parser.parse_args()

    if args.large:
        run_dir = run_large_reconciliation(
            claims_path=args.claims,
            checks_path=args.checks,
            output_root=args.output_root,
            db_path=args.staging_db,
            amount_column=args.amount_col,
            check_amount_column=args.check_amount_col,
            fuzzy_threshold=args.fuzzy_threshold,
            chunksize=args.chunksize,
            hospital_withholding_rate=args.hospital_wht_rate,
            tolerance=args.tolerance,
        )
    else:
        config = AnalysisConfig(
            amount_column=args.amount_col,
            fuzzy_threshold=args.fuzzy_threshold,
        )
        run_dir = run_analysis(
            claims_path=args.claims,
            checks_path=args.checks,
            output_root=args.output_root,
            config=config,
        )

    print(f"Done. Reports generated in: {run_dir}")
    print("Latest report copies are available in: reports/latest")


if __name__ == "__main__":
    main()
