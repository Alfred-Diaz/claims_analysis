from __future__ import annotations

import csv
import io
from pathlib import Path

from flask import Flask, jsonify, request, Response

from claims_analysis.payment_db import DEFAULT_DB_PATH, get_all_tags, get_history, init_db, upsert_tag


APP_TITLE = "Claims Payment Workflow"


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> Flask:
    app = Flask(__name__)
    init_db(db_path)

    @app.get("/")
    def index():
        return DASHBOARD_HTML

    @app.get("/api/payments")
    def api_payments():
        rows = get_all_tags(db_path)
        return jsonify(rows)

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
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=payments_db_export.csv"},
        )

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
* { box-sizing:border-box; }
body { margin:0; font-family:Arial,Helvetica,sans-serif; background:var(--bg); color:var(--text); }
header { background:#0f172a; color:#fff; padding:22px 28px; }
header h1 { margin:0 0 6px; font-size:24px; }
header p { margin:0; color:#cbd5e1; font-size:13px; }
main { padding:20px; }
.card { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:16px; box-shadow:0 1px 3px rgba(15,23,42,.08); margin-bottom:14px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; }
.metric-label { color:var(--muted); font-size:12px; margin-bottom:8px; }
.metric-value { font-size:24px; font-weight:800; }
.toolbar { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; align-items:end; }
label { display:block; color:var(--muted); font-size:12px; margin-bottom:5px; }
input,select,textarea { width:100%; padding:9px 10px; border:1px solid var(--border); border-radius:8px; background:white; font-family:inherit; }
button { border:1px solid var(--border); background:white; padding:10px 12px; border-radius:9px; cursor:pointer; font-weight:700; }
button.primary { background:var(--primary); color:white; border-color:var(--primary); }
button.good { background:var(--good); color:white; border-color:var(--good); }
button.danger { background:var(--danger); color:white; border-color:var(--danger); }
.note { color:var(--muted); font-size:12px; }
.table-wrap { overflow:auto; max-height:68vh; border:1px solid var(--border); border-radius:12px; background:white; }
table { border-collapse:collapse; width:100%; font-size:12px; }
th,td { border-bottom:1px solid var(--border); padding:8px 9px; text-align:left; white-space:nowrap; }
th { position:sticky; top:0; background:#f8fafc; z-index:1; }
tr:hover td { background:#f9fafb; }
.tagged { color:var(--good); font-weight:800; }
.untagged { color:var(--danger); font-weight:800; }
.priority-urgent { color:var(--danger); font-weight:800; }
.priority-high { color:var(--warn); font-weight:800; }
.inline-input { min-width:130px; }
.remarks { min-width:230px; }
.pagination { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:10px; }
</style>
</head>
<body>
<header>
<h1>Claims Payment Workflow</h1>
<p>Database-backed payment tagging and payment calendar workflow. Source: data/payments.db</p>
</header>
<main>
<section class="grid" id="metrics"></section>
<section class="card">
<div class="toolbar">
<div><label>Actor / Processor Name</label><input id="actor" placeholder="Your name" /></div>
<div><label>Global Search</label><input id="search" placeholder="Batch, provider, region, credit term, amount..." /></div>
<div><label>Tag Status</label><select id="tagStatus"><option value="ALL">All</option><option value="TAGGED">Tagged</option><option value="UNTAGGED">Untagged</option></select></div>
<div><label>Priority</label><select id="priorityFilter"><option value="ALL">All</option><option value="URGENT">Urgent</option><option value="HIGH">High</option><option value="NORMAL">Normal</option><option value="LOW">Low</option></select></div>
<div><label>Approval</label><select id="approvalFilter"><option value="ALL">All</option><option value="APPROVED">Approved</option><option value="PENDING">Pending</option></select></div>
<div><label>Target Payment From</label><input id="dateFrom" type="date" /></div>
<div><label>Target Payment To</label><input id="dateTo" type="date" /></div>
<div><button class="primary" onclick="loadRows()">Refresh</button></div>
<div><button class="good" onclick="window.location.href='/export/payments.csv'">Export DB CSV</button></div>
</div>
<p class="note">Changes save directly to SQLite. Run the sync command after new ERP exports to refresh reference fields while preserving tags.</p>
</section>
<section class="card">
<div id="tableNote" class="note"></div>
<div class="table-wrap" id="tableWrap"></div>
<div class="pagination" id="pagination"></div>
</section>
</main>
<script>
let ROWS = [];
let filtered = [];
let currentPage = 1;
let pageSize = 100;

function num(v) { const n = Number(String(v ?? '').replaceAll(',', '')); return Number.isNaN(n) ? 0 : n; }
function money(v) { return num(v).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}); }
function escapeHtml(v) { return String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;'); }
function norm(v) { return String(v ?? '').trim().toLowerCase(); }
function upper(v) { return String(v ?? '').trim().toUpperCase(); }
function isTagged(row) { return upper(row.tagged_for_payment) === 'YES'; }
function priority(row) { return upper(row.payment_priority || ''); }
function parseDate(v) { const d = new Date(v); return Number.isNaN(d.getTime()) ? null : d; }

async function loadRows() {
  const response = await fetch('/api/payments');
  ROWS = await response.json();
  applyFilters();
}

function passFilters(row) {
  const q = norm(document.getElementById('search').value);
  const tagStatus = document.getElementById('tagStatus').value;
  const pFilter = document.getElementById('priorityFilter').value;
  const approval = document.getElementById('approvalFilter').value;
  const from = document.getElementById('dateFrom').value ? parseDate(document.getElementById('dateFrom').value) : null;
  const to = document.getElementById('dateTo').value ? parseDate(document.getElementById('dateTo').value) : null;
  const allText = Object.values(row).join(' ').toLowerCase();
  if (q && !allText.includes(q)) return false;
  if (tagStatus === 'TAGGED' && !isTagged(row)) return false;
  if (tagStatus === 'UNTAGGED' && isTagged(row)) return false;
  if (pFilter !== 'ALL' && priority(row) !== pFilter) return false;
  if (approval === 'APPROVED' && upper(row.approval_status) !== 'APPROVED') return false;
  if (approval === 'PENDING' && upper(row.approval_status) === 'APPROVED') return false;
  const target = parseDate(row.target_payment_date || row.calendar_payment_date || '');
  if ((from || to) && !target) return false;
  if (from && target < from) return false;
  if (to) { const end = new Date(to); end.setHours(23,59,59,999); if (target > end) return false; }
  return true;
}

function calcMetrics() {
  const rows = filtered;
  const tagged = rows.filter(isTagged);
  const approved = rows.filter(r => upper(r.approval_status) === 'APPROVED');
  const urgent = rows.filter(r => priority(r) === 'URGENT' || priority(r) === 'HIGH');
  const amount = rows.reduce((a,r) => a + num(r.expected_check_amount), 0);
  const taggedAmount = tagged.reduce((a,r) => a + num(r.expected_check_amount), 0);
  const metrics = [
    ['Payment Candidates', rows.length.toLocaleString()],
    ['Tagged', tagged.length.toLocaleString()],
    ['Approved', approved.length.toLocaleString()],
    ['Urgent / High', urgent.length.toLocaleString()],
    ['Filtered Amount', money(amount)],
    ['Tagged Amount', money(taggedAmount)]
  ];
  document.getElementById('metrics').innerHTML = metrics.map(([l,v]) => `<div class="card"><div class="metric-label">${l}</div><div class="metric-value">${v}</div></div>`).join('');
}

function applyFilters(reset=true) {
  if (reset) currentPage = 1;
  filtered = ROWS.filter(passFilters);
  calcMetrics();
  renderTable();
}

function renderTable() {
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  if (currentPage > totalPages) currentPage = totalPages;
  const start = (currentPage - 1) * pageSize;
  const page = filtered.slice(start, start + pageSize);
  document.getElementById('tableNote').textContent = `Showing ${page.length.toLocaleString()} rows on this page. Filtered rows: ${filtered.length.toLocaleString()}.`;
  if (!page.length) { document.getElementById('tableWrap').innerHTML = '<div style="padding:16px" class="note">No rows found.</div>'; return; }
  const cols = ['controls','batch_no','provider','supplier_category_name','region','date_received','aging_bucket','credit_term','calendar_payment_date','target_payment_date','expected_check_amount','check_amount','cv_no','check_no','payment_remarks'];
  const header = `<thead><tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead>`;
  const body = `<tbody>${page.map(row => renderRow(row, cols)).join('')}</tbody>`;
  document.getElementById('tableWrap').innerHTML = `<table>${header}${body}</table>`;
  document.getElementById('pagination').innerHTML = `<button onclick="prevPage()" ${currentPage<=1?'disabled':''}>Previous</button><button onclick="nextPage()" ${currentPage>=totalPages?'disabled':''}>Next</button><span class="note">Page ${currentPage.toLocaleString()} of ${totalPages.toLocaleString()}</span><select onchange="pageSize=Number(this.value);currentPage=1;renderTable()"><option value="50" ${pageSize==50?'selected':''}>50</option><option value="100" ${pageSize==100?'selected':''}>100</option><option value="250" ${pageSize==250?'selected':''}>250</option><option value="500" ${pageSize==500?'selected':''}>500</option></select>`;
}

function renderRow(row, cols) { return `<tr>${cols.map(c => renderCell(row, c)).join('')}</tr>`; }
function renderCell(row, col) {
  const key = escapeHtml(row.batch_no);
  if (col === 'controls') {
    return `<td><select onchange="updateRow('${key}','tagged_for_payment',this.value)"><option value="" ${!row.tagged_for_payment?'selected':''}>Not Tagged</option><option value="YES" ${upper(row.tagged_for_payment)==='YES'?'selected':''}>YES</option></select><input class="inline-input" placeholder="Processor" value="${escapeHtml(row.processor_name)}" onchange="updateRow('${key}','processor_name',this.value)" /><input class="inline-input" type="date" value="${escapeHtml(row.target_payment_date)}" onchange="updateRow('${key}','target_payment_date',this.value)" /><select onchange="updateRow('${key}','payment_priority',this.value)"><option value="" ${!row.payment_priority?'selected':''}>Priority</option><option value="URGENT" ${upper(row.payment_priority)==='URGENT'?'selected':''}>URGENT</option><option value="HIGH" ${upper(row.payment_priority)==='HIGH'?'selected':''}>HIGH</option><option value="NORMAL" ${upper(row.payment_priority)==='NORMAL'?'selected':''}>NORMAL</option><option value="LOW" ${upper(row.payment_priority)==='LOW'?'selected':''}>LOW</option></select><select onchange="updateRow('${key}','approval_status',this.value)"><option value="" ${!row.approval_status?'selected':''}>Approval</option><option value="APPROVED" ${upper(row.approval_status)==='APPROVED'?'selected':''}>APPROVED</option><option value="HOLD" ${upper(row.approval_status)==='HOLD'?'selected':''}>HOLD</option></select></td>`;
  }
  if (col === 'payment_remarks') return `<td><input class="remarks" value="${escapeHtml(row.payment_remarks)}" onchange="updateRow('${key}','payment_remarks',this.value)" /></td>`;
  if (col === 'expected_check_amount' || col === 'check_amount') return `<td>${money(row[col])}</td>`;
  if (col === 'payment_priority') return `<td class="priority-${norm(row[col])}">${escapeHtml(row[col])}</td>`;
  return `<td>${escapeHtml(row[col] || '')}</td>`;
}

async function updateRow(batchNo, field, value) {
  const actor = document.getElementById('actor').value || '';
  const row = ROWS.find(r => String(r.batch_no) === String(batchNo));
  const payload = { actor, provider: row?.provider || '', [field]: value };
  if (field === 'tagged_for_payment' && value === 'YES') payload.tagged_date = new Date().toISOString().slice(0,10);
  const response = await fetch(`/api/payments/${encodeURIComponent(batchNo)}`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
  const updated = await response.json();
  const idx = ROWS.findIndex(r => String(r.batch_no) === String(batchNo));
  if (idx >= 0) ROWS[idx] = Object.assign({}, ROWS[idx], updated);
  applyFilters(false);
}
function nextPage() { currentPage++; renderTable(); }
function prevPage() { currentPage--; renderTable(); }
['search','tagStatus','priorityFilter','approvalFilter','dateFrom','dateTo'].forEach(id => document.getElementById(id).addEventListener('input', () => applyFilters()));
loadRows();
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
