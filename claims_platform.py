from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Claims Analysis Platform", layout="wide")

REPORTS_DIR = Path("reports/latest")
PREVIEW_ROWS = 1000


def money(value) -> str:
    try:
        return f"PHP {float(value or 0):,.2f}"
    except Exception:
        return "PHP 0.00"


def read_report(filename: str) -> pd.DataFrame:
    path = REPORTS_DIR / filename
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame()


def show_preview(df: pd.DataFrame, label: str) -> None:
    if df.empty:
        st.info(f"No {label} records found.")
        return
    q = st.text_input(f"Search {label}", key=f"search_{label}")
    view = df
    if q:
        mask = df.astype(str).apply(lambda s: s.str.contains(q, case=False, na=False)).any(axis=1)
        view = df[mask]
    st.caption(f"Showing first {min(len(view), PREVIEW_ROWS):,} of {len(view):,} rows.")
    st.dataframe(view.head(PREVIEW_ROWS), use_container_width=True, height=520)


def show_kpis(summary_df: pd.DataFrame) -> None:
    if summary_df.empty:
        st.info("No summary available yet.")
        return
    summary = dict(zip(summary_df["metric"], summary_df["value"]))
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Batches", f"{int(float(summary.get('total_batches', 0))):,}")
    col2.metric("Total Amount", money(summary.get("total_amount", 0)))
    col3.metric("For Review", f"{int(float(summary.get('for_review_payees', 0))):,}")
    col4.metric("Unmatched", f"{int(float(summary.get('unmatched_batches', 0))):,}")
    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Hospital", summary.get("hospital_count", 0))
    col6.metric("Professional", summary.get("professional_count", 0))
    col7.metric("Duplicate Checks", summary.get("duplicate_check_numbers", 0))
    col8.metric("Duplicate CV", summary.get("duplicate_cv_numbers", 0))


def dashboard_page() -> None:
    st.title("Claims Analysis Dashboard")
    st.caption("Analyze ERP exports, review exceptions, and search latest report outputs.")
    summary_df = read_report("summary.csv")
    show_kpis(summary_df)
    tabs = st.tabs(["Results", "For Review", "Unmatched", "Duplicate Checks", "Duplicate CV"])
    files = [
        ("claims_analysis_output.csv", "results"),
        ("for_review.csv", "for review"),
        ("unmatched_batches.csv", "unmatched batches"),
        ("duplicate_checks.csv", "duplicate checks"),
        ("duplicate_cv.csv", "duplicate CV"),
    ]
    for tab, (filename, label) in zip(tabs, files):
        with tab:
            show_preview(read_report(filename), label)


def payment_page() -> None:
    st.title("Payment Scheduling")
    st.caption("Streamlit redesign shell. Full batch scheduling controls will be migrated here in the next phase.")
    st.info("For now, use the existing Payment Scheduling app while this module is migrated to the Streamlit design.")
    st.markdown("Open existing app: [Payment Scheduling](http://127.0.0.1:5050)")


def budget_page() -> None:
    st.title("Budget Management")
    st.caption("Streamlit redesign shell. Full weekly/monthly controls will be migrated here in the next phase.")
    st.info("For now, use the existing Budget Management app while this module is migrated to the Streamlit design.")
    st.markdown("Open existing app: [Budget Management](http://127.0.0.1:5051)")


def main() -> None:
    st.sidebar.title("Claims Analysis Platform")
    role = st.sidebar.selectbox("Role", ["Admin", "Claims Manager", "Finance Manager"])
    pages = ["Dashboard"]
    if role in {"Admin", "Claims Manager"}:
        pages.append("Payment Scheduling")
    if role in {"Admin", "Finance Manager"}:
        pages.append("Budget Management")
    page = st.sidebar.radio("Module", pages)
    st.sidebar.caption("Unified Streamlit shell using the dashboard design language.")
    if page == "Dashboard":
        dashboard_page()
    elif page == "Payment Scheduling":
        payment_page()
    elif page == "Budget Management":
        budget_page()


if __name__ == "__main__":
    main()
