"""Generate a local HTML dashboard from Claims Analysis report CSV files.

Usage:
    python -m claims_analysis.html_dashboard --reports-dir reports/latest

Output:
    reports/latest/dashboard.html
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_DASHBOARD_ROW_LIMIT = 100000

REPORT_FILES = {
    "summary": "summary.csv",
    "results": "claims_analysis_output.csv",
    "paid": "paid_batches.csv",
    "unpaid": "unpaid_batches.csv",
    "provider_reconciliation": "provider_amount_reconciliation.csv",
    "date_summary": "date_created_summary.csv",
    "variances": "batch_variances.csv",
    "for_review": "for_review.csv",
    "unmatched": "unmatched_batches.csv",
    "duplicate_checks": "duplicate_checks.csv",
    "duplicate_cv": "duplicate_cv.csv",
}


def read_csv_preview(path: Path, limit: int = DEFAULT_DASHBOARD_ROW_LIMIT) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return pd.read_csv(path, dtype=str, nrows=limit).fillna("").to_dict(orient="records")


def read_summary(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str).fillna("")
    if not {"metric", "value"}.issubset(df.columns):
        return {}
    return dict(zip(df["metric"], df["value"]))


def count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="ignore") as file:
        return max(sum(1 for _ in file) - 1, 0)


def build_dashboard_data(reports_dir: Path, preview_limit: int = DEFAULT_DASHBOARD_ROW_LIMIT) -> dict[str, object]:
    data = {
        "reports_dir": str(reports_dir),
        "summary": read_summary(reports_dir / REPORT_FILES["summary"]),
        "row_counts": {},
        "tables": {},
        "preview_limit": preview_limit,
    }
    for key, filename in REPORT_FILES.items():
        path = reports_dir / filename
        data["row_counts"][key] = count_rows(path)
        data["tables"][key] = read_csv_preview(path, limit=preview_limit)
    return data


def render_html(data: dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Claims Reconciliation Dashboard</title>
  <script src=\"https://cdn.jsdelivr.net/npm/chart.js\"></script>
  <style>
    :root {{
      --bg: #f3f6fb;
      --card: #ffffff;
      --text: #172033;
      --muted: #64748b;
      --border: #dbe3ef;
      --primary: #1d4ed8;
      --danger: #b91c1c;
      --good: #047857;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; background: var(--bg); color: var(--text); }}
    header {{ background: #0f172a; color: white; padding: 22px 28px; }}
    header h1 {{ margin: 0 0 6px 0; font-size: clamp(20px, 2.2vw, 30px); }}
    header p {{ margin: 0; color: #cbd5e1; font-size: 13px; }}
    main {{ padding: 22px; }}
    .layout {{ display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 18px; align-items: start; }}
    .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 16px; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08); min-width: 0; }}
    .filters {{ position: sticky; top: 14px; max-height: calc(100vh - 28px); overflow: auto; }}
    .filters h2, .section-title {{ margin: 0 0 12px 0; font-size: 16px; }}
    label {{ display: block; font-size: 12px; color: var(--muted); margin: 12px 0 5px; }}
    select, input {{ width: 100%; padding: 10px 11px; border: 1px solid var(--border); border-radius: 9px; background: white; }}
    .date-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
    .filter-actions {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 14px; }}
    button {{ border: 1px solid var(--border); background: white; padding: 10px 12px; border-radius: 9px; cursor: pointer; font-weight: 700; }}
    button.primary {{ background: var(--primary); color: white; border-color: var(--primary); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; margin-bottom: 16px; }}
    .metric-card {{ min-height: 105px; display: flex; flex-direction: column; justify-content: space-between; overflow: hidden; }}
    .metric-label {{ color: var(--muted); font-size: clamp(11px, 1vw, 13px); min-height: 34px; white-space: normal; line-height: 1.25; overflow-wrap: anywhere; }}
    .metric-value {{ font-size: clamp(17px, 1.8vw, 26px); font-weight: 800; line-height: 1.15; overflow-wrap: anywhere; word-break: break-word; }}
    .charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 14px; margin-bottom: 16px; }}
    .chart-box {{ height: 360px; overflow: hidden; }}
    .chart-box canvas {{ width: 100% !important; height: 300px !important; }}
    .tabs {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }}
    .tab {{ border-radius: 999px; padding: 9px 13px; }}
    .tab.active {{ background: var(--primary); color: white; border-color: var(--primary); }}
    .toolbar {{ display: grid; grid-template-columns: minmax(240px, 1fr) auto; gap: 10px; align-items: center; margin-bottom: 10px; }}
    .note {{ color: var(--muted); font-size: 12px; }}
    .table-wrap {{ background: white; border: 1px solid var(--border); border-radius: 12px; overflow: auto; max-height: 68vh; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
    th, td {{ border-bottom: 1px solid var(--border); padding: 8px 9px; text-align: left; white-space: nowrap; }}
    th {{ background: #f8fafc; position: sticky; top: 0; z-index: 1; }}
    tr:hover td {{ background: #f9fafb; }}
    .status-review, .status-variance, .status-unpaid {{ color: var(--danger); font-weight: 800; }}
    .status-ok, .status-matched, .status-paid {{ color: var(--good); font-weight: 800; }}
    footer {{ padding: 0 24px 24px; color: var(--muted); font-size: 12px; }}
    @media (max-width: 1050px) {{ .layout {{ grid-template-columns: 1fr; }} .filters {{ position: static; max-height: none; }} .toolbar {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Claims Reconciliation Dashboard</h1>
    <p id=\"reportPath\"></p>
  </header>
  <main>
    <div class=\"layout\">
      <aside class=\"card filters\">
        <h2>Filters</h2>

        <label>Provider / Hospital</label>
        <select id=\"providerFilter\"></select>
        <input id=\"providerTextFilter\" placeholder=\"Type provider/hospital name...\" />

        <label>Payment Status</label>
        <select id=\"paymentFilter\"><option value=\"ALL\">All</option><option value=\"PAID\">Paid</option><option value=\"UNPAID\">Unpaid</option></select>

        <label>Supplier Category</label>
        <select id=\"categoryFilter\"><option value=\"ALL\">All</option><option value=\"Hospital\">Hospital</option><option value=\"Professional\">Professional</option></select>

        <label>Reconciliation Status</label>
        <select id=\"reconFilter\"><option value=\"ALL\">All</option><option value=\"MATCHED\">Matched</option><option value=\"VARIANCE\">Variance</option></select>

        <label>Date Created / Check Date Range</label>
        <div class=\"date-row\">
          <input id=\"dateFromFilter\" type=\"date\" />
          <input id=\"dateToFilter\" type=\"date\" />
        </div>

        <label>Batch No</label>
        <input id=\"batchTextFilter\" placeholder=\"Type batch no...\" />

        <label>Check No</label>
        <input id=\"checkTextFilter\" placeholder=\"Type check no...\" />

        <label>CV No</label>
        <input id=\"cvTextFilter\" placeholder=\"Type CV no...\" />

        <label>Global Search</label>
        <input id=\"searchInput\" placeholder=\"Search any visible value...\" />

        <div class=\"filter-actions\"><button class=\"primary\" onclick=\"applyFilters()\">Apply</button><button onclick=\"resetFilters()\">Reset</button></div>
      </aside>
      <section>
        <section class=\"grid\" id=\"metrics\"></section>
        <section class=\"charts\">
          <div class=\"card chart-box\"><div class=\"section-title\">Paid vs Unpaid</div><canvas id=\"paymentChart\"></canvas></div>
          <div class=\"card chart-box\"><div class=\"section-title\">Top Providers by Claims Amount</div><canvas id=\"providerChart\"></canvas></div>
          <div class=\"card chart-box\"><div class=\"section-title\">Claims vs Checks</div><canvas id=\"amountChart\"></canvas></div>
        </section>
        <section class=\"card\">
          <div class=\"tabs\" id=\"tabs\"></div>
          <div class=\"toolbar\"><span class=\"note\" id=\"tableNote\"></span><button onclick=\"downloadActiveCsv()\">CSV file name</button></div>
          <div class=\"table-wrap\" id=\"tableWrap\"></div>
        </section>
      </section>
    </div>
  </main>
  <footer>Dashboard generated from enhanced Claims Analysis reports. Filters apply to KPI cards, charts, and table rows.</footer>
<script>
const DATA = {payload};
const TABLE_LABELS = {{
  provider_reconciliation: 'Provider Totals', results: 'All Batches', paid: 'Paid', unpaid: 'Unpaid', variances: 'Batch Variances', for_review: 'For Review', duplicate_checks: 'Duplicate Checks', duplicate_cv: 'Duplicate CV', date_summary: 'Date Summary'
}};
const FILE_NAMES = {{
  provider_reconciliation: 'provider_amount_reconciliation.csv', results: 'claims_analysis_output.csv', paid: 'paid_batches.csv', unpaid: 'unpaid_batches.csv', variances: 'batch_variances.csv', for_review: 'for_review.csv', duplicate_checks: 'duplicate_checks.csv', duplicate_cv: 'duplicate_cv.csv', date_summary: 'date_created_summary.csv'
}};
const TABLE_KEYS = ['provider_reconciliation','results','paid','unpaid','variances','for_review','duplicate_checks','duplicate_cv','date_summary'];
let activeTable = 'provider_reconciliation';
let charts = {{}};

function num(v) {{ const n = Number(String(v ?? '').replaceAll(',', '')); return Number.isNaN(n) ? 0 : n; }}
function money(v) {{ return num(v).toLocaleString(undefined, {{minimumFractionDigits: 2, maximumFractionDigits: 2}}); }}
function fmt(v) {{ const n = Number(v); return !Number.isNaN(n) && String(v ?? '').match(/^[-0-9.]+$/) ? n.toLocaleString() : (v ?? '0'); }}
function rows(key) {{ return DATA.tables[key] || []; }}
function getMainRows() {{ return rows('results'); }}
function escapeHtml(value) {{ return String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;'); }}
function norm(v) {{ return String(v ?? '').trim().toLowerCase(); }}
function includesText(value, query) {{ return !query || norm(value).includes(query); }}
function rowDateValue(row) {{ return row.date_created || row.created_date || row.check_date || ''; }}
function parseDate(value) {{
  const text = String(value ?? '').split(',')[0].trim();
  if (!text || text === 'NO CHECK DATE') return null;
  const d = new Date(text);
  return Number.isNaN(d.getTime()) ? null : d;
}}

function populateFilters() {{
  document.getElementById('reportPath').textContent = `Source: ${{DATA.reports_dir}} | Loaded rows: ${{getMainRows().length.toLocaleString()}} of ${{(DATA.row_counts.results || getMainRows().length).toLocaleString()}}`;
  const providers = [...new Set(getMainRows().map(r => r.provider || 'UNKNOWN'))].sort();
  document.getElementById('providerFilter').innerHTML = '<option value="ALL">All Providers</option>' + providers.map(p => `<option value="${{escapeHtml(p)}}">${{escapeHtml(p)}}</option>`).join('');
}}

function filterValues() {{
  return {{
    provider: document.getElementById('providerFilter').value,
    providerText: norm(document.getElementById('providerTextFilter').value),
    payment: document.getElementById('paymentFilter').value,
    category: document.getElementById('categoryFilter').value,
    recon: document.getElementById('reconFilter').value,
    dateFrom: document.getElementById('dateFromFilter').value ? new Date(document.getElementById('dateFromFilter').value) : null,
    dateTo: document.getElementById('dateToFilter').value ? new Date(document.getElementById('dateToFilter').value) : null,
    batchText: norm(document.getElementById('batchTextFilter').value),
    checkText: norm(document.getElementById('checkTextFilter').value),
    cvText: norm(document.getElementById('cvTextFilter').value),
    search: norm(document.getElementById('searchInput').value)
  }};
}}

function passesDate(row, f) {{
  if (!f.dateFrom && !f.dateTo) return true;
  const d = parseDate(rowDateValue(row));
  if (!d) return false;
  if (f.dateFrom && d < f.dateFrom) return false;
  if (f.dateTo) {{ const end = new Date(f.dateTo); end.setHours(23,59,59,999); if (d > end) return false; }}
  return true;
}}

function filterBatchRows(inputRows) {{
  const f = filterValues();
  return inputRows.filter(r => {{
    const provider = r.provider || 'UNKNOWN';
    const allText = Object.values(r).join(' ').toLowerCase();
    return (f.provider === 'ALL' || provider === f.provider)
      && includesText(provider, f.providerText)
      && (f.payment === 'ALL' || r.payment_status === f.payment)
      && (f.category === 'ALL' || r.supplier_category_name === f.category)
      && (f.recon === 'ALL' || r.reconciliation_status === f.recon)
      && includesText(r.batch_no, f.batchText)
      && includesText(r.check_no, f.checkText)
      && includesText(r.cv_no, f.cvText)
      && passesDate(r, f)
      && (!f.search || allText.includes(f.search));
  }});
}}

function groupProviderRowsFromFilteredBatches() {{
  const map = new Map();
  filterBatchRows(getMainRows()).forEach(r => {{
    const provider = r.provider || 'UNKNOWN';
    if (!map.has(provider)) map.set(provider, {{provider, batch_count:0, paid_batches:0, unpaid_batches:0, claims_amount:0, withholding_tax:0, expected_check_amount:0, check_amount:0, difference:0, variance_batch_count:0}});
    const p = map.get(provider);
    p.batch_count += 1;
    if (r.payment_status === 'PAID') p.paid_batches += 1;
    if (r.payment_status === 'UNPAID') p.unpaid_batches += 1;
    p.claims_amount += num(r.claims_amount);
    p.withholding_tax += num(r.withholding_tax);
    p.expected_check_amount += num(r.expected_check_amount);
    p.check_amount += num(r.check_amount);
    p.difference += num(r.difference);
    if (r.reconciliation_status === 'VARIANCE') p.variance_batch_count += 1;
  }});
  return [...map.values()].map(r => {{ ['claims_amount','withholding_tax','expected_check_amount','check_amount','difference'].forEach(c => r[c] = money(r[c])); return r; }}).sort((a,b)=>num(b.claims_amount)-num(a.claims_amount));
}}

function groupDateRowsFromFilteredBatches() {{
  const map = new Map();
  filterBatchRows(getMainRows()).forEach(r => {{
    const date = rowDateValue(r) || 'NO DATE';
    if (!map.has(date)) map.set(date, {{date_created: date, batch_count:0, paid_batches:0, unpaid_batches:0, claims_amount:0, check_amount:0, difference:0}});
    const d = map.get(date);
    d.batch_count += 1;
    if (r.payment_status === 'PAID') d.paid_batches += 1;
    if (r.payment_status === 'UNPAID') d.unpaid_batches += 1;
    d.claims_amount += num(r.claims_amount);
    d.check_amount += num(r.check_amount);
    d.difference += num(r.difference);
  }});
  return [...map.values()].map(r => {{ ['claims_amount','check_amount','difference'].forEach(c => r[c] = money(r[c])); return r; }});
}}

function filteredTableRows(key) {{
  if (key === 'provider_reconciliation') return groupProviderRowsFromFilteredBatches();
  if (key === 'date_summary') return groupDateRowsFromFilteredBatches();
  if (['results','paid','unpaid','variances','for_review'].includes(key)) return filterBatchRows(rows(key));
  const f = filterValues();
  return rows(key).filter(r => !f.search || Object.values(r).join(' ').toLowerCase().includes(f.search));
}}

function calcMetrics() {{
  const data = filterBatchRows(getMainRows());
  const sum = col => data.reduce((a,r) => a + num(r[col]), 0);
  return [
    ['Total Batches', data.length.toLocaleString()],
    ['Paid Batches', data.filter(r => r.payment_status === 'PAID').length.toLocaleString()],
    ['Unpaid Batches', data.filter(r => r.payment_status === 'UNPAID').length.toLocaleString()],
    ['Claims Amount', money(sum('claims_amount'))],
    ['Expected Check', money(sum('expected_check_amount'))],
    ['Actual Check', money(sum('check_amount'))],
    ['Difference', money(sum('difference'))],
    ['Variance Batches', data.filter(r => r.reconciliation_status === 'VARIANCE').length.toLocaleString()]
  ];
}}

function renderMetrics() {{ document.getElementById('metrics').innerHTML = calcMetrics().map(([label,value]) => `<div class="card metric-card"><div class="metric-label">${{label}}</div><div class="metric-value">${{value}}</div></div>`).join(''); }}
function destroyCharts() {{ Object.values(charts).forEach(c => c.destroy()); charts = {{}}; }}
function shortLabel(s) {{ return String(s || '').length > 28 ? String(s).slice(0,25) + '...' : s; }}
function renderCharts() {{
  destroyCharts();
  const data = filterBatchRows(getMainRows());
  const paid = data.filter(r => r.payment_status === 'PAID').length;
  const unpaid = data.filter(r => r.payment_status === 'UNPAID').length;
  charts.payment = new Chart(document.getElementById('paymentChart'), {{type:'doughnut', data:{{labels:['Paid','Unpaid'], datasets:[{{data:[paid,unpaid]}}]}}, options:{{responsive:true, maintainAspectRatio:false, plugins:{{legend:{{position:'bottom'}}}}}}}});
  const providerMap = new Map();
  data.forEach(r => providerMap.set(r.provider || 'UNKNOWN', (providerMap.get(r.provider || 'UNKNOWN') || 0) + num(r.claims_amount)));
  const top = [...providerMap.entries()].sort((a,b)=>b[1]-a[1]).slice(0,10);
  charts.provider = new Chart(document.getElementById('providerChart'), {{type:'bar', data:{{labels:top.map(x=>shortLabel(x[0])), datasets:[{{label:'Claims Amount', data:top.map(x=>x[1])}}]}}, options:{{indexAxis:'y', responsive:true, maintainAspectRatio:false, plugins:{{legend:{{display:false}}}}, scales:{{y:{{ticks:{{font:{{size:10}}}}}}}}}}}});
  charts.amount = new Chart(document.getElementById('amountChart'), {{type:'bar', data:{{labels:['Claims','Expected Check','Actual Check'], datasets:[{{label:'Amount', data:[data.reduce((a,r)=>a+num(r.claims_amount),0), data.reduce((a,r)=>a+num(r.expected_check_amount),0), data.reduce((a,r)=>a+num(r.check_amount),0)]}}]}}, options:{{responsive:true, maintainAspectRatio:false, plugins:{{legend:{{display:false}}}}}}}});
}}

function renderTabs() {{ document.getElementById('tabs').innerHTML = TABLE_KEYS.map(key => `<button class="tab ${{key===activeTable?'active':''}}" onclick="setTable('${{key}}')">${{TABLE_LABELS[key]}} (${{filteredTableRows(key).length.toLocaleString()}})</button>`).join(''); }}
function setTable(key) {{ activeTable = key; applyFilters(); }}
function statusClass(c,v) {{ if (c === 'payment_status') return v === 'PAID' ? 'status-paid' : 'status-unpaid'; if (c === 'reconciliation_status') return v === 'MATCHED' ? 'status-matched' : 'status-variance'; if (c === 'payee_match_status') return v === 'OK' ? 'status-ok' : v === 'For Review' ? 'status-review' : ''; return ''; }}
function renderTable() {{
  const tableRows = filteredTableRows(activeTable);
  const sourceCount = DATA.row_counts[activeTable] || rows(activeTable).length;
  const loadedCount = rows(activeTable).length;
  document.getElementById('tableNote').textContent = `Showing ${{tableRows.length.toLocaleString()}} filtered rows. Loaded ${{loadedCount.toLocaleString()}} of ${{sourceCount.toLocaleString()}} source rows. CSV: ${{FILE_NAMES[activeTable]}}`;
  const wrap = document.getElementById('tableWrap');
  if (!tableRows.length) {{ wrap.innerHTML = '<div style="padding:18px" class="note">No rows match the active filters.</div>'; return; }}
  const cols = Object.keys(tableRows[0]);
  wrap.innerHTML = `<table><thead><tr>${{cols.map(c=>`<th>${{escapeHtml(c)}}</th>`).join('')}}</tr></thead><tbody>${{tableRows.map(r=>`<tr>${{cols.map(c=>`<td class="${{statusClass(c,r[c])}}">${{escapeHtml(r[c])}}</td>`).join('')}}</tr>`).join('')}}</tbody></table>`;
}}
function applyFilters() {{ renderMetrics(); renderCharts(); renderTabs(); renderTable(); }}
function resetFilters() {{ ['providerFilter','paymentFilter','categoryFilter','reconFilter'].forEach(id => document.getElementById(id).value='ALL'); ['providerTextFilter','dateFromFilter','dateToFilter','batchTextFilter','checkTextFilter','cvTextFilter','searchInput'].forEach(id => document.getElementById(id).value=''); applyFilters(); }}
function downloadActiveCsv() {{ alert(`Open this file from reports/latest: ${{FILE_NAMES[activeTable]}}`); }}

['providerTextFilter','dateFromFilter','dateToFilter','batchTextFilter','checkTextFilter','cvTextFilter','searchInput'].forEach(id => document.getElementById(id).addEventListener('input', applyFilters));
['providerFilter','paymentFilter','categoryFilter','reconFilter'].forEach(id => document.getElementById(id).addEventListener('change', applyFilters));
populateFilters();
applyFilters();
</script>
</body>
</html>
"""


def generate_dashboard(reports_dir: str | Path = "reports/latest", preview_limit: int = DEFAULT_DASHBOARD_ROW_LIMIT) -> Path:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    data = build_dashboard_data(reports_path, preview_limit=preview_limit)
    html = render_html(data)
    output_path = reports_path / "dashboard.html"
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate local HTML dashboard from Claims Analysis reports.")
    parser.add_argument("--reports-dir", default="reports/latest", help="Folder containing generated report CSV files")
    parser.add_argument("--preview-limit", type=int, default=DEFAULT_DASHBOARD_ROW_LIMIT, help="Maximum rows embedded per table")
    args = parser.parse_args()
    output_path = generate_dashboard(args.reports_dir, preview_limit=args.preview_limit)
    print(f"Dashboard generated: {output_path}")


if __name__ == "__main__":
    main()
