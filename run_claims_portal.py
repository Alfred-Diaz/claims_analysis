from __future__ import annotations

import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable

APPS = [
    ("Portal", [PYTHON, "-m", "claims_analysis.portal_app"], "http://127.0.0.1:5049"),
    ("Payment Scheduling", [PYTHON, "-m", "claims_analysis.payment_app"], "http://127.0.0.1:5050"),
    ("Budget Management", [PYTHON, "-m", "claims_analysis.budget_app"], "http://127.0.0.1:5051"),
]


def main() -> None:
    processes: list[tuple[str, subprocess.Popen]] = []
    print("Starting Claims Analysis Portal environment...")
    print("Press CTRL+C in this window to stop all apps.\n")

    try:
        for name, command, url in APPS:
            print(f"Starting {name}: {url}")
            process = subprocess.Popen(command, cwd=ROOT)
            processes.append((name, process))
            time.sleep(1.2)

        print("\nAll apps started.")
        print("Portal: http://127.0.0.1:5049")
        print("Payment Scheduling: http://127.0.0.1:5050")
        print("Budget Management: http://127.0.0.1:5051\n")
        webbrowser.open("http://127.0.0.1:5049")

        while True:
            time.sleep(1)
            for name, process in processes:
                if process.poll() is not None:
                    print(f"WARNING: {name} stopped with code {process.returncode}")
    except KeyboardInterrupt:
        print("\nStopping Claims Analysis Portal environment...")
        for name, process in processes:
            if process.poll() is None:
                print(f"Stopping {name}...")
                process.terminate()
        time.sleep(2)
        for name, process in processes:
            if process.poll() is None:
                process.kill()
        print("Stopped.")


if __name__ == "__main__":
    main()
