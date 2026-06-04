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
    "for_review": "for_review.csv",
    "unmatched": "unmatched_batches.csv",
    "duplicate_checks": "duplicate_checks.csv",
    "duplicate_cv": "duplicate_cv.csv",
}


def read_csv_preview(path: Path, limit: int = 1000) -> list[dict[str, object]]:
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


def build_dashboard_data(reports_dir: Path, preview_limit: int = 1000) -> dict[str, object]:
    summary_path = reports_dir / REPORT_FILES["summary"]
    data = {
        "reports_dir": str(reports_dir),
        "summary": read_summary(summary_path),
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
  <title>Claims Analysis Dashboard</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --card: #ffffff;
      --text: #1f2937;
      --muted: #6b7280;
      --border: #e5e7eb;
      --primary: #1d4ed8;
      --danger: #b91c1c;
      --good: #047857;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      background: #0f172a;
      color: white;
      padding: 22px 28px;
    }}
    header h1 {{ margin: 0 0 6px 0; font-size: 24px; }}
    header p {{ margin: 0; color: #cbd5e1; }}
    main {{ padding: 24px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 14px;
      margin-bottom: 22px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
    }}
    .metric-label {{ color: var(--muted); font-size: 13px; margin-bottom: 8px; }}
    .metric-value {{ font-size: 26px; font-weight: 700; }}
    .tabs {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 18px 0; }}
    .tab {{
      border: 1px solid var(--border);
      background: white;
      padding: 10px 14px;
      border-radius: 999px;
      cursor: pointer;
      font-weight: 600;
    }}
    .tab.active {{ background: var(--primary); color: white; border-color: var(--primary); }}
    .toolbar {{
      display: flex;
      gap: 10px;
      align-items: center;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }}
    input {{
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      min-width: 280px;
    }}
    .note {{ color: var(--muted); font-size: 13px; }}
    .table-wrap {{
      background: white;
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow: auto;
      max-height: 70vh;
    }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 9px 10px;
      text-align: left;
      white-space: nowrap;
    }}
    th {{
      background: #f8fafc;
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    tr:hover td {{ background: #f9fafb; }}
    .status-review {{ color: var(--danger); font-weight: 700; }}
    .status-ok {{ color: var(--good); font-weight: 700; }}
    footer {{ padding: 0 24px 24px; color: var(--muted); font-size: 12px; }}
  </style>
</head>
<body>
  <header>
    <h1>Claims Analysis Dashboard</h1>
    <p id=\"reportPath\"></p>
  </header>
  <main>
    <section class=\"grid\" id=\"metrics\"></section>

    <section class=\"card\">
      <div class=\"toolbar\">
        <input id=\"searchInput\" placeholder=\"Search table: batch no, provider, check no, CV no...\" />
        <span class=\"note\" id=\"tableNote\"></span>
      </div>
      <div class=\"tabs\" id=\"tabs\"></div>
      <div class=\"table-wrap\" id=\"tableWrap\"></div>
    </section>
  </main>
  <footer>
    Static dashboard generated from Claims Analysis CSV reports. Large report files are previewed for browser performance.
  </footer>

<script>
const DATA = {payload};
const TABLE_LABELS = {{
  results: 'Results',
  for_review: 'For Review',
  unmatched: 'Unmatched Batches',
  duplicate_checks: 'Duplicate Checks',
  duplicate_cv: 'Duplicate CV',
  summary: 'Summary'
}};
const METRICS = [
  ['total_batches', 'Total Batches'],
  ['total_amount', 'Total Amount'],
  ['hospital_count', 'Hospital'],
  ['professional_count', 'Professional'],
  ['for_review_payees', 'For Review'],
  ['unmatched_batches', 'Unmatched'],
  ['duplicate_check_numbers', 'Duplicate Checks'],
  ['duplicate_cv_numbers', 'Duplicate CV']
];
let activeTable = 'results';
let searchText = '';

function fmt(value) {{
  if (value === undefined || value === null || value === '') return '0';
  const n = Number(value);
  if (!Number.isNaN(n) && String(value).match(/^[-0-9.]+$/)) return n.toLocaleString();
  return value;
}}

function renderMetrics() {{
  document.getElementById('reportPath').textContent = `Source: ${{DATA.reports_dir}}`;
  const box = document.getElementById('metrics');
  box.innerHTML = METRICS.map(([key, label]) => `
    <div class=\"card\">
      <div class=\"metric-label\">${{label}}</div>
      <div class=\"metric-value\">${{fmt(DATA.summary[key])}}</div>
    </div>
  `).join('');
}}

function renderTabs() {{
  const tabs = document.getElementById('tabs');
  const keys = ['results', 'for_review', 'unmatched', 'duplicate_checks', 'duplicate_cv', 'summary'];
  tabs.innerHTML = keys.map(key => `
    <button class=\"tab ${{key === activeTable ? 'active' : ''}}\" onclick=\"setTable('${{key}}')\">
      ${{TABLE_LABELS[key]}} (${{fmt(DATA.row_counts[key])}})
    </button>
  `).join('');
}}

function setTable(key) {{
  activeTable = key;
  renderTabs();
  renderTable();
}}

function rowMatches(row) {{
  if (!searchText) return true;
  return Object.values(row).join(' ').toLowerCase().includes(searchText);
}}

function escapeHtml(value) {{
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}}

function renderTable() {{
  const rows = (DATA.tables[activeTable] || []).filter(rowMatches);
  const totalRows = DATA.row_counts[activeTable] || 0;
  const note = document.getElementById('tableNote');
  note.textContent = `Showing ${{rows.length.toLocaleString()}} preview rows. Full CSV rows: ${{totalRows.toLocaleString()}}.`;

  const wrap = document.getElementById('tableWrap');
  if (!rows.length) {{
    wrap.innerHTML = '<div style=\"padding:18px\" class=\"note\">No rows to display.</div>';
    return;
  }}
  const columns = Object.keys(rows[0]);
  const thead = `<thead><tr>${{columns.map(c => `<th>${{escapeHtml(c)}}</th>`).join('')}}</tr></thead>`;
  const tbody = `<tbody>${{rows.map(row => `<tr>${{columns.map(c => {{
    const v = escapeHtml(row[c]);
    const cls = c === 'payee_match_status' && v === 'For Review' ? 'status-review' : c === 'payee_match_status' && v === 'OK' ? 'status-ok' : '';
    return `<td class=\"${{cls}}\">${{v}}</td>`;
  }}).join('')}}</tr>`).join('')}}</tbody>`;
  wrap.innerHTML = `<table>${{thead}}${{tbody}}</table>`;
}}

document.getElementById('searchInput').addEventListener('input', event => {{
  searchText = event.target.value.trim().toLowerCase();
  renderTable();
}});

renderMetrics();
renderTabs();
renderTable();
</script>
</body>
</html>
"""


def generate_dashboard(reports_dir: str | Path = "reports/latest", preview_limit: int = 1000) -> Path:
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
    parser.add_argument("--preview-limit", type=int, default=1000, help="Maximum rows embedded per table")
    args = parser.parse_args()

    output_path = generate_dashboard(args.reports_dir, preview_limit=args.preview_limit)
    print(f"Dashboard generated: {output_path}")


if __name__ == "__main__":
    main()
