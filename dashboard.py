"""Streamlit dashboard for Claims Analysis.

Run locally:
    streamlit run dashboard.py
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import traceback

import pandas as pd
import streamlit as st

from claims_analysis.analyzer import AnalysisConfig, run_analysis
from claims_analysis.database import initialize_database, save_run_to_database, search_batch


st.set_page_config(page_title="Claims Analysis", layout="wide")

st.title("Claims Analysis Dashboard")
st.caption("Analyze ERP exports, review exceptions, and search historical batch results.")

DB_PATH = "data/claims_analysis.db"
PREVIEW_ROWS = 1000

try:
    initialize_database(DB_PATH)
except Exception as exc:
    st.error("Database initialization failed.")
    st.exception(exc)
    st.stop()


def read_report(run_dir: Path, filename: str) -> pd.DataFrame:
    path = run_dir / filename
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame()


def show_preview(df: pd.DataFrame, label: str) -> None:
    if df.empty:
        st.info(f"No {label} records found.")
        return

    st.caption(f"Showing first {min(len(df), PREVIEW_ROWS):,} of {len(df):,} rows.")
    st.dataframe(df.head(PREVIEW_ROWS), use_container_width=True)


def show_kpis(summary_df: pd.DataFrame) -> None:
    if summary_df.empty:
        st.info("No summary available yet.")
        return

    summary = dict(zip(summary_df["metric"], summary_df["value"]))
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Batches", summary.get("total_batches", 0))
    col2.metric("Total Amount", summary.get("total_amount", 0))
    col3.metric("For Review", summary.get("for_review_payees", 0))
    col4.metric("Unmatched", summary.get("unmatched_batches", 0))

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Hospital", summary.get("hospital_count", 0))
    col6.metric("Professional", summary.get("professional_count", 0))
    col7.metric("Duplicate Checks", summary.get("duplicate_check_numbers", 0))
    col8.metric("Duplicate CV", summary.get("duplicate_cv_numbers", 0))


tab_analyze, tab_latest, tab_search = st.tabs(["Run Analysis", "Latest Reports", "Search History"])

with tab_analyze:
    st.subheader("Upload ERP Exports")
    st.warning(
        "For very large files, the app may take several minutes. "
        "Do not display full datasets on-screen; only previews are shown."
    )

    claims_file = st.file_uploader("Claims Process CSV", type=["csv"])
    checks_file = st.file_uploader("Check Date Created CSV", type=["csv"])

    col_a, col_b = st.columns(2)
    amount_column = col_a.text_input("Amount Column", value="amount")
    fuzzy_threshold = col_b.slider("Payee Match Threshold", min_value=0, max_value=100, value=80)

    if claims_file:
        st.caption(f"Claims Process file size: {claims_file.size / (1024 * 1024):,.2f} MB")
    if checks_file:
        st.caption(f"Check Date Created file size: {checks_file.size / (1024 * 1024):,.2f} MB")

    if st.button("Run Claims Analysis", type="primary"):
        if not claims_file or not checks_file:
            st.error("Please upload both CSV files.")
        else:
            try:
                progress = st.progress(0, text="Saving uploaded files...")
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp = Path(tmpdir)
                    claims_path = tmp / claims_file.name
                    checks_path = tmp / checks_file.name
                    claims_path.write_bytes(claims_file.getvalue())
                    checks_path.write_bytes(checks_file.getvalue())

                    progress.progress(20, text="Running claims analysis...")
                    config = AnalysisConfig(
                        amount_column=amount_column,
                        fuzzy_threshold=fuzzy_threshold,
                    )
                    run_dir = run_analysis(
                        claims_path=claims_path,
                        checks_path=checks_path,
                        output_root="reports/history",
                        config=config,
                    )

                    progress.progress(80, text="Saving results to database...")
                    run_id = save_run_to_database(
                        run_dir=run_dir,
                        claims_file=claims_file.name,
                        checks_file=checks_file.name,
                        db_path=DB_PATH,
                    )
                    progress.progress(100, text="Complete.")

                st.success(f"Analysis completed. Database run ID: {run_id}")
                st.info(f"Reports saved to: {run_dir}")

                summary_df = read_report(run_dir, "summary.csv")
                results_df = read_report(run_dir, "claims_analysis_output.csv")
                show_kpis(summary_df)
                show_preview(results_df, "result")

                excel_path = run_dir / "summary_report.xlsx"
                if excel_path.exists():
                    st.download_button(
                        "Download Excel Report",
                        data=excel_path.read_bytes(),
                        file_name="summary_report.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
            except Exception as exc:
                st.error("Analysis failed. See details below.")
                st.exception(exc)
                with st.expander("Full traceback"):
                    st.code(traceback.format_exc())

with tab_latest:
    st.subheader("Latest Reports")
    latest_dir = Path("reports/latest")

    if not latest_dir.exists():
        st.info("No latest reports found yet. Run an analysis first.")
    else:
        summary_df = read_report(latest_dir, "summary.csv")
        results_df = read_report(latest_dir, "claims_analysis_output.csv")
        for_review_df = read_report(latest_dir, "for_review.csv")
        unmatched_df = read_report(latest_dir, "unmatched_batches.csv")
        duplicate_checks_df = read_report(latest_dir, "duplicate_checks.csv")
        duplicate_cv_df = read_report(latest_dir, "duplicate_cv.csv")

        show_kpis(summary_df)

        report_tab1, report_tab2, report_tab3, report_tab4, report_tab5 = st.tabs(
            ["Results", "For Review", "Unmatched", "Duplicate Checks", "Duplicate CV"]
        )
        with report_tab1:
            show_preview(results_df, "result")
        with report_tab2:
            show_preview(for_review_df, "for review")
        with report_tab3:
            show_preview(unmatched_df, "unmatched batch")
        with report_tab4:
            show_preview(duplicate_checks_df, "duplicate check")
        with report_tab5:
            show_preview(duplicate_cv_df, "duplicate CV")

        excel_path = latest_dir / "summary_report.xlsx"
        if excel_path.exists():
            st.download_button(
                "Download Latest Excel Report",
                data=excel_path.read_bytes(),
                file_name="latest_summary_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

with tab_search:
    st.subheader("Search Batch History")
    batch_no = st.text_input("Batch No")

    if st.button("Search Batch"):
        if not batch_no.strip():
            st.warning("Enter a batch number to search.")
        else:
            try:
                results = search_batch(batch_no.strip(), db_path=DB_PATH)
                if results.empty:
                    st.info("No historical records found for this batch.")
                else:
                    show_preview(results, "historical batch")
            except Exception as exc:
                st.error("Search failed.")
                st.exception(exc)
