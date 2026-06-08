from __future__ import annotations

import subprocess
import sys
import webbrowser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
CLAIMS_FILE = PROJECT_ROOT / "data" / "raw" / "CLAIMS PROCESS-FINAL.csv"
CHECKS_FILE = PROJECT_ROOT / "data" / "raw" / "CHECK-DATE CREATED.csv"
DASHBOARD_FILE = PROJECT_ROOT / "reports" / "latest" / "dashboard.html"


def run_command(command: list[str], label: str) -> None:
    print("\n" + "=" * 70)
    print(label)
    print("=" * 70)
    print(" ".join(command))
    result = subprocess.run(command, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        raise SystemExit(f"\nFAILED: {label}\nExit code: {result.returncode}")


def verify_files() -> None:
    missing = []
    if not CLAIMS_FILE.exists():
        missing.append(str(CLAIMS_FILE))
    if not CHECKS_FILE.exists():
        missing.append(str(CHECKS_FILE))

    if missing:
        print("Missing required ERP files:")
        for item in missing:
            print(f"- {item}")
        print("\nPlace the ERP CSV exports inside data/raw, then run this launcher again.")
        raise SystemExit(1)


def main() -> None:
    print("Claims Analysis Dashboard Launcher")
    print(f"Project folder: {PROJECT_ROOT}")

    verify_files()

    python_exe = sys.executable

    run_command(
        [
            python_exe,
            "app.py",
            "--large",
            "--claims",
            str(CLAIMS_FILE),
            "--checks",
            str(CHECKS_FILE),
            "--amount-col",
            "amount_payable",
            "--check-amount-col",
            "check_amount",
        ],
        "Running claims reconciliation",
    )

    run_command(
        [
            python_exe,
            "-m",
            "claims_analysis.enhanced_reports",
            "--reports-dir",
            "reports/latest",
            "--claims",
            str(CLAIMS_FILE),
        ],
        "Generating enhanced reports",
    )

    run_command(
        [
            python_exe,
            "-m",
            "claims_analysis.html_dashboard",
            "--reports-dir",
            "reports/latest",
        ],
        "Generating HTML dashboard",
    )

    if not DASHBOARD_FILE.exists():
        raise SystemExit(f"Dashboard was not created: {DASHBOARD_FILE}")

    print("\nOpening dashboard...")
    webbrowser.open(DASHBOARD_FILE.resolve().as_uri())
    print("Done.")
    print(f"Dashboard: {DASHBOARD_FILE}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        raise SystemExit(130)
