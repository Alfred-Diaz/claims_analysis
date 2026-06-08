from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_REPORTS_DIR = "reports/latest"
SOURCE_FILE = "tagged_for_payment_workflow.csv"
OUTPUT_FILE = "payment_workflow_dashboard.html"


def load_rows(reports_dir: Path, limit: int = 100000) -> list[dict[str, object]]:
    path = reports_dir / SOURCE_FILE
    if not path.exists():
        return []
    return pd.read_csv(path, dtype=str, nrows=limit).fillna("").to_dict(orient="records")


def render_html(rows: list[dict[str, object]], reports_dir: Path) -> str:
    payload = json.dumps(rows, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Payment Tagging Workflow</title>
<style>
:root {{ --bg:#f3f6fb; --card:#fff; --text:#172033; --muted:#64748b; --border:#dbe3ef; --primary:#1d4ed8; --danger:#b91c1c; --good:#047857; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:Arial,Helvetica,sans-serif; background:var(--bg); color:var(--text); }}
header {{ background:#0f172a; color:white; padding:22px 28px; }}
header h1 {{ margin:0 0 6px; font-size:24px; }}
header p {{ margin:0; color:#cbd5e1; font-size:13px; }}
main {{ padding:20px; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:16px; box-shadow:0 1px 3px rgba(15,23,42,.08); margin-bottom:14px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; }}
.metric-label {{ color:var(--muted); font-size:12px; margin-bottom:8px; }}
.metric-value {{ font-size:24px; font-weight:800; }}
.toolbar {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:10px; align-items:end; }}
label {{ display:block; color:var(--muted); font-size:12px; margin-bottom:5px; }}
input,select,textarea {{ width:100%; padding:9px 10px; border:1px solid var(--border); border-radius:8px; background:white; font-family:inherit; }}
button {{ border:1px solid var(--border); background:white; padding:10px 12px; border-radius:9px; cursor:pointer; font-weight:700; }}
button.primary {{ background:var(--primary); color:white; border-color:var(--primary); }}
button.good {{ background:var(--good); color:white; border-color:var(--good); }}
button.danger {{ background:var(--danger); color:white; border-color:var(--danger); }}
.note {{ color:var(--muted); font-size:12px; }}
.table-wrap {{ overflow:auto; max-height:68vh; border:1px solid var(--border); border-radius:12px; background:white; }}
table {{ border-collapse:collapse; width:100%; font-size:12px; }}
th,td {{ border-bottom:1px solid var(--border); padding:8px 9px; text-align:left; white-space:nowrap; }}
th {{ position:sticky; top:0; background:#f8fafc; z-index:1; }}
tr:hover td {{ background:#f9fafb; }}
.tagged {{ color:var(--good); font-weight:800; }}
.untagged {{ color:var(--danger); font-weight:800; }}
.inline-input {{ min-width:135px; }}
.remarks {{ min-width:220px; }}
.pagination {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:10px; }}
</style>
</head>
<body>
<header>
<h1>Payment Tagging Workflow</h1>
<p>Source: {reports_dir / SOURCE_FILE}. Tags are saved in this browser and can be exported to CSV.</p>
</header>
<main>
<section class="grid" id="metrics"></section>
<section class="card">
<div class="toolbar">
<div><label>Global Search</label><input id="search" placeholder="Batch, provider, region, amount, etc." /></div>
<div><label>Tag Status</label><select id="tagStatus"><option value="ALL">All</option><option value="TAGGED">Tagged</option><option value="UNTAGGED">Untagged</option></select></div>
<div><label>Processor</label><input id="processorFilter" placeholder="Processor name" /></div>
<div><label>Target Payment From</label><input id="dateFrom" type="date" /></div>
<div><label>Target Payment To</label><input id="dateTo" type="date" /></div>
<div><button class="primary" onclick="applyFilters()">Apply Filters</button></div>
<div><button class="good" onclick="exportTaggedCsv()">Export Tagged CSV</button></div>
<div><button onclick="exportAllCsv()">Export Current View</button></div>
</div>
<p class="note">Use the table fields to tag payment rows. Changes are saved automatically in your browser using the batch number as the key.</p>
</section>
<section class="card">
<div id="tableNote" class="note"></div>
<div class="table-wrap" id="tableWrap"></div>
<div class="pagination" id="pagination"></div>
</section>
</main>
<script>
const SOURCE_ROWS = {payload};
const STORAGE_KEY = 'claims_payment_tags_v1';
let currentPage = 1;
let pageSize = 100;
let filtered = [];

function loadTags() {{
  try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}'); }} catch {{ return {{}}; }}
}}
function saveTags(tags) {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(tags)); }}
function rowKey(row) {{ return String(row.batch_no || row.batch || row.id || '').trim(); }}
function getTag(row) {{ return loadTags()[rowKey(row)] || {{}}; }}
function setTag(key, patch) {{ const tags = loadTags(); tags[key] = Object.assign({{}}, tags[key] || {{}}, patch); saveTags(tags); }}
function val(row, col) {{ const tag = getTag(row); return tag[col] ?? row[col] ?? ''; }}
function isTagged(row) {{ return String(val(row, 'tagged_for_payment')).toUpperCase() === 'YES'; }}
function num(v) {{ const n = Number(String(v ?? '').replaceAll(',', '')); return Number.isNaN(n) ? 0 : n; }}
function money(v) {{ return num(v).toLocaleString(undefined, {{minimumFractionDigits:2, maximumFractionDigits:2}}); }}
function escapeHtml(v) {{ return String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;'); }}
function norm(v) {{ return String(v ?? '').trim().toLowerCase(); }}
function parseDate(v) {{ const d = new Date(v); return Number.isNaN(d.getTime()) ? null : d; }}
function rowForExport(row) {{
  const tag = getTag(row);
  return Object.assign({{}}, row, tag, {{
    tagged_for_payment: tag.tagged_for_payment || row.tagged_for_payment || '',
    processor_name: tag.processor_name || row.processor_name || '',
    target_payment_date: tag.target_payment_date || row.target_payment_date || '',
    tagged_date: tag.tagged_date || row.tagged_date || '',
    payment_priority: tag.payment_priority || row.payment_priority || '',
    payment_remarks: tag.payment_remarks || row.payment_remarks || ''
  }});
}}

function passFilters(row) {{
  const q = norm(document.getElementById('search').value);
  const status = document.getElementById('tagStatus').value;
  const processor = norm(document.getElementById('processorFilter').value);
  const from = document.getElementById('dateFrom').value ? parseDate(document.getElementById('dateFrom').value) : null;
  const to = document.getElementById('dateTo').value ? parseDate(document.getElementById('dateTo').value) : null;
  const exportRow = rowForExport(row);
  const allText = Object.values(exportRow).join(' ').toLowerCase();
  if (q && !allText.includes(q)) return false;
  if (status === 'TAGGED' && !isTagged(row)) return false;
  if (status === 'UNTAGGED' && isTagged(row)) return false;
  if (processor && !norm(exportRow.processor_name).includes(processor)) return false;
  const target = parseDate(exportRow.target_payment_date);
  if ((from || to) && !target) return false;
  if (from && target < from) return false;
  if (to) {{ const end = new Date(to); end.setHours(23,59,59,999); if (target > end) return false; }}
  return true;
}}

function calcMetrics() {{
  const rows = SOURCE_ROWS.map(rowForExport);
  const tagged = rows.filter(r => String(r.tagged_for_payment).toUpperCase() === 'YES');
  const untagged = rows.length - tagged.length;
  const taggedAmount = tagged.reduce((a,r) => a + num(r.expected_check_amount), 0);
  const filteredAmount = filtered.map(rowForExport).reduce((a,r) => a + num(r.expected_check_amount), 0);
  const metrics = [
    ['Workflow Rows', rows.length.toLocaleString()],
    ['Tagged', tagged.length.toLocaleString()],
    ['Untagged', untagged.toLocaleString()],
    ['Tagged Amount', money(taggedAmount)],
    ['Filtered Rows', filtered.length.toLocaleString()],
    ['Filtered Amount', money(filteredAmount)]
  ];
  document.getElementById('metrics').innerHTML = metrics.map(([l,v]) => `<div class="card"><div class="metric-label">${{l}}</div><div class="metric-value">${{v}}</div></div>`).join('');
}}

function renderTable() {{
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  if (currentPage > totalPages) currentPage = totalPages;
  const start = (currentPage - 1) * pageSize;
  const page = filtered.slice(start, start + pageSize);
  document.getElementById('tableNote').textContent = `Showing ${{page.length.toLocaleString()}} rows on this page. Filtered rows: ${{filtered.length.toLocaleString()}}.`;
  if (!page.length) {{ document.getElementById('tableWrap').innerHTML = '<div style="padding:16px" class="note">No rows found.</div>'; return; }}
  const cols = ['tag_controls','batch_no','provider','supplier_category_name','region','date_received','aging_bucket','credit_term','calendar_payment_date','scheduled_payment_date','expected_check_amount','check_amount','cv_no','check_no','check_date','payment_remarks'];
  const header = `<thead><tr>${{cols.map(c => `<th>${{escapeHtml(c)}}</th>`).join('')}}</tr></thead>`;
  const body = `<tbody>${{page.map(row => renderRow(row, cols)).join('')}}</tbody>`;
  document.getElementById('tableWrap').innerHTML = `<table>${{header}}${{body}}</table>`;
  document.getElementById('pagination').innerHTML = `<button onclick="prevPage()" ${{currentPage<=1?'disabled':''}}>Previous</button><button onclick="nextPage()" ${{currentPage>=totalPages?'disabled':''}}>Next</button><span class="note">Page ${{currentPage.toLocaleString()}} of ${{totalPages.toLocaleString()}}</span><select onchange="pageSize=Number(this.value);currentPage=1;renderTable()"><option value="50" ${{pageSize==50?'selected':''}}>50</option><option value="100" ${{pageSize==100?'selected':''}}>100</option><option value="250" ${{pageSize==250?'selected':''}}>250</option><option value="500" ${{pageSize==500?'selected':''}}>500</option></select>`;
}}

function renderRow(row, cols) {{
  const key = rowKey(row);
  const exportRow = rowForExport(row);
  return `<tr>${{cols.map(c => renderCell(row, exportRow, key, c)).join('')}}</tr>`;
}}
function renderCell(row, exportRow, key, col) {{
  if (col === 'tag_controls') {{
    const tagged = String(exportRow.tagged_for_payment).toUpperCase() === 'YES';
    return `<td><select onchange="updateTag('${{escapeHtml(key)}}','tagged_for_payment',this.value)"><option value="" ${{!exportRow.tagged_for_payment?'selected':''}}>Not Tagged</option><option value="YES" ${{tagged?'selected':''}}>YES</option></select><input class="inline-input" placeholder="Processor" value="${{escapeHtml(exportRow.processor_name)}}" onchange="updateTag('${{escapeHtml(key)}}','processor_name',this.value)" /><input class="inline-input" type="date" value="${{escapeHtml(exportRow.target_payment_date)}}" onchange="updateTag('${{escapeHtml(key)}}','target_payment_date',this.value)" /><select onchange="updateTag('${{escapeHtml(key)}}','payment_priority',this.value)"><option value="" ${{!exportRow.payment_priority?'selected':''}}>Priority</option><option value="HIGH" ${{exportRow.payment_priority==='HIGH'?'selected':''}}>HIGH</option><option value="NORMAL" ${{exportRow.payment_priority==='NORMAL'?'selected':''}}>NORMAL</option><option value="LOW" ${{exportRow.payment_priority==='LOW'?'selected':''}}>LOW</option></select></td>`;
  }}
  if (col === 'payment_remarks') {{ return `<td><input class="remarks" value="${{escapeHtml(exportRow.payment_remarks)}}" onchange="updateTag('${{escapeHtml(key)}}','payment_remarks',this.value)" /></td>`; }}
  if (col === 'expected_check_amount' || col === 'check_amount') return `<td>${{money(exportRow[col])}}</td>`;
  return `<td>${{escapeHtml(exportRow[col] || '')}}</td>`;
}}
function updateTag(key, field, value) {{
  const patch = {{[field]: value}};
  if (field === 'tagged_for_payment' && value === 'YES') patch.tagged_date = new Date().toISOString().slice(0,10);
  setTag(key, patch);
  applyFilters(false);
}}
function applyFilters(resetPage=true) {{ if (resetPage) currentPage = 1; filtered = SOURCE_ROWS.filter(passFilters); calcMetrics(); renderTable(); }}
function nextPage() {{ currentPage++; renderTable(); }}
function prevPage() {{ currentPage--; renderTable(); }}
function toCsv(rows) {{
  if (!rows.length) return '';
  const cols = [...new Set(rows.flatMap(r => Object.keys(r)))];
  const esc = v => '"' + String(v ?? '').replaceAll('"','""') + '"';
  return [cols.map(esc).join(','), ...rows.map(r => cols.map(c => esc(r[c])).join(','))].join('\n');
}}
function downloadCsv(filename, rows) {{
  const blob = new Blob([toCsv(rows)], {{type:'text/csv;charset=utf-8;'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}}
function exportTaggedCsv() {{ downloadCsv('tagged_payment_workflow_export.csv', SOURCE_ROWS.map(rowForExport).filter(r => String(r.tagged_for_payment).toUpperCase() === 'YES')); }}
function exportAllCsv() {{ downloadCsv('payment_workflow_current_view.csv', filtered.map(rowForExport)); }}
['search','tagStatus','processorFilter','dateFrom','dateTo'].forEach(id => document.getElementById(id).addEventListener('input', () => applyFilters()));
applyFilters();
</script>
</body>
</html>"""


def generate_dashboard(reports_dir: str | Path = DEFAULT_REPORTS_DIR, limit: int = 100000) -> Path:
    reports_path = Path(reports_dir)
    rows = load_rows(reports_path, limit=limit)
    output_path = reports_path / OUTPUT_FILE
    output_path.write_text(render_html(rows, reports_path), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate interactive payment tagging workflow dashboard.")
    parser.add_argument("--reports-dir", default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--limit", type=int, default=100000)
    args = parser.parse_args()
    print(f"Payment workflow dashboard generated: {generate_dashboard(args.reports_dir, args.limit)}")


if __name__ == "__main__":
    main()
