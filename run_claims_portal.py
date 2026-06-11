from __future__ import annotations

import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
HOST = "0.0.0.0"


def get_server_url() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    return f"http://{ip}"


SERVER_URL = get_server_url()

APPS = [
    ("Portal", [PYTHON, "-m", "claims_analysis.portal_app", "--host", HOST, "--port", "5049"], f"{SERVER_URL}:5049"),
    ("Dashboard", [PYTHON, "-m", "streamlit", "run", "dashboard.py", "--server.address", HOST, "--server.port", "8501", "--server.headless", "true"], f"{SERVER_URL}:8501"),
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
        print(f"Dashboard: {SERVER_URL}:8501")
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
