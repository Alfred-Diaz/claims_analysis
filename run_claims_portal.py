from __future__ import annotations

import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
HOST = "0.0.0.0"
SERVER_URL = "http://192.168.2.13"

APPS = [
    ("Portal", [PYTHON, "-m", "claims_analysis.portal_app", "--host", HOST, "--port", "5049"], f"{SERVER_URL}:5049"),
    ("Payment Scheduling", [PYTHON, "-m", "claims_analysis.payment_app", "--host", HOST, "--port", "5050"], f"{SERVER_URL}:5050"),
    ("Budget Management", [PYTHON, "-m", "claims_analysis.budget_app", "--host", HOST, "--port", "5051"], f"{SERVER_URL}:5051"),
]


def main() -> None:
    processes: list[tuple[str, subprocess.Popen]] = []
    print("Starting Claims Analysis Portal environment in NETWORK MODE...")
    print("Press CTRL+C in this window to stop all apps.\n")

    try:
        for name, command, url in APPS:
            print(f"Starting {name}: {url}")
            process = subprocess.Popen(command, cwd=ROOT)
            processes.append((name, process))
            time.sleep(1.2)

        print("\nAll apps started.")
        print(f"Portal: {SERVER_URL}:5049")
        print(f"Payment Scheduling: {SERVER_URL}:5050")
        print(f"Budget Management: {SERVER_URL}:5051\n")
        print("Users should open the Portal URL in their browser.")
        webbrowser.open(f"{SERVER_URL}:5049")

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
