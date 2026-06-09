from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request

from claims_analysis.payment_db import DEFAULT_DB_PATH, connect, get_all_tags, get_history, init_db, upsert_tag


APP_TITLE = "Claims Payment Workflow"

SEARCH_COLUMNS = [
    "batch_no",
    "provider",
    "supplier_category_name",
    "region",
    "province",
    "city",
    "credit_term",
    "aging_bucket",
    "cv_no",
    "check_no",
    "payment_remarks",
]

BULK_FIELDS = {
    "provider": "provider",
    "date_received": "date_received",
    "region": "region",
}


def _where_clause(args):
    where = ["1 = 1"]
    params: list[str] = []

    q = (args.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        where.append("(" + " OR ".join([f"{col} LIKE ?" for col in SEARCH_COLUMNS]) + ")")
        params.extend([like] * len(SEARCH_COLUMNS))

    tag_status = (args.get("tag_status") or "ALL").upper()
    if tag_status == "TAGGED":
        where.append("UPPER(COALESCE(tagged_for_payment, '')) = 'YES'")
    elif tag_status == "UNTAGGED":
        where.append("UPPER(COALESCE(tagged_for_payment, '')) <> 'YES'")

    priority = (args.get("priority") or "ALL").upper()
    if priority != "ALL":
        where.append("UPPER(COALESCE(payment_priority, '')) = ?")
        params.append(priority)

    approval = (args.get("approval") or "ALL").upper()
    if approval == "APPROVED":
        where.append("UPPER(COALESCE(approval_status, '')) = 'APPROVED'")
    elif approval == "PENDING":
        where.append("UPPER(COALESCE(approval_status, '')) <> 'APPROVED'")

    date_from = (args.get("date_from") or "").strip()
    date_to = (args.get("date_to") or "").strip()
    if date_from:
        where.append("COALESCE(NULLIF(target_payment_date, ''), calendar_payment_date) >= ?")
        params.append(date_from)
    if date_to:
        where.append("COALESCE(NULLIF(target_payment_date, ''), calendar_payment_date) <= ?")
        params.append(date_to)

    return " WHERE " + " AND ".join(where), params


def _bulk_where(field: str, values: list[str]) -> tuple[str, list[str]]:
    col = BULK_FIELDS.get(field)
    if not col:
        raise ValueError("Invalid bulk field")
    clean = [str(v).strip() for v in values if str(v).strip()]
    if not clean:
        raise ValueError("No values selected")
    placeholders = ",".join(["?"] * len(clean))
    return f"WHERE COALESCE({col}, '') IN ({placeholders}) AND UPPER(COALESCE(payment_status,'')) = 'UNPAID'", clean


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> Flask:
    app = Flask(__name__)
    init_db(db_path)

    @app.get("/")
    def index():
        return DASHBOARD_HTML

    @app.get("/api/payments")
    def api_payments():
        page = max(int(request.args.get("page", 1)), 1)
        page_size = min(max(int(request.args.get("page_size", 100)), 25), 500)
        offset = (page - 1) * page_size
        where_sql, params = _where_clause(request.args)

        with connect(db_path) as conn:
            total = conn.execute(f"SELECT COUNT(*) AS c FROM payment_tags {where_sql}", params).fetchone()["c"]
            metric = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS candidates,
                    SUM(CASE WHEN UPPER(COALESCE(tagged_for_payment,'')) = 'YES' THEN 1 ELSE 0 END) AS tagged,
                    SUM(CASE WHEN UPPER(COALESCE(approval_status,'')) = 'APPROVED' THEN 1 ELSE 0 END) AS approved,
                    SUM(CASE WHEN UPPER(COALESCE(payment_priority,'')) IN ('URGENT','HIGH') THEN 1 ELSE 0 END) AS urgent_high,
                    SUM(CAST(COALESCE(NULLIF(expected_check_amount,''),'0') AS REAL)) AS filtered_amount,
                    SUM(CASE WHEN UPPER(COALESCE(tagged_for_payment,'')) = 'YES' THEN CAST(COALESCE(NULLIF(expected_check_amount,''),'0') AS REAL) ELSE 0 END) AS tagged_amount
                FROM payment_tags
                {where_sql}
                """,
                params,
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT *
                FROM payment_tags
                {where_sql}
                ORDER BY
                    CASE UPPER(COALESCE(payment_priority,''))
                        WHEN 'URGENT' THEN 1
                        WHEN 'HIGH' THEN 2
                        WHEN 'NORMAL' THEN 3
                        WHEN 'LOW' THEN 4
                        ELSE 5
                    END,
                    COALESCE(NULLIF(target_payment_date, ''), calendar_payment_date, '') ASC,
                    provider ASC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()

        return jsonify({"rows": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size, "metrics": dict(metric)})

    @app.get("/api/bulk-values")
    def api_bulk_values():
        field = request.args.get("field", "provider")
        col = BULK_FIELDS.get(field)
        if not col:
            return jsonify({"error": "Invalid field"}), 400
        with connect(db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT COALESCE({col}, '') AS value,
                       COUNT(*) AS batch_count,
                       SUM(CAST(COALESCE(NULLIF(expected_check_amount,''),'0') AS REAL)) AS amount
                FROM payment_tags
                WHERE UPPER(COALESCE(payment_status,'')) = 'UNPAID'
                  AND COALESCE({col}, '') <> ''
                GROUP BY COALESCE({col}, '')
                ORDER BY amount DESC, batch_count DESC, value ASC
                LIMIT 500
                """
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.post("/api/bulk-preview")
    def api_bulk_preview():
        payload = request.get_json(force=True, silent=True) or {}
        field = payload.get("field", "provider")
        values = payload.get("values", [])
        try:
            where_sql, params = _bulk_where(field, values)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        with connect(db_path) as conn:
            summary = conn.execute(
                f"""
                SELECT COUNT(*) AS batch_count,
                       COUNT(DISTINCT provider) AS provider_count,
                       SUM(CAST(COALESCE(NULLIF(expected_check_amount,''),'0') AS REAL)) AS amount
                FROM payment_tags
                {where_sql}
                """,
                params,
            ).fetchone()
            top = conn.execute(
                f"""
                SELECT provider,
                       COUNT(*) AS batch_count,
                       SUM(CAST(COALESCE(NULLIF(expected_check_amount,''),'0') AS REAL)) AS amount
                FROM payment_tags
                {where_sql}
                GROUP BY provider
                ORDER BY amount DESC
                LIMIT 10
                """,
                params,
            ).fetchall()
        return jsonify({"summary": dict(summary), "top_providers": [dict(row) for row in top]})

    @app.post("/api/bulk-apply")
    def api_bulk_apply():
        payload = request.get_json(force=True, silent=True) or {}
        field = payload.get("field", "provider")
        values = payload.get("values", [])
        update_values = {
            "tagged_for_payment": "YES",
            "target_payment_date": payload.get("target_payment_date", ""),
            "payment_priority": payload.get("payment_priority", ""),
            "approval_status": payload.get("approval_status", ""),
            "payment_remarks": payload.get("payment_remarks", ""),
            "tagged_date": datetime.now().strftime("%Y-%m-%d"),
        }
        try:
            where_sql, params = _bulk_where(field, values)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        with connect(db_path) as conn:
            batch_rows = conn.execute(f"SELECT batch_no, provider FROM payment_tags {where_sql}", params).fetchall()
        for row in batch_rows:
            upsert_tag(row["batch_no"], {**update_values, "provider": row["provider"]}, db_path=db_path, actor="bulk_schedule")
        return jsonify({"updated_rows": len(batch_rows)})

    @app.post("/api/payments/<batch_no>")
    def api_update_payment(batch_no: str):
        payload = request.get_json(force=True, silent=True) or {}
        actor = str(payload.pop("actor", "") or "")
        row = upsert_tag(batch_no, payload, db_path=db_path, actor=actor)
        return jsonify(row)

    @app.get("/api/history")
    def api_history():
        batch_no = request.args.get("batch_no")
        return jsonify(get_history(batch_no=batch_no, db_path=db_path))

    @app.get("/export/payments.csv")
    def export_payments():
        rows = get_all_tags(db_path)
        output = io.StringIO()
        if rows:
            fieldnames = list(rows[0].keys())
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=payments_db_export.csv"})

    return app


DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Claims Payment Workflow</title>
<style>
:root { --bg:#f3f6fb; --card:#fff; --text:#172033; --muted:#64748b; --border:#dbe3ef; --primary:#1d4ed8; --danger:#b91c1c; --good:#047857; --warn:#b45309; }
* { box-sizing:border-box; } body { margin:0; font-family:Arial,Helvetica,sans-serif; background:var(--bg); color:var(--text); }
header { background:#0f172a; color:#fff; padding:20px 26px; } header h1 { margin:0 0 5px; font-size:24px; } header p { margin:0; color:#cbd5e1; font-size:13px; }
main { padding:18px; } .card { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:14px; box-shadow:0 1px 3px rgba(15,23,42,.08); margin-bottom:14px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; } .metric-label { color:var(--muted); font-size:12px; margin-bottom:7px; } .metric-value { font-size:23px; font-weight:800; }
.toolbar,.bulk-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(175px,1fr)); gap:10px; align-items:end; } label { display:block; color:var(--muted); font-size:12px; margin-bottom:5px; }
input,select,textarea { width:100%; padding:8px 9px; border:1px solid var(--border); border-radius:8px; background:white; font-family:inherit; font-size:12px; }
button { border:1px solid var(--border); background:white; padding:9px 11px; border-radius:9px; cursor:pointer; font-weight:700; font-size:12px; } button.primary { background:var(--primary); color:white; border-color:var(--primary); } button.good { background:var(--good); color:white; border-color:var(--good); }
.note { color:var(--muted); font-size:12px; } .drilldown { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:8px; max-height:260px; overflow:auto; margin-top:10px; }
.check-item { display:flex; gap:8px; align-items:flex-start; padding:8px; border:1px solid var(--border); border-radius:8px; background:#f8fafc; font-size:12px; } .check-item span { overflow-wrap:anywhere; }
.preview { margin-top:10px; padding:10px; border-radius:10px; background:#f8fafc; border:1px solid var(--border); }
.table-wrap { overflow:auto; max-height:68vh; border:1px solid var(--border); border-radius:12px; background:white; } table { border-collapse:collapse; width:100%; min-width:1500px; font-size:11px; table-layout:fixed; }
th,td { border-bottom:1px solid var(--border); padding:7px 8px; text-align:left; vertical-align:top; white-space:normal; overflow-wrap:anywhere; word-break:break-word; line-height:1.25; } th { position:sticky; top:0; background:#f8fafc; z-index:1; font-size:11px; } tr:hover td { background:#f9fafb; }
.controls-cell { width:150px; } .control-stack { display:grid; grid-template-columns:1fr; gap:5px; } .col-batch { width:145px; } .col-provider { width:230px; } .col-category { width:135px; } .col-region { width:80px; } .col-date { width:105px; } .col-aging { width:90px; } .col-term { width:90px; } .col-money { width:115px; text-align:right; } .col-priority { width:90px; } .col-status { width:95px; } .col-remarks { width:190px; }
.badge { display:inline-block; padding:3px 6px; border-radius:6px; font-size:10px; font-weight:800; } .priority-urgent { background:#fee2e2; color:var(--danger); } .priority-high { background:#ffedd5; color:var(--warn); } .priority-normal { background:#e0f2fe; color:#0369a1; } .priority-low { background:#ecfdf5; color:var(--good); }
.pagination { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:10px; }
</style>
</head>
<body>
<header><h1>Claims Payment Workflow</h1><p>Bulk scheduling by Provider, Date Received, or Region. Source: data/payments.db</p></header>
<main>
<section class="grid" id="metrics"></section>
<section class="card">
<h3>Bulk Payment Scheduling</h3>
<div class="bulk-grid">
<div><label>Schedule By</label><select id="bulkField" onchange="loadBulkValues()"><option value="provider">Provider Name</option><option value="date_received">Date Received</option><option value="region">Region</option></select></div>
<div><label>Target Payment Date</label><input id="bulkTargetDate" type="date" /></div>
<div><label>Priority</label><select id="bulkPriority"><option value="HIGH">HIGH</option><option value="URGENT">URGENT</option><option value="NORMAL">NORMAL</option><option value="LOW">LOW</option></select></div>
<div><label>Approval</label><select id="bulkApproval"><option value="">No Approval Yet</option><option value="APPROVED">APPROVED</option><option value="HOLD">HOLD</option></select></div>
<div><label>Remarks</label><input id="bulkRemarks" placeholder="Payment batch remarks" /></div>
<div><button class="primary" onclick="previewBulk()">Preview Matching Batches</button></div>
<div><button class="good" onclick="applyBulk()">Apply To Selected Batches</button></div>
</div>
<div id="bulkValues" class="drilldown"></div>
<div id="bulkPreview" class="preview note">Select drilldown values, then preview.</div>
</section>
<section class="card">
<div class="toolbar">
<div><label>Global Search</label><input id="search" placeholder="Batch, provider, region, credit term, amount..." /></div>
<div><label>Tag Status</label><select id="tagStatus"><option value="ALL">All</option><option value="TAGGED">Tagged</option><option value="UNTAGGED">Untagged</option></select></div>
<div><label>Priority</label><select id="priorityFilter"><option value="ALL">All</option><option value="URGENT">Urgent</option><option value="HIGH">High</option><option value="NORMAL">Normal</option><option value="LOW">Low</option></select></div>
<div><label>Approval</label><select id="approvalFilter"><option value="ALL">All</option><option value="APPROVED">Approved</option><option value="PENDING">Pending</option></select></div>
<div><label>Target Payment From</label><input id="dateFrom" type="date" /></div>
<div><label>Target Payment To</label><input id="dateTo" type="date" /></div>
<div><button class="primary" onclick="loadRows()">Refresh</button></div>
<div><button class="good" onclick="window.location.href='/export/payments.csv'">Export DB CSV</button></div>
</div>
<p class="note">This optimized view uses server-side pagination. Only the current page is loaded from SQLite.</p>
</section>
<section class="card"><div id="tableNote" class="note"></div><div class="table-wrap" id="tableWrap"></div><div class="pagination" id="pagination"></div></section>
</main>
<script>
let ROWS = []; let totalRows = 0; let currentPage = 1; let pageSize = 100; let loading = false;
function num(v) { const n = Number(String(v ?? '').replaceAll(',', '')); return Number.isNaN(n) ? 0 : n; }
function money(v) { return num(v).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}); }
function escapeHtml(v) { return String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;'); }
function upper(v) { return String(v ?? '').trim().toUpperCase(); }
function priorityClass(v) { const p = upper(v || 'NORMAL').toLowerCase(); return `priority-${p}`; }
function selectedBulkValues() { return [...document.querySelectorAll('.bulk-check:checked')].map(x => x.value); }
function params() { const p = new URLSearchParams(); p.set('page', currentPage); p.set('page_size', pageSize); p.set('q', document.getElementById('search').value || ''); p.set('tag_status', document.getElementById('tagStatus').value); p.set('priority', document.getElementById('priorityFilter').value); p.set('approval', document.getElementById('approvalFilter').value); p.set('date_from', document.getElementById('dateFrom').value || ''); p.set('date_to', document.getElementById('dateTo').value || ''); return p; }
async function loadBulkValues() { const field = document.getElementById('bulkField').value; const res = await fetch('/api/bulk-values?field=' + encodeURIComponent(field)); const rows = await res.json(); document.getElementById('bulkValues').innerHTML = rows.map(r => `<label class="check-item"><input class="bulk-check" type="checkbox" value="${escapeHtml(r.value)}" /><span><b>${escapeHtml(r.value)}</b><br>${Number(r.batch_count||0).toLocaleString()} batches | ${money(r.amount||0)}</span></label>`).join(''); document.getElementById('bulkPreview').textContent = 'Select drilldown values, then preview.'; }
async function previewBulk() { const values = selectedBulkValues(); const field = document.getElementById('bulkField').value; if (!values.length) { alert('Select at least one value.'); return; } const res = await fetch('/api/bulk-preview', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({field, values})}); const data = await res.json(); if (data.error) { alert(data.error); return; } const s = data.summary || {}; const top = (data.top_providers || []).map(x => `${escapeHtml(x.provider)} - ${Number(x.batch_count||0).toLocaleString()} batches - ${money(x.amount||0)}`).join('<br>'); document.getElementById('bulkPreview').innerHTML = `<b>Preview:</b> ${Number(s.batch_count||0).toLocaleString()} batches | ${Number(s.provider_count||0).toLocaleString()} providers | ${money(s.amount||0)}<br><br><b>Top Providers</b><br>${top}`; }
async function applyBulk() { const values = selectedBulkValues(); if (!values.length) { alert('Select at least one value.'); return; } if (!document.getElementById('bulkTargetDate').value) { alert('Select a target payment date.'); return; } if (!confirm('Apply payment schedule to all matching unpaid batches?')) return; const payload = {field: document.getElementById('bulkField').value, values, target_payment_date: document.getElementById('bulkTargetDate').value, payment_priority: document.getElementById('bulkPriority').value, approval_status: document.getElementById('bulkApproval').value, payment_remarks: document.getElementById('bulkRemarks').value}; const res = await fetch('/api/bulk-apply', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}); const data = await res.json(); if (data.error) { alert(data.error); return; } alert(`Updated ${Number(data.updated_rows||0).toLocaleString()} batches.`); await previewBulk(); await loadRows(true); }
async function loadRows(reset=false) { if (loading) return; if (reset) currentPage = 1; loading = true; document.getElementById('tableNote').textContent = 'Loading...'; const response = await fetch('/api/payments?' + params().toString()); const payload = await response.json(); ROWS = payload.rows || []; totalRows = payload.total || 0; currentPage = payload.page || currentPage; pageSize = payload.page_size || pageSize; renderMetrics(payload.metrics || {}); renderTable(); loading = false; }
function renderMetrics(m) { const metrics = [['Payment Candidates', Number(m.candidates || 0).toLocaleString()], ['Tagged', Number(m.tagged || 0).toLocaleString()], ['Approved', Number(m.approved || 0).toLocaleString()], ['Urgent / High', Number(m.urgent_high || 0).toLocaleString()], ['Filtered Amount', money(m.filtered_amount || 0)], ['Tagged Amount', money(m.tagged_amount || 0)]]; document.getElementById('metrics').innerHTML = metrics.map(([l,v]) => `<div class="card"><div class="metric-label">${l}</div><div class="metric-value">${v}</div></div>`).join(''); }
function renderTable() { const totalPages = Math.max(1, Math.ceil(totalRows / pageSize)); document.getElementById('tableNote').textContent = `Showing ${ROWS.length.toLocaleString()} rows on this page. Filtered rows: ${totalRows.toLocaleString()}.`; if (!ROWS.length) { document.getElementById('tableWrap').innerHTML = '<div style="padding:16px" class="note">No rows found.</div>'; return; } const header = `<thead><tr>${['Controls','Batch No','Provider','Supplier Category','Region','Date Received','Aging','Credit Term','Claim Amount','Expected Check','Priority','Tag Status','Target Payment','Approval','Remarks'].map(h => `<th>${h}</th>`).join('')}</tr></thead>`; const body = `<tbody>${ROWS.map(renderRow).join('')}</tbody>`; document.getElementById('tableWrap').innerHTML = `<table>${header}${body}</table>`; document.getElementById('pagination').innerHTML = `<button onclick="firstPage()" ${currentPage<=1?'disabled':''}>First</button><button onclick="prevPage()" ${currentPage<=1?'disabled':''}>Previous</button><span class="note">Page ${currentPage.toLocaleString()} of ${totalPages.toLocaleString()}</span><button onclick="nextPage()" ${currentPage>=totalPages?'disabled':''}>Next</button><button onclick="lastPage()" ${currentPage>=totalPages?'disabled':''}>Last</button><select onchange="pageSize=Number(this.value);currentPage=1;loadRows()"><option value="50" ${pageSize==50?'selected':''}>50</option><option value="100" ${pageSize==100?'selected':''}>100</option><option value="250" ${pageSize==250?'selected':''}>250</option><option value="500" ${pageSize==500?'selected':''}>500</option></select>`; }
function renderRow(row) { const key = escapeHtml(row.batch_no); const p = upper(row.payment_priority || 'NORMAL') || 'NORMAL'; return `<tr><td class="controls-cell"><div class="control-stack"><select onchange="updateRow('${key}','tagged_for_payment',this.value)"><option value="" ${!row.tagged_for_payment?'selected':''}>Not Tagged</option><option value="YES" ${upper(row.tagged_for_payment)==='YES'?'selected':''}>YES</option></select><select onchange="updateRow('${key}','payment_priority',this.value)"><option value="URGENT" ${p==='URGENT'?'selected':''}>URGENT</option><option value="HIGH" ${p==='HIGH'?'selected':''}>HIGH</option><option value="NORMAL" ${p==='NORMAL'?'selected':''}>NORMAL</option><option value="LOW" ${p==='LOW'?'selected':''}>LOW</option></select></div></td><td class="col-batch">${escapeHtml(row.batch_no)}</td><td class="col-provider">${escapeHtml(row.provider)}</td><td class="col-category">${escapeHtml(row.supplier_category_name)}</td><td class="col-region">${escapeHtml(row.region)}</td><td class="col-date">${escapeHtml(row.date_received)}</td><td class="col-aging">${escapeHtml(row.aging_bucket)}</td><td class="col-term">${escapeHtml(row.credit_term)}</td><td class="col-money">${money(row.claims_amount)}</td><td class="col-money">${money(row.expected_check_amount)}</td><td class="col-priority"><span class="badge ${priorityClass(p)}">${escapeHtml(p)}</span></td><td class="col-status">${escapeHtml(row.tagged_for_payment || 'Not Tagged')}</td><td class="col-date"><input type="date" value="${escapeHtml(row.target_payment_date)}" onchange="updateRow('${key}','target_payment_date',this.value)" /></td><td class="col-status"><select onchange="updateRow('${key}','approval_status',this.value)"><option value="" ${!row.approval_status?'selected':''}>Select</option><option value="APPROVED" ${upper(row.approval_status)==='APPROVED'?'selected':''}>APPROVED</option><option value="HOLD" ${upper(row.approval_status)==='HOLD'?'selected':''}>HOLD</option></select></td><td class="col-remarks"><textarea rows="2" onchange="updateRow('${key}','payment_remarks',this.value)">${escapeHtml(row.payment_remarks)}</textarea></td></tr>`; }
async function updateRow(batchNo, field, value) { const row = ROWS.find(r => String(r.batch_no) === String(batchNo)); const payload = { actor: 'manual_update', provider: row?.provider || '', [field]: value }; if (field === 'tagged_for_payment' && value === 'YES') payload.tagged_date = new Date().toISOString().slice(0,10); await fetch(`/api/payments/${encodeURIComponent(batchNo)}`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) }); }
function nextPage() { currentPage++; loadRows(); } function prevPage() { currentPage--; loadRows(); } function firstPage() { currentPage = 1; loadRows(); } function lastPage() { currentPage = Math.max(1, Math.ceil(totalRows / pageSize)); loadRows(); }
let timer = null; ['search','tagStatus','priorityFilter','approvalFilter','dateFrom','dateTo'].forEach(id => document.getElementById(id).addEventListener('input', () => { clearTimeout(timer); timer=setTimeout(() => loadRows(true), 250); })); loadBulkValues(); loadRows();
</script>
</body>
</html>
"""


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Run local database-backed claims payment workflow app.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    args = parser.parse_args()
    app = create_app(args.db)
    print(f"{APP_TITLE} running at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
