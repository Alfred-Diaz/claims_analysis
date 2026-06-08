"""Generate a paginated local HTML dashboard from Claims Analysis report CSV files."""

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
    "aging_analysis": "aging_analysis.csv",
    "payment_batch": "payment_schedule_by_batch.csv",
    "payment_provider": "payment_schedule_by_provider.csv",
    "payment_workflow": "tagged_for_payment_workflow.csv",
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
    data = {"reports_dir": str(reports_dir), "summary": read_summary(reports_dir / REPORT_FILES["summary"]), "row_counts": {}, "tables": {}, "preview_limit": preview_limit}
    for key, filename in REPORT_FILES.items():
        path = reports_dir / filename
        data["row_counts"][key] = count_rows(path)
        data["tables"][key] = read_csv_preview(path, preview_limit)
    return data


def render_html(data: dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Claims Operations Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root{{--bg:#f3f6fb;--card:#fff;--text:#172033;--muted:#64748b;--border:#dbe3ef;--primary:#1d4ed8;--danger:#b91c1c;--good:#047857}}
*{{box-sizing:border-box}} body{{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--text)}} header{{background:#0f172a;color:#fff;padding:22px 28px}} header h1{{margin:0 0 6px;font-size:clamp(20px,2.2vw,30px)}} header p{{margin:0;color:#cbd5e1;font-size:13px}} main{{padding:22px}}
.menu{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}} .menu button{{border-radius:999px;padding:11px 16px}} .menu button.active{{background:var(--primary);color:#fff;border-color:var(--primary)}}
.layout{{display:grid;grid-template-columns:330px minmax(0,1fr);gap:18px;align-items:start}} .card{{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:16px;box-shadow:0 1px 3px rgba(15,23,42,.08);min-width:0}}
.filters{{position:sticky;top:14px;max-height:calc(100vh - 28px);overflow:auto}} label{{display:block;font-size:12px;color:var(--muted);margin:12px 0 5px}} select,input{{width:100%;padding:10px 11px;border:1px solid var(--border);border-radius:9px;background:#fff}}
.date-row,.filter-actions{{display:grid;grid-template-columns:1fr 1fr;gap:8px}} .filter-actions{{margin-top:14px}} button{{border:1px solid var(--border);background:#fff;padding:10px 12px;border-radius:9px;cursor:pointer;font-weight:700}} button.primary{{background:var(--primary);color:#fff;border-color:var(--primary)}} button:disabled{{opacity:.5;cursor:not-allowed}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-bottom:16px}} .metric-card{{min-height:105px;display:flex;flex-direction:column;justify-content:space-between;overflow:hidden}} .metric-label{{color:var(--muted);font-size:clamp(11px,1vw,13px);min-height:34px;line-height:1.25;overflow-wrap:anywhere}} .metric-value{{font-size:clamp(17px,1.8vw,26px);font-weight:800;line-height:1.15;overflow-wrap:anywhere;word-break:break-word}}
.charts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:14px;margin-bottom:16px}} .chart-box{{height:360px;overflow:hidden}} .chart-box canvas{{width:100%!important;height:300px!important}} .section-title{{margin:0 0 12px;font-size:16px}}
.tabs{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}} .tab{{border-radius:999px;padding:9px 13px}} .tab.active{{background:var(--primary);color:#fff;border-color:var(--primary)}} .toolbar{{display:grid;grid-template-columns:minmax(240px,1fr) auto;gap:10px;align-items:center;margin-bottom:10px}} .note{{color:var(--muted);font-size:12px}}
.pagination{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:10px 0}} .pagination select{{width:auto;min-width:90px;padding:8px}} .pagination span{{font-size:12px;color:var(--muted)}}
.table-wrap{{background:#fff;border:1px solid var(--border);border-radius:12px;overflow:auto;max-height:68vh}} table{{border-collapse:collapse;width:100%;font-size:12px}} th,td{{border-bottom:1px solid var(--border);padding:8px 9px;text-align:left;white-space:nowrap}} th{{background:#f8fafc;position:sticky;top:0;z-index:1}} tr:hover td{{background:#f9fafb}} .status-review,.status-unpaid,.status-tag{{color:var(--danger);font-weight:800}} .status-ok,.status-paid{{color:var(--good);font-weight:800}} footer{{padding:0 24px 24px;color:var(--muted);font-size:12px}}
@media(max-width:1050px){{.layout{{grid-template-columns:1fr}}.filters{{position:static;max-height:none}}.toolbar{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header><h1>Claims Operations Dashboard</h1><p id="reportPath"></p></header>
<main>
<div class="menu"><button id="reconMenu" class="active" onclick="setMode('reconciliation')">Reconciliation Dashboard</button><button id="calendarMenu" onclick="setMode('calendar')">Payment Calendar Dashboard</button></div>
<div class="layout">
<aside class="card filters">
<h2>Filters</h2>
<label>Documentation Type</label><select id="docTypeFilter"><option value="REGULAR">Regular Only</option><option value="ALL">All</option><option value="REIMBURSEMENT">Reimbursement Only</option></select>
<label>Supplier Category</label><select id="categoryFilter"></select>
<label>Region</label><select id="regionFilter"></select>
<label>Province</label><select id="provinceFilter"></select>
<label>City</label><select id="cityFilter"></select>
<label>Credit Term</label><select id="creditTermFilter"></select>
<label>Aging Bucket</label><select id="agingFilter"></select>
<label>MPSU Tag</label><select id="mpsuFilter"></select>
<label>Provider</label><select id="providerFilter"></select><input id="providerTextFilter" placeholder="Type provider name..." />
<label>Payment Status</label><select id="paymentFilter"><option value="ALL">All</option><option value="PAID">Paid</option><option value="UNPAID">Unpaid</option></select>
<label>Payment Schedule Status</label><select id="scheduleStatusFilter"><option value="ALL">All</option><option value="FOR PAYMENT TAGGING">For Payment Tagging</option><option value="PAID">Paid</option></select>
<label>Received / Schedule Date Range</label><div class="date-row"><input id="dateFromFilter" type="date" /><input id="dateToFilter" type="date" /></div>
<label>Global Search</label><input id="searchInput" placeholder="Batch, check no, CV no, provider, any value..." />
<div class="filter-actions"><button class="primary" onclick="applyFilters()">Apply</button><button onclick="resetFilters()">Reset</button></div>
</aside>
<section>
<section class="grid" id="metrics"></section>
<section class="charts"><div class="card chart-box"><div class="section-title" id="chart1Title">Paid vs Unpaid</div><canvas id="chart1"></canvas></div><div class="card chart-box"><div class="section-title" id="chart2Title">Top Providers</div><canvas id="chart2"></canvas></div><div class="card chart-box"><div class="section-title" id="chart3Title">Supplier Category</div><canvas id="chart3"></canvas></div></section>
<section class="card"><div class="tabs" id="tabs"></div><div class="toolbar"><span class="note" id="tableNote"></span><button onclick="downloadActiveCsv()">CSV file name</button></div><div class="pagination" id="paginationControls"></div><div class="table-wrap" id="tableWrap"></div></section>
</section>
</div></main>
<footer>Variance and duplicate check/CV exception tabs were removed. The active table, charts, and KPIs follow the current filters.</footer>
<script>
const DATA = {payload};
const RECON_TABLES = ['provider_reconciliation','results','paid','unpaid','date_summary','aging_analysis'];
const CALENDAR_TABLES = ['payment_provider','payment_batch','payment_workflow'];
const TABLE_LABELS = {{provider_reconciliation:'Provider Totals',results:'All Batches',paid:'Paid',unpaid:'Unpaid',date_summary:'Date Summary',aging_analysis:'Aging Analysis',payment_provider:'Payment by Provider',payment_batch:'Payment by Batch',payment_workflow:'For Payment Tagging'}};
const FILE_NAMES = {{provider_reconciliation:'provider_amount_reconciliation.csv',results:'claims_analysis_output.csv',paid:'paid_batches.csv',unpaid:'unpaid_batches.csv',date_summary:'date_created_summary.csv',aging_analysis:'aging_analysis.csv',payment_provider:'payment_schedule_by_provider.csv',payment_batch:'payment_schedule_by_batch.csv',payment_workflow:'tagged_for_payment_workflow.csv'}};
let mode='reconciliation'; let activeTable='provider_reconciliation'; let charts={{}}; let currentPage=1; let pageSize=100;
function num(v){{const n=Number(String(v??'').replaceAll(',',''));return Number.isNaN(n)?0:n}}
function money(v){{return num(v).toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}})}}
function rows(key){{return DATA.tables[key]||[]}} function mainRows(){{return rows('results')}} function scheduleRows(){{return rows('payment_batch')}}
function escapeHtml(v){{return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;')}}
function norm(v){{return String(v??'').trim().toLowerCase()}} function upper(v){{return String(v??'').trim().toUpperCase()}} function supplierCategory(r){{return upper(r.supplier_category_name||'')}} function docType(r){{return upper(r.claim_documentation_type||'REGULAR')||'REGULAR'}}
function rowDateValue(r){{return mode==='calendar' ? (r.scheduled_payment_date||r.date_received||'') : (r.date_received||r.received_date||r.check_date||'')}}
function parseDate(v){{const t=String(v??'').split(',')[0].trim();if(!t||t==='NO CHECK DATE'||t==='NO SCHEDULE DATE')return null;const d=new Date(t);return Number.isNaN(d.getTime())?null:d}}
function fillSelect(id, values, label){{const clean=[...new Set(values.map(v=>String(v??'').trim()).filter(Boolean))].sort();document.getElementById(id).innerHTML=`<option value="ALL">${{label}}</option>`+clean.map(v=>`<option value="${{escapeHtml(v)}}">${{escapeHtml(v)}}</option>`).join('')}}
function populateFilters(){{const all=[...mainRows(),...scheduleRows()];document.getElementById('reportPath').textContent=`Source: ${{DATA.reports_dir}}`;fillSelect('providerFilter',all.map(r=>r.provider||'UNKNOWN'),'All Providers');fillSelect('categoryFilter',all.map(r=>supplierCategory(r)),'All Supplier Categories');fillSelect('regionFilter',all.map(r=>r.region),'All Regions');fillSelect('provinceFilter',all.map(r=>r.province),'All Provinces');fillSelect('cityFilter',all.map(r=>r.city),'All Cities');fillSelect('creditTermFilter',all.map(r=>r.credit_term),'All Credit Terms');fillSelect('agingFilter',all.map(r=>r.aging_bucket),'All Aging Buckets');fillSelect('mpsuFilter',all.map(r=>r.mpsu_tag),'All MPSU Tags')}}
function filterValues(){{return {{docType:document.getElementById('docTypeFilter').value,provider:document.getElementById('providerFilter').value,providerText:norm(document.getElementById('providerTextFilter').value),payment:document.getElementById('paymentFilter').value,scheduleStatus:document.getElementById('scheduleStatusFilter').value,category:document.getElementById('categoryFilter').value,region:document.getElementById('regionFilter').value,province:document.getElementById('provinceFilter').value,city:document.getElementById('cityFilter').value,creditTerm:document.getElementById('creditTermFilter').value,aging:document.getElementById('agingFilter').value,mpsu:document.getElementById('mpsuFilter').value,dateFrom:document.getElementById('dateFromFilter').value?new Date(document.getElementById('dateFromFilter').value):null,dateTo:document.getElementById('dateToFilter').value?new Date(document.getElementById('dateToFilter').value):null,search:norm(document.getElementById('searchInput').value)}}}}
function passesCommonFilters(r){{const f=filterValues();const provider=r.provider||'UNKNOWN';const allText=Object.values(r).join(' ').toLowerCase();const d=parseDate(rowDateValue(r));let dateOk=true;if(f.dateFrom||f.dateTo){{dateOk=!!d;if(dateOk&&f.dateFrom&&d<f.dateFrom)dateOk=false;if(dateOk&&f.dateTo){{const end=new Date(f.dateTo);end.setHours(23,59,59,999);if(d>end)dateOk=false}}}}return(f.docType==='ALL'||docType(r)===f.docType)&&(f.provider==='ALL'||provider===f.provider)&&(norm(provider).includes(f.providerText))&&(f.payment==='ALL'||r.payment_status===f.payment)&&(f.scheduleStatus==='ALL'||r.payment_schedule_status===f.scheduleStatus)&&(f.category==='ALL'||supplierCategory(r)===upper(f.category))&&(f.region==='ALL'||String(r.region||'')===f.region)&&(f.province==='ALL'||String(r.province||'')===f.province)&&(f.city==='ALL'||String(r.city||'')===f.city)&&(f.creditTerm==='ALL'||String(r.credit_term||'')===f.creditTerm)&&(f.aging==='ALL'||String(r.aging_bucket||'')===f.aging)&&(f.mpsu==='ALL'||String(r.mpsu_tag||'')===f.mpsu)&&dateOk&&(!f.search||allText.includes(f.search))}}
function filteredRows(key){{let base=[];if(key==='provider_reconciliation')return groupProvider(filterRows(mainRows()));if(key==='date_summary')return groupDate(filterRows(mainRows()));if(key==='aging_analysis')return groupAging(filterRows(mainRows()));if(key==='payment_provider')return groupPaymentProvider(filterRows(scheduleRows()));if(key==='payment_workflow')base=rows('payment_workflow');else base=rows(key);return filterRows(base)}}
function filterRows(input){{return input.filter(passesCommonFilters)}}
function groupProvider(data){{const map=new Map();data.forEach(r=>{{const p=r.provider||'UNKNOWN';if(!map.has(p))map.set(p,{{provider:p,supplier_category_name:supplierCategory(r),region:r.region||'',credit_term:r.credit_term||'',batch_count:0,paid_batches:0,unpaid_batches:0,claims_amount:0,expected_check_amount:0,check_amount:0,difference:0}});const x=map.get(p);x.batch_count++;if(r.payment_status==='PAID')x.paid_batches++;if(r.payment_status==='UNPAID')x.unpaid_batches++;['claims_amount','expected_check_amount','check_amount','difference'].forEach(c=>x[c]+=num(r[c]))}});return [...map.values()].map(formatMoney).sort((a,b)=>num(b.claims_amount)-num(a.claims_amount))}}
function groupPaymentProvider(data){{const map=new Map();data.forEach(r=>{{const key=[r.payment_calendar_month||'',r.scheduled_payment_date||'',r.provider||'UNKNOWN'].join('|');if(!map.has(key))map.set(key,{{payment_calendar_month:r.payment_calendar_month||'',scheduled_payment_date:r.scheduled_payment_date||'',provider:r.provider||'UNKNOWN',supplier_category_name:supplierCategory(r),region:r.region||'',credit_term:r.credit_term||'',payment_schedule_status:r.payment_schedule_status||'',batch_count:0,claims_amount:0,expected_check_amount:0,check_amount:0,difference:0}});const x=map.get(key);x.batch_count++;['claims_amount','expected_check_amount','check_amount','difference'].forEach(c=>x[c]+=num(r[c]))}});return [...map.values()].map(formatMoney).sort((a,b)=>String(a.scheduled_payment_date).localeCompare(String(b.scheduled_payment_date)))}}
function groupDate(data){{const map=new Map();data.forEach(r=>{{const d=rowDateValue(r)||'NO DATE';if(!map.has(d))map.set(d,{{date_received:d,batch_count:0,paid_batches:0,unpaid_batches:0,claims_amount:0,check_amount:0,difference:0}});const x=map.get(d);x.batch_count++;if(r.payment_status==='PAID')x.paid_batches++;if(r.payment_status==='UNPAID')x.unpaid_batches++;['claims_amount','check_amount','difference'].forEach(c=>x[c]+=num(r[c]))}});return [...map.values()].map(formatMoney)}}
function groupAging(data){{const map=new Map();data.forEach(r=>{{const b=r.aging_bucket||'NO AGING BUCKET';if(!map.has(b))map.set(b,{{aging_bucket:b,batch_count:0,claims_amount:0,check_amount:0,difference:0}});const x=map.get(b);x.batch_count++;['claims_amount','check_amount','difference'].forEach(c=>x[c]+=num(r[c]))}});return [...map.values()].map(formatMoney)}}
function formatMoney(r){{['claims_amount','withholding_tax','expected_check_amount','check_amount','difference'].forEach(c=>{{if(c in r)r[c]=money(r[c])}});return r}}
function calcMetrics(){{const data=mode==='calendar'?filterRows(scheduleRows()):filterRows(mainRows());const sum=c=>data.reduce((a,r)=>a+num(r[c]),0);if(mode==='calendar')return [['Scheduled Batches',data.length.toLocaleString()],['For Payment Tagging',data.filter(r=>r.payment_schedule_status==='FOR PAYMENT TAGGING').length.toLocaleString()],['Paid',data.filter(r=>r.payment_schedule_status==='PAID').length.toLocaleString()],['Scheduled Amount',money(sum('expected_check_amount'))],['Actual Check',money(sum('check_amount'))],['Providers',[...new Set(data.map(r=>r.provider))].length.toLocaleString()]];return [['Total Batches',data.length.toLocaleString()],['Paid Batches',data.filter(r=>r.payment_status==='PAID').length.toLocaleString()],['Unpaid Batches',data.filter(r=>r.payment_status==='UNPAID').length.toLocaleString()],['Above 120 Days',data.filter(r=>r.aging_bucket==='ABOVE 120 DAYS').length.toLocaleString()],['Claims Amount',money(sum('claims_amount'))],['Expected Check',money(sum('expected_check_amount'))],['Actual Check',money(sum('check_amount'))],['Difference',money(sum('difference'))]]}}
function renderMetrics(){{document.getElementById('metrics').innerHTML=calcMetrics().map(([l,v])=>`<div class="card metric-card"><div class="metric-label">${{l}}</div><div class="metric-value">${{v}}</div></div>`).join('')}}
function destroyCharts(){{Object.values(charts).forEach(c=>c.destroy());charts={{}}}} function shortLabel(s){{return String(s||'').length>28?String(s).slice(0,25)+'...':s}}
function renderCharts(){{destroyCharts();const data=mode==='calendar'?filterRows(scheduleRows()):filterRows(mainRows());if(mode==='calendar'){{document.getElementById('chart1Title').textContent='Schedule Status';document.getElementById('chart2Title').textContent='Payment by Month';document.getElementById('chart3Title').textContent='Top Providers Due';chartCount('chart1',data,'payment_schedule_status');chartSum('chart2',data,'payment_calendar_month','expected_check_amount',false);chartSum('chart3',data,'provider','expected_check_amount',true);return}}document.getElementById('chart1Title').textContent='Paid vs Unpaid';document.getElementById('chart2Title').textContent='Top Providers by Claims Amount';document.getElementById('chart3Title').textContent='Claims by Supplier Category';chartCount('chart1',data,'payment_status');chartSum('chart2',data,'provider','claims_amount',true);chartSum('chart3',data,'supplier_category_name','claims_amount',false)}}
function chartCount(id,data,col){{const m=new Map();data.forEach(r=>m.set(r[col]||'UNKNOWN',(m.get(r[col]||'UNKNOWN')||0)+1));const x=[...m.entries()];charts[id]=new Chart(document.getElementById(id),{{type:'doughnut',data:{{labels:x.map(a=>a[0]),datasets:[{{data:x.map(a=>a[1])}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:'bottom'}}}}}}}})}}
function chartSum(id,data,labelCol,valueCol,horizontal){{const m=new Map();data.forEach(r=>m.set(r[labelCol]||'UNKNOWN',(m.get(r[labelCol]||'UNKNOWN')||0)+num(r[valueCol])));let x=[...m.entries()].sort((a,b)=>b[1]-a[1]).slice(0,10);charts[id]=new Chart(document.getElementById(id),{{type:'bar',data:{{labels:x.map(a=>shortLabel(a[0])),datasets:[{{data:x.map(a=>a[1])}}]}},options:{{indexAxis:horizontal?'y':'x',responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}}}}}})}}
function tableKeys(){{return mode==='calendar'?CALENDAR_TABLES:RECON_TABLES}} function renderTabs(){{document.getElementById('tabs').innerHTML=tableKeys().map(k=>`<button class="tab ${{k===activeTable?'active':''}}" onclick="setTable('${{k}}')">${{TABLE_LABELS[k]}} (${{filteredRows(k).length.toLocaleString()}})</button>`).join('')}}
function setMode(m){{mode=m;document.getElementById('reconMenu').classList.toggle('active',m==='reconciliation');document.getElementById('calendarMenu').classList.toggle('active',m==='calendar');activeTable=m==='calendar'?'payment_provider':'provider_reconciliation';currentPage=1;applyFilters()}} function setTable(k){{activeTable=k;currentPage=1;applyFilters()}}
function statusClass(c,v){{if(c==='payment_status')return v==='PAID'?'status-paid':'status-unpaid';if(c==='payment_schedule_status')return v==='PAID'?'status-paid':'status-tag';if(c==='payee_match_status')return v==='OK'?'status-ok':v==='For Review'?'status-review':'';return''}}
function renderPagination(total){{const totalPages=Math.max(1,Math.ceil(total/pageSize));if(currentPage>totalPages)currentPage=totalPages;const start=total?((currentPage-1)*pageSize+1):0;const end=Math.min(currentPage*pageSize,total);document.getElementById('paginationControls').innerHTML=`<button onclick="prevPage()" ${{currentPage<=1?'disabled':''}}>Previous</button><button onclick="nextPage()" ${{currentPage>=totalPages?'disabled':''}}>Next</button><span>Rows ${{start.toLocaleString()}}-${{end.toLocaleString()}} of ${{total.toLocaleString()}} | Page ${{currentPage.toLocaleString()}} of ${{totalPages.toLocaleString()}}</span><select onchange="changePageSize(this.value)"><option value="50" ${{pageSize==50?'selected':''}}>50</option><option value="100" ${{pageSize==100?'selected':''}}>100</option><option value="250" ${{pageSize==250?'selected':''}}>250</option><option value="500" ${{pageSize==500?'selected':''}}>500</option></select>`}}
function renderTable(){{const all=filteredRows(activeTable);renderPagination(all.length);const page=all.slice((currentPage-1)*pageSize,currentPage*pageSize);const loaded=rows(activeTable).length;const source=DATA.row_counts[activeTable]||loaded;document.getElementById('tableNote').textContent=`Filtered ${{all.length.toLocaleString()}} rows. Rendering ${{page.length.toLocaleString()}} rows. Loaded ${{loaded.toLocaleString()}} of ${{source.toLocaleString()}}. CSV: ${{FILE_NAMES[activeTable]}}`;const wrap=document.getElementById('tableWrap');if(!page.length){{wrap.innerHTML='<div style="padding:18px" class="note">No rows match the active filters.</div>';return}}const cols=Object.keys(page[0]);wrap.innerHTML=`<table><thead><tr>${{cols.map(c=>`<th>${{escapeHtml(c)}}</th>`).join('')}}</tr></thead><tbody>${{page.map(r=>`<tr>${{cols.map(c=>`<td class="${{statusClass(c,r[c])}}">${{escapeHtml(r[c])}}</td>`).join('')}}</tr>`).join('')}}</tbody></table>`}}
function nextPage(){{currentPage++;renderTable()}} function prevPage(){{currentPage--;renderTable()}} function changePageSize(v){{pageSize=Number(v);currentPage=1;renderTable()}}
function applyFilters(){{currentPage=1;renderMetrics();renderCharts();renderTabs();renderTable()}} function resetFilters(){{['docTypeFilter','providerFilter','paymentFilter','scheduleStatusFilter','categoryFilter','regionFilter','provinceFilter','cityFilter','creditTermFilter','agingFilter','mpsuFilter'].forEach(id=>document.getElementById(id).value=id==='docTypeFilter'?'REGULAR':'ALL');['providerTextFilter','dateFromFilter','dateToFilter','searchInput'].forEach(id=>document.getElementById(id).value='');applyFilters()}} function downloadActiveCsv(){{alert(`Open this file from reports/latest: ${{FILE_NAMES[activeTable]}}`)}}
['providerTextFilter','dateFromFilter','dateToFilter','searchInput'].forEach(id=>document.getElementById(id).addEventListener('input',applyFilters));['docTypeFilter','providerFilter','paymentFilter','scheduleStatusFilter','categoryFilter','regionFilter','provinceFilter','cityFilter','creditTermFilter','agingFilter','mpsuFilter'].forEach(id=>document.getElementById(id).addEventListener('change',applyFilters));populateFilters();applyFilters();
</script>
</body>
</html>"""


def generate_dashboard(reports_dir: str | Path = "reports/latest", preview_limit: int = DEFAULT_DASHBOARD_ROW_LIMIT) -> Path:
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    data = build_dashboard_data(reports_path, preview_limit=preview_limit)
    output_path = reports_path / "dashboard.html"
    output_path.write_text(render_html(data), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate local HTML dashboard from Claims Analysis reports.")
    parser.add_argument("--reports-dir", default="reports/latest")
    parser.add_argument("--preview-limit", type=int, default=DEFAULT_DASHBOARD_ROW_LIMIT)
    args = parser.parse_args()
    print(f"Dashboard generated: {generate_dashboard(args.reports_dir, args.preview_limit)}")


if __name__ == "__main__":
    main()
