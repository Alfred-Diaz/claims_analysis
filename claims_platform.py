from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from claims_analysis.budget_db import (
    approve_monthly_budget_request,
    create_monthly_budget_request,
    ensure_month,
    month_key_from_date,
    reject_monthly_budget_request,
    request_weekly_additional_funds,
)
from claims_analysis.payment_db import DEFAULT_DB_PATH, connect, init_db, upsert_tag

st.set_page_config(page_title="Claims Analysis Platform", layout="wide")

REPORTS_DIR = Path("reports/latest")
DB_PATH = DEFAULT_DB_PATH
PREVIEW_ROWS = 1000
CATEGORIES = ["Hospital", "Medical Clinic", "Dental Clinic", "Professional"]

CATEGORY_SQL = """
CASE
  WHEN UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%PROFESSIONAL%'
    OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%PROF FEE%'
    OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%DOCTOR%'
    OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE 'DR %'
    OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '% DR %'
    OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%PHYSICIAN%'
    THEN 'Professional'
  WHEN UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%DENTAL%'
    OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%DENTIST%'
    THEN 'Dental Clinic'
  WHEN UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%CLINIC%'
    OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%DIAGNOSTIC%'
    OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%LABORATORY%'
    OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%IMAGING%'
    OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%MEDICAL CENTER%'
    THEN 'Medical Clinic'
  ELSE 'Hospital'
END
"""


def money(value) -> str:
    try:
        return f"PHP {float(value or 0):,.2f}"
    except Exception:
        return "PHP 0.00"


def amount_expr(col: str = "claims_amount") -> str:
    return f"CAST(COALESCE(NULLIF({col},''),'0') AS REAL)"


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


def provider_summary(scheduled: bool, category: str, search: str = "") -> pd.DataFrame:
    target_filter = "COALESCE(target_payment_date,'') <> ''" if scheduled else "COALESCE(target_payment_date,'') = ''"
    provider_filter = "AND provider LIKE ?" if search else ""
    params = []
    if search:
        params.append(f"%{search}%")
    params.append(category)
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            f"""
            SELECT provider, region, credit_term, ({CATEGORY_SQL}) AS category,
                   COUNT(*) AS batch_count,
                   SUM({amount_expr()}) AS claims_amount,
                   MIN(target_payment_date) AS min_payment_date,
                   MAX(target_payment_date) AS max_payment_date
            FROM payment_tags
            WHERE UPPER(COALESCE(payment_status,'')) = 'UNPAID'
              AND {target_filter}
              AND COALESCE(provider,'') <> ''
              {provider_filter}
              AND ({CATEGORY_SQL}) = ?
            GROUP BY provider, region, credit_term, category
            ORDER BY claims_amount DESC, provider ASC
            LIMIT 500
            """,
            params,
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def provider_batches(provider: str, scheduled: bool, category: str) -> pd.DataFrame:
    if not provider:
        return pd.DataFrame()
    target_filter = "COALESCE(target_payment_date,'') <> ''" if scheduled else "COALESCE(target_payment_date,'') = ''"
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            f"""
            SELECT batch_no, provider, ({CATEGORY_SQL}) AS category, region, date_received,
                   aging_bucket, credit_term, claims_amount, expected_check_amount,
                   target_payment_date, payment_priority, approval_status, payment_remarks,
                   cv_no, check_no, check_date
            FROM payment_tags
            WHERE provider = ?
              AND UPPER(COALESCE(payment_status,'')) = 'UNPAID'
              AND {target_filter}
              AND ({CATEGORY_SQL}) = ?
            ORDER BY COALESCE(target_payment_date,''), date_received, batch_no
            """,
            (provider, category),
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def selected_amount(df: pd.DataFrame, selected: list[str]) -> float:
    if df.empty or not selected:
        return 0.0
    return df[df["batch_no"].astype(str).isin(selected)]["claims_amount"].astype(float).sum()


def schedule_selected(batch_numbers: list[str], target_date: str, priority: str, approval: str, remarks: str) -> tuple[bool, str]:
    if not batch_numbers:
        return False, "Select at least one batch."
    if not target_date:
        return False, "Target payment date is required."
    placeholders = ",".join(["?"] * len(batch_numbers))
    with connect(DB_PATH) as conn:
        rows = conn.execute(f"SELECT batch_no, provider FROM payment_tags WHERE batch_no IN ({placeholders})", batch_numbers).fetchall()
    values = {
        "tagged_for_payment": "YES",
        "target_payment_date": target_date,
        "payment_priority": priority,
        "approval_status": approval,
        "payment_remarks": remarks,
        "tagged_date": datetime.now().strftime("%Y-%m-%d"),
    }
    for row in rows:
        upsert_tag(row["batch_no"], {**values, "provider": row["provider"]}, db_path=DB_PATH, actor="claims_platform")
    ensure_month(month_key_from_date(target_date), DB_PATH)
    return True, f"Scheduled {len(rows):,} selected batches."


