from __future__ import annotations

import subprocess
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from claims_analysis.large_reconciliation_engine import run_large_reconciliation
from claims_analysis.html_dashboard import generate_dashboard


class AnalysisWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)
    log = Signal(str)

    def __init__(self, claims_file: str, checks_file: str, amount_col: str, check_amount_col: str):
        super().__init__()
        self.claims_file = claims_file
        self.checks_file = checks_file
        self.amount_col = amount_col
        self.check_amount_col = check_amount_col

    def run(self) -> None:
        try:
            self.log.emit("Starting claims reconciliation...")
            self.log.emit(f"Claims Process: {self.claims_file}")
            self.log.emit(f"Check Date Created: {self.checks_file}")
            self.log.emit("This may take several minutes for large ERP files.")

            run_dir = run_large_reconciliation(
                claims_path=self.claims_file,
                checks_path=self.checks_file,
                amount_column=self.amount_col,
                check_amount_column=self.check_amount_col,
                output_root="reports/history",
                db_path="data/large_staging.db",
                chunksize=100000,
                hospital_withholding_rate=0.02,
                tolerance=0.01,
            )

            self.log.emit(f"Reports generated: {run_dir}")
            self.log.emit("Generating HTML dashboard...")
            dashboard_path = generate_dashboard("reports/latest")
            self.log.emit(f"Dashboard generated: {dashboard_path}")
            self.finished.emit(str(dashboard_path))
        except Exception:
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Claims Analysis Desktop")
        self.resize(900, 650)
        self.worker_thread: QThread | None = None
        self.worker: AnalysisWorker | None = None
        self.dashboard_path: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        title = QLabel("Claims Analysis Desktop")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        subtitle = QLabel("Select ERP CSV files, run reconciliation, and open the generated dashboard.")
        layout.addWidget(subtitle)

        file_box = QGroupBox("ERP Files")
        file_layout = QGridLayout(file_box)

        self.claims_input = QLineEdit()
        self.claims_input.setPlaceholderText("Select CLAIMS PROCESS-FINAL.csv")
        claims_btn = QPushButton("Browse")
        claims_btn.clicked.connect(self.browse_claims)

        self.checks_input = QLineEdit()
        self.checks_input.setPlaceholderText("Select CHECK-DATE CREATED.csv")
        checks_btn = QPushButton("Browse")
        checks_btn.clicked.connect(self.browse_checks)

        file_layout.addWidget(QLabel("Claims Process:"), 0, 0)
        file_layout.addWidget(self.claims_input, 0, 1)
        file_layout.addWidget(claims_btn, 0, 2)
        file_layout.addWidget(QLabel("Check Date Created:"), 1, 0)
        file_layout.addWidget(self.checks_input, 1, 1)
        file_layout.addWidget(checks_btn, 1, 2)
        layout.addWidget(file_box)

        settings_box = QGroupBox("Settings")
        settings_layout = QGridLayout(settings_box)
        self.amount_col_input = QLineEdit("amount_payable")
        self.check_amount_col_input = QLineEdit("check_amount")
        settings_layout.addWidget(QLabel("Claims amount column:"), 0, 0)
        settings_layout.addWidget(self.amount_col_input, 0, 1)
        settings_layout.addWidget(QLabel("Check amount column:"), 1, 0)
        settings_layout.addWidget(self.check_amount_col_input, 1, 1)
        settings_layout.addWidget(QLabel("Hospital withholding:"), 2, 0)
        settings_layout.addWidget(QLabel("2% automatically applied to Hospital batches"), 2, 1)
        layout.addWidget(settings_box)

        self.run_button = QPushButton("Run Analysis and Open Dashboard")
        self.run_button.setMinimumHeight(42)
        self.run_button.clicked.connect(self.run_analysis)
        layout.addWidget(self.run_button)

        self.open_reports_button = QPushButton("Open Reports Folder")
        self.open_reports_button.clicked.connect(self.open_reports_folder)
        layout.addWidget(self.open_reports_button)

        self.open_dashboard_button = QPushButton("Open Latest Dashboard")
        self.open_dashboard_button.clicked.connect(self.open_latest_dashboard)
        layout.addWidget(self.open_dashboard_button)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Logs will appear here...")
        layout.addWidget(self.log_output)

        self.setCentralWidget(root)

    def browse_claims(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Claims Process CSV", "data/raw", "CSV Files (*.csv)")
        if path:
            self.claims_input.setText(path)

    def browse_checks(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Check Date Created CSV", "data/raw", "CSV Files (*.csv)")
        if path:
            self.checks_input.setText(path)

    def append_log(self, message: str) -> None:
        self.log_output.append(message)

    def run_analysis(self) -> None:
        claims_file = self.claims_input.text().strip()
        checks_file = self.checks_input.text().strip()
        amount_col = self.amount_col_input.text().strip() or "amount_payable"
        check_amount_col = self.check_amount_col_input.text().strip() or "check_amount"

        if not claims_file or not Path(claims_file).exists():
            QMessageBox.warning(self, "Missing file", "Please select a valid Claims Process CSV file.")
            return
        if not checks_file or not Path(checks_file).exists():
            QMessageBox.warning(self, "Missing file", "Please select a valid Check Date Created CSV file.")
            return

        self.run_button.setEnabled(False)
        self.log_output.clear()
        self.append_log("Running. Please wait...")

        self.worker_thread = QThread()
        self.worker = AnalysisWorker(claims_file, checks_file, amount_col, check_amount_col)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.log.connect(self.append_log)
        self.worker.finished.connect(self.analysis_finished)
        self.worker.failed.connect(self.analysis_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.start()

    def analysis_finished(self, dashboard_path: str) -> None:
        self.dashboard_path = dashboard_path
        self.run_button.setEnabled(True)
        self.append_log("Done.")
        self.open_file(dashboard_path)

    def analysis_failed(self, error_text: str) -> None:
        self.run_button.setEnabled(True)
        self.append_log("FAILED")
        self.append_log(error_text)
        QMessageBox.critical(self, "Analysis failed", "The analysis failed. Check the log box for details.")

    def open_file(self, path: str) -> None:
        target = str(Path(path).resolve())
        if sys.platform.startswith("win"):
            subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
        else:
            subprocess.Popen(["xdg-open", target])

    def open_reports_folder(self) -> None:
        Path("reports/latest").mkdir(parents=True, exist_ok=True)
        self.open_file("reports/latest")

    def open_latest_dashboard(self) -> None:
        dashboard = Path("reports/latest/dashboard.html")
        if dashboard.exists():
            self.open_file(str(dashboard))
        else:
            QMessageBox.information(self, "Dashboard not found", "Generate the dashboard first by running the analysis.")


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
