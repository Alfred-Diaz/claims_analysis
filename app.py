"""Command-line entry point for Claims Analysis.

Example:
    python app.py --claims "data/raw/claims_process.csv" --checks "data/raw/check_date_created.csv"
"""

from __future__ import annotations

import argparse
from claims_analysis.analyzer import AnalysisConfig, run_analysis


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Claims Analysis reports.")
    parser.add_argument("--claims", required=True, help="Path to Claims Process CSV export")
    parser.add_argument("--checks", required=True, help="Path to Check Date Created CSV export")
    parser.add_argument("--amount-col", default="amount", help="Amount column in Claims Process export")
    parser.add_argument("--fuzzy-threshold", type=int, default=80, help="Payee fuzzy match threshold, 0-100")
    parser.add_argument("--output-root", default="reports/history", help="Folder for timestamped reports")

    args = parser.parse_args()

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

    print(f"\nDone. Reports generated in: {run_dir}")
    print("Latest report copies are available in: reports/latest")


if __name__ == "__main__":
    main()
