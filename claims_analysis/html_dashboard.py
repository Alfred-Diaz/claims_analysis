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


def read_csv_preview(path: Path, limit: int = 5000) -> list[dict[str, object]]:
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


def build_dashboard_data(reports_dir: Path, preview_limit: int = 5000) -> dict[str, object]:
    data = {
        "reports_dir": str(reports_dir),
        "summary": read_summary(reports_dir / REPORT_FILES["summary"]),
        "row_counts": {},
        "tables": {},
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
      --primary-soft: #eff6ff;
      --danger: #b91c1c;
      --good: #047857;
      --warn: #b45309;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; background: var(--bg); color: var(--text); }}
    header {{ background: #0f172a; color: white; padding: 22px 28px; }}
    header h1 {{ margin: 0 0 6px 0; font-size: clamp(20px, 2.2vw, 30px); }}
    header p {{ margin: 0; color: #cbd5e1; font-size: 13px; }}
    main {{ padding: 22px; }}
    .layout {{ display: grid; grid-template-columns: 285px minmax(0, 1fr); gap: 18px; align-items: start; }}
    .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 16px; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08); }}
    .filters {{ position: sticky; top: 14px; }}
    .filters h2, .section-title {{ margin: 0 0 12px 0; font-size: 16px; }}
    label {{ display: block; font-size: 12px; color: var(--muted); margin: 12px 0 5px; }}
    select, input {{ width: 100%; padding: 10px 11px; border: 1px solid var(--border); border-radius: 9px; background: white; }}
    .filter-actions {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 14px; }}
    button {{ border: 1px solid var(--border); background: white; padding: 10px 12px; border-radius: 9px; cursor: pointer; font-weight: 700; }}
    button.primary {{ background: var(--primary); color: white; border-color: var(--primary); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(185px, 1fr)); gap: 12px; margin-bottom: 16px; }}
    .metric-card {{ min-width: 0; overflow: hidden; }}
    .metric-label {{ color: var(--muted); font-size: clamp(10px, 1vw, 12px); margin-bottom: 8px; white-space: normal; line-height: 1.25; }}
    .metric-value {{ font-size: clamp(16px, 2vw, 25px); font-weight: 800; line-height: 1.15; overflow-wrap: anywhere; word-break: break-word; }}
    .charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; margin-bottom: 16px; }}
    .chart-box {{ height: 300px; }}
    .chart-box canvas {{ width: 100% !important; height: 100% !important; }}
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
    @media (max-width: 900px) {{ .layout {{ grid-template-columns: 1fr; }} .filters {{ position: static; }} .toolbar {{ grid-template-columns: 1fr; }} }}
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
        <label>Payment Status</label>
        <select id=\"paymentFilter\"><option value=\"ALL\">All</option><option value=\"PAID\">Paid</option><option value=\"UNPAID\">Unpaid</option></select>
        <label>Supplier Category</label>
        <select id=\"categoryFilter\"><option value=\"ALL\">All</option><option value=\"Hospital\">Hospital</option><option value=\"Professional\">Professional</option></select>
        <label>Reconciliation Status</label>
        <select id=\"reconFilter\"><option value=\"ALL\">All</option><option value=\"MATCHED\">Matched</option><option value=\"VARIANCE\">Variance</option></select>
        <label>Check Date</label>
        <select id=\"dateFilter\"></select>
        <label>Search</label>
        <input id=\"searchInput\" placeholder=\"Batch no, provider, check no, CV no...\" />
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
          <div class=\"toolbar\"><span class=\"note\" id=\"tableNote\"></span><button onclick=\"downloadActiveCsv()\">Open CSV name</button></div>
          <div class=\"table-wrap\" id=\"tableWrap\"></div>
        </section>
      </section>
    </div>
  </main>
  <footer>Dashboard generated from enhanced Claims Analysis reports. Data is previewed for browser performance.</footer>