def unschedule_selected(batch_numbers: list[str]) -> tuple[bool, str]:
    if not batch_numbers:
        return False, "Select at least one scheduled batch."
    placeholders = ",".join(["?"] * len(batch_numbers))
    with connect(DB_PATH) as conn:
        rows = conn.execute(f"SELECT batch_no, provider, target_payment_date FROM payment_tags WHERE batch_no IN ({placeholders})", batch_numbers).fetchall()
    affected_months = {month_key_from_date(row["target_payment_date"]) for row in rows if row["target_payment_date"]}
    for row in rows:
        upsert_tag(
            row["batch_no"],
            {"provider": row["provider"], "tagged_for_payment": "", "target_payment_date": "", "payment_priority": "", "approval_status": "", "payment_remarks": ""},
            db_path=DB_PATH,
            actor="claims_platform",
        )
    for month in affected_months:
        ensure_month(month, DB_PATH)
    return True, f"Returned {len(rows):,} batches to For Scheduling."


def payment_page() -> None:
    init_db(DB_PATH)
    st.title("Payment Scheduling")
    st.caption("Provider drilldown, batch-level scheduling, and scheduled payment review.")

    tab_for, tab_scheduled = st.tabs(["For Scheduling", "Scheduled"])

    with tab_for:
        category = st.radio("Supplier Category", CATEGORIES, horizontal=True, key="for_cat")
        search = st.text_input("Search Provider", key="for_search")
        providers = provider_summary(False, category, search)
        left, right = st.columns([1, 2])
        with left:
            st.subheader("Providers for Scheduling")
            if providers.empty:
                st.info("No providers found.")
                provider = ""
            else:
                provider = st.selectbox("Select Provider", providers["provider"].tolist(), key="for_provider")
                st.dataframe(providers, use_container_width=True, height=360)
        with right:
            st.subheader("Unscheduled Batches")
            batches = provider_batches(provider, False, category) if provider else pd.DataFrame()
            if batches.empty:
                st.info("No unscheduled batches found.")
            else:
                selected = st.multiselect("Select Batch Numbers", batches["batch_no"].astype(str).tolist(), key="for_selected")
                c1, c2, c3 = st.columns(3)
                c1.metric("Selected Batches", f"{len(selected):,}")
                c2.metric("Selected Claims Amount", money(selected_amount(batches, selected)))
                c3.metric("Provider Claims Amount", money(batches["claims_amount"].astype(float).sum()))
                with st.form("schedule_form"):
                    f1, f2, f3 = st.columns(3)
                    target_date = f1.date_input("Target Payment Date", value=date.today())
                    priority = f2.selectbox("Priority", ["HIGH", "URGENT", "NORMAL", "LOW"])
                    approval = f3.selectbox("Approval", ["", "APPROVED", "HOLD"])
                    remarks = st.text_input("Remarks")
                    if st.form_submit_button("Schedule Selected Batches", type="primary"):
                        ok, msg = schedule_selected(selected, target_date.isoformat(), priority, approval, remarks)
                        st.success(msg) if ok else st.error(msg)
                        st.rerun()
                st.dataframe(batches, use_container_width=True, height=420)

    with tab_scheduled:
        category = st.radio("Supplier Category", CATEGORIES, horizontal=True, key="sched_cat")
        search = st.text_input("Search Scheduled Provider", key="sched_search")
        providers = provider_summary(True, category, search)
        left, right = st.columns([1, 2])
        with left:
            st.subheader("Scheduled Providers")
            if providers.empty:
                st.info("No scheduled providers found.")
                provider = ""
            else:
                provider = st.selectbox("Select Scheduled Provider", providers["provider"].tolist(), key="sched_provider")
                st.dataframe(providers, use_container_width=True, height=360)
        with right:
            st.subheader("Scheduled Batches")
            batches = provider_batches(provider, True, category) if provider else pd.DataFrame()
            if batches.empty:
                st.info("No scheduled batches found.")
            else:
                selected = st.multiselect("Select Scheduled Batch Numbers", batches["batch_no"].astype(str).tolist(), key="sched_selected")
                c1, c2, c3 = st.columns(3)
                c1.metric("Scheduled Batches", f"{len(batches):,}")
                c2.metric("Selected Claims Amount", money(selected_amount(batches, selected)))
                c3.metric("Provider Scheduled Amount", money(batches["claims_amount"].astype(float).sum()))
                if st.button("Return Selected to For Scheduling", type="secondary"):
                    ok, msg = unschedule_selected(selected)
                    st.success(msg) if ok else st.error(msg)
                    st.rerun()
                view = st.radio("View", ["Calendar", "List"], horizontal=True, key="scheduled_view")
                if view == "Calendar":
                    grouped = batches.groupby("target_payment_date", dropna=False)
                    cols = st.columns(4)
                    for idx, (payment_date, group) in enumerate(grouped):
                        with cols[idx % 4]:
                            st.markdown(f"#### {payment_date}")
                            st.metric("Batches", f"{len(group):,}")
                            st.metric("Claims", money(group["claims_amount"].astype(float).sum()))
                            st.dataframe(group[["batch_no", "claims_amount", "payment_priority"]].head(20), use_container_width=True, height=220)
                else:
                    st.dataframe(batches, use_container_width=True, height=520)