<script>
const DATA = {payload};
const TABLE_LABELS = {{
  provider_reconciliation: 'Provider Totals',
  results: 'All Batches',
  paid: 'Paid',
  unpaid: 'Unpaid',
  variances: 'Batch Variances',
  for_review: 'For Review',
  duplicate_checks: 'Duplicate Checks',
  duplicate_cv: 'Duplicate CV',
  date_summary: 'Date Summary'
}};
const FILE_NAMES = {{
  provider_reconciliation: 'provider_amount_reconciliation.csv',
  results: 'claims_analysis_output.csv',
  paid: 'paid_batches.csv',
  unpaid: 'unpaid_batches.csv',
  variances: 'batch_variances.csv',
  for_review: 'for_review.csv',
  duplicate_checks: 'duplicate_checks.csv',
  duplicate_cv: 'duplicate_cv.csv',
  date_summary: 'date_created_summary.csv'
}};
const TABLE_KEYS = ['provider_reconciliation','results','paid','unpaid','variances','for_review','duplicate_checks','duplicate_cv','date_summary'];
let activeTable = 'provider_reconciliation';
let filteredRows = [];
let charts = {{}};

function num(v) {{ const n = Number(String(v ?? '').replaceAll(',', '')); return Number.isNaN(n) ? 0 : n; }}
function money(v) {{ return num(v).toLocaleString(undefined, {{minimumFractionDigits: 2, maximumFractionDigits: 2}}); }}
function fmt(v) {{ const n = Number(v); return !Number.isNaN(n) && String(v ?? '').match(/^[-0-9.]+$/) ? n.toLocaleString() : (v ?? '0'); }}
function rows(key) {{ return DATA.tables[key] || []; }}
function escapeHtml(value) {{ return String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;'); }}
function getMainRows() {{ return rows('results'); }}

function populateFilters() {{
  document.getElementById('reportPath').textContent = `Source: ${{DATA.reports_dir}}`;
  const providers = [...new Set(getMainRows().map(r => r.provider || 'UNKNOWN'))].sort();
  document.getElementById('providerFilter').innerHTML = '<option value="ALL">All Providers</option>' + providers.map(p => `<option value="${{escapeHtml(p)}}">${{escapeHtml(p)}}</option>`).join('');
  const dates = [...new Set(getMainRows().map(r => r.check_date || 'NO CHECK DATE'))].sort();
  document.getElementById('dateFilter').innerHTML = '<option value="ALL">All Dates</option>' + dates.map(d => `<option value="${{escapeHtml(d)}}">${{escapeHtml(d)}}</option>`).join('');
}}

function currentFilterValues() {{
  return {{
    provider: document.getElementById('providerFilter').value,
    payment: document.getElementById('paymentFilter').value,
    category: document.getElementById('categoryFilter').value,
    recon: document.getElementById('reconFilter').value,
    date: document.getElementById('dateFilter').value,
    search: document.getElementById('searchInput').value.trim().toLowerCase()
  }};
}}

function filterBatchRows(inputRows) {{
  const f = currentFilterValues();
  return inputRows.filter(r => {{
    const provider = r.provider || 'UNKNOWN';
    const date = r.check_date || 'NO CHECK DATE';
    const text = Object.values(r).join(' ').toLowerCase();
    return (f.provider === 'ALL' || provider === f.provider)
      && (f.payment === 'ALL' || r.payment_status === f.payment)
      && (f.category === 'ALL' || r.supplier_category_name === f.category)
      && (f.recon === 'ALL' || r.reconciliation_status === f.recon)
      && (f.date === 'ALL' || date === f.date)
      && (!f.search || text.includes(f.search));
  }});
}}

function filteredTableRows(key) {{
  const base = rows(key);
  if (['results','paid','unpaid','variances','for_review'].includes(key)) return filterBatchRows(base);
  if (key === 'provider_reconciliation') {{
    const f = currentFilterValues();
    return base.filter(r => (f.provider === 'ALL' || (r.provider || 'UNKNOWN') === f.provider) && (!f.search || Object.values(r).join(' ').toLowerCase().includes(f.search)));
  }}
  return base.filter(r => !currentFilterValues().search || Object.values(r).join(' ').toLowerCase().includes(currentFilterValues().search));
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

function renderMetrics() {{
  document.getElementById('metrics').innerHTML = calcMetrics().map(([label,value]) => `<div class="card metric-card"><div class="metric-label">${{label}}</div><div class="metric-value">${{value}}</div></div>`).join('');
}}

function destroyCharts() {{ Object.values(charts).forEach(c => c.destroy()); charts = {{}}; }}
function renderCharts() {{
  destroyCharts();
  const data = filterBatchRows(getMainRows());
  const paid = data.filter(r => r.payment_status === 'PAID').length;
  const unpaid = data.filter(r => r.payment_status === 'UNPAID').length;
  charts.payment = new Chart(document.getElementById('paymentChart'), {{type:'doughnut', data:{{labels:['Paid','Unpaid'], datasets:[{{data:[paid,unpaid]}}]}}, options:{{responsive:true, maintainAspectRatio:false}}}});

  const providerMap = new Map();
  data.forEach(r => providerMap.set(r.provider || 'UNKNOWN', (providerMap.get(r.provider || 'UNKNOWN') || 0) + num(r.claims_amount)));
  const top = [...providerMap.entries()].sort((a,b)=>b[1]-a[1]).slice(0,10);
  charts.provider = new Chart(document.getElementById('providerChart'), {{type:'bar', data:{{labels:top.map(x=>x[0]), datasets:[{{label:'Claims Amount', data:top.map(x=>x[1])}}]}}, options:{{indexAxis:'y', responsive:true, maintainAspectRatio:false}}}});

  const claims = data.reduce((a,r)=>a+num(r.claims_amount),0);
  const expected = data.reduce((a,r)=>a+num(r.expected_check_amount),0);
  const actual = data.reduce((a,r)=>a+num(r.check_amount),0);
  charts.amount = new Chart(document.getElementById('amountChart'), {{type:'bar', data:{{labels:['Claims','Expected Check','Actual Check'], datasets:[{{label:'Amount', data:[claims,expected,actual]}}]}}, options:{{responsive:true, maintainAspectRatio:false}}}});
}}

function renderTabs() {{
  document.getElementById('tabs').innerHTML = TABLE_KEYS.map(key => `<button class="tab ${{key===activeTable?'active':''}}" onclick="setTable('${{key}}')">${{TABLE_LABELS[key]}} (${{fmt(DATA.row_counts[key] || rows(key).length)}})</button>`).join('');
}}
function setTable(key) {{ activeTable = key; renderTabs(); renderTable(); }}
function statusClass(c,v) {{
  if (c === 'payment_status') return v === 'PAID' ? 'status-paid' : 'status-unpaid';
  if (c === 'reconciliation_status') return v === 'MATCHED' ? 'status-matched' : 'status-variance';
  if (c === 'payee_match_status') return v === 'OK' ? 'status-ok' : v === 'For Review' ? 'status-review' : '';
  return '';
}}
function renderTable() {{
  const tableRows = filteredTableRows(activeTable);
  document.getElementById('tableNote').textContent = `Showing ${{tableRows.length.toLocaleString()}} preview rows. Full CSV: ${{FILE_NAMES[activeTable]}}`;
  const wrap = document.getElementById('tableWrap');
  if (!tableRows.length) {{ wrap.innerHTML = '<div style="padding:18px" class="note">No rows to display.</div>'; return; }}
  const cols = Object.keys(tableRows[0]);
  wrap.innerHTML = `<table><thead><tr>${{cols.map(c=>`<th>${{escapeHtml(c)}}</th>`).join('')}}</tr></thead><tbody>${{tableRows.map(r=>`<tr>${{cols.map(c=>`<td class="${{statusClass(c,r[c])}}">${{escapeHtml(r[c])}}</td>`).join('')}}</tr>`).join('')}}</tbody></table>`;
}}
function applyFilters() {{ renderMetrics(); renderCharts(); renderTabs(); renderTable(); }}
function resetFilters() {{ ['providerFilter','paymentFilter','categoryFilter','reconFilter','dateFilter'].forEach(id => document.getElementById(id).value='ALL'); document.getElementById('searchInput').value=''; applyFilters(); }}
function downloadActiveCsv() {{ alert(`Open this file from reports/latest: ${{FILE_NAMES[activeTable]}}`); }}

document.getElementById('searchInput').addEventListener('input', applyFilters);
['providerFilter','paymentFilter','categoryFilter','reconFilter','dateFilter'].forEach(id => document.getElementById(id).addEventListener('change', applyFilters));
populateFilters();
applyFilters();
</script>
</body>
</html>
"""


def generate_dashboard(reports_dir: str | Path = "reports/latest", preview_limit: int = 5000) -> Path:
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
    parser.add_argument("--preview-limit", type=int, default=5000, help="Maximum rows embedded per table")
    args = parser.parse_args()
    output_path = generate_dashboard(args.reports_dir, preview_limit=args.preview_limit)
    print(f"Dashboard generated: {output_path}")


if __name__ == "__main__":
    main()