def budget_page() -> None:
    st.title("Budget Management")
    st.caption("Monthly budget, fixed 4-week allocation, weekly reallocation, and Finance Manager approval.")

    month = st.text_input("Budget Month", value=month_key_from_date(), help="Use YYYY-MM format")
    data = ensure_month(month, DB_PATH)
    month_data = data["month"]
    weeks = pd.DataFrame(data["weeks"])
    requests = pd.DataFrame(data["requests"])

    total_used = float(weeks["used_budget"].astype(float).sum()) if not weeks.empty else 0.0
    total_remaining = float(weeks["remaining_budget"].astype(float).sum()) if not weeks.empty else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Base Monthly Budget", money(month_data.get("base_monthly_budget")))
    c2.metric("Approved Additional", money(month_data.get("approved_additional_budget")))
    c3.metric("Total Budget", money(month_data.get("total_monthly_budget")))
    c4.metric("Used / Scheduled", money(total_used))

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Remaining", money(total_remaining))
    c6.metric("Budget Weeks", f"{len(weeks):,}")
    c7.metric("Pending Requests", f"{0 if requests.empty else len(requests[requests['status'] == 'PENDING']):,}")
    utilization = (total_used / float(month_data.get("total_monthly_budget") or 1)) * 100
    c8.metric("Utilization", f"{utilization:.2f}%")

    tab_weeks, tab_reallocate, tab_request, tab_approval = st.tabs([
        "Weekly Allocation",
        "Weekly Reallocation",
        "Monthly Request",
        "Approval Queue",
    ])

    with tab_weeks:
        st.subheader("Fixed 4-Week Budget Allocation")
        if weeks.empty:
            st.info("No weekly allocation found.")
        else:
            display_weeks = weeks.copy()
            for col in ["allocated_budget", "used_budget", "remaining_budget"]:
                display_weeks[col] = display_weeks[col].astype(float)
            st.dataframe(display_weeks, use_container_width=True, height=300)
            chart_df = display_weeks[["week_no", "allocated_budget", "used_budget", "remaining_budget"]].set_index("week_no")
            st.bar_chart(chart_df)

    with tab_reallocate:
        st.subheader("Request Additional Weekly Funds")
        st.caption("This does not increase the monthly budget. It adds funds to one week and deducts evenly from the other three weeks.")
        with st.form("weekly_reallocation_form"):
            f1, f2 = st.columns(2)
            week_no = f1.selectbox("Target Week", [1, 2, 3, 4])
            amount = f2.number_input("Additional Amount", min_value=0.0, step=100000.0)
            reason = st.text_input("Reason")
            submitted = st.form_submit_button("Apply Weekly Reallocation", type="primary")
            if submitted:
                try:
                    request_weekly_additional_funds(month, week_no, amount, reason, "Claims Manager", DB_PATH)
                    st.success("Weekly budget reallocated successfully.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    with tab_request:
        st.subheader("Monthly Additional Funds Request")
        st.caption("This creates a pending request. It only affects the budget after Finance Manager approval.")
        with st.form("monthly_request_form"):
            amount = st.number_input("Requested Additional Monthly Amount", min_value=0.0, step=100000.0)
            reason = st.text_input("Request Reason")
            submitted = st.form_submit_button("Submit Monthly Request", type="primary")
            if submitted:
                try:
                    create_monthly_budget_request(month, amount, reason, "Claims Manager", DB_PATH)
                    st.success("Monthly additional budget request submitted.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    with tab_approval:
        st.subheader("Finance Manager Approval Queue")
        if requests.empty:
            st.info("No budget requests for this month.")
        else:
            st.dataframe(requests, use_container_width=True, height=320)
            pending = requests[requests["status"] == "PENDING"]
            if pending.empty:
                st.info("No pending requests.")
            else:
                selected_id = st.selectbox("Select Pending Request ID", pending["id"].astype(int).tolist())
                remarks = st.text_input("Approval / Rejection Remarks")
                col_a, col_b = st.columns(2)
                if col_a.button("Approve Request", type="primary"):
                    try:
                        approve_monthly_budget_request(int(selected_id), "Finance Manager", remarks, DB_PATH)
                        st.success("Monthly request approved and applied to weekly allocation.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                if col_b.button("Reject Request"):
                    try:
                        reject_monthly_budget_request(int(selected_id), "Finance Manager", remarks, DB_PATH)
                        st.warning("Monthly request rejected.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))


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
