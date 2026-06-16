from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request

from claims_analysis.payment_db import DEFAULT_DB_PATH, connect, get_all_tags, init_db, upsert_tag

APP_TITLE = "Claims Payment Workflow"

CATEGORY_SQL = """
CASE
 WHEN UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%PROFESSIONAL%'
   OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%PROF FEE%'
   OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%PHYSICIAN%'
   OR UPPER(COALESCE(provider,'')) LIKE 'DR %' THEN 'Professional'
 WHEN UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%DENTAL%'
   OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%DENTIST%' THEN 'Dental Clinic'
 WHEN UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%CLINIC%'
   OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%DIAGNOSTIC%'
   OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%LABORATORY%'
   OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%MEDICAL CENTER%' THEN 'Medical Clinic'
 ELSE 'Hospital'
END
"""
AMOUNT_SQL = "CAST(COALESCE(NULLIF(expected_check_amount,''), NULLIF(claims_amount,''), '0') AS REAL)"


def _where(args, scheduled: bool) -> tuple[str, list[object]]:
    clauses = ["UPPER(COALESCE(payment_status,'')) = 'UNPAID'"]
    clauses.append("COALESCE(target_payment_date,'') <> ''" if scheduled else "COALESCE(target_payment_date,'') = ''")
    params: list[object] = []
    q = (args.get("q") or "").strip()
    if q:
        clauses.append("(provider LIKE ? OR batch_no LIKE ? OR region LIKE ? OR credit_term LIKE ? OR cv_no LIKE ? OR check_no LIKE ?)")
        params.extend([f"%{q}%"] * 6)
    category = (args.get("category") or "All").strip()
    if category and category != "All":
        clauses.append(f"({CATEGORY_SQL}) = ?")
        params.append(category)
    for field, column in [("region", "region"), ("aging", "aging_bucket"), ("priority", "payment_priority"), ("approval", "approval_status")]:
        value = (args.get(field) or "").strip()
        if value:
            clauses.append(f"COALESCE({column},'') LIKE ?")
            params.append(f"%{value}%")
    date_from = (args.get("date_from") or "").strip()
    if date_from:
        clauses.append("date_received >= ?")
        params.append(date_from)
    date_to = (args.get("date_to") or "").strip()
    if date_to:
        clauses.append("date_received <= ?")
        params.append(date_to)
    target_from = (args.get("target_from") or "").strip()
    if scheduled and target_from:
        clauses.append("target_payment_date >= ?")
        params.append(target_from)
    target_to = (args.get("target_to") or "").strip()
    if scheduled and target_to:
        clauses.append("target_payment_date <= ?")
        params.append(target_to)
    amount_min = (args.get("amount_min") or "").strip()
    if amount_min:
        clauses.append(f"{AMOUNT_SQL} >= ?")
        params.append(float(amount_min))
    amount_max = (args.get("amount_max") or "").strip()
    if amount_max:
        clauses.append(f"{AMOUNT_SQL} <= ?")
        params.append(float(amount_max))
    return " AND ".join(clauses), params


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> Flask:
    app = Flask(__name__)
    init_db(db_path)

    @app.get("/")
    def index():
        return HTML

    @app.get("/api/summary")
    def api_summary():
        scheduled = request.args.get("mode") == "scheduled"
        where, params = _where(request.args, scheduled)
        with connect(db_path) as conn:
            total = conn.execute(f"SELECT COUNT(*) AS count, SUM({AMOUNT_SQL}) AS amount FROM payment_tags WHERE {where}", params).fetchone()
            by_category = conn.execute(f"SELECT ({CATEGORY_SQL}) AS label, COUNT(*) AS count, SUM({AMOUNT_SQL}) AS amount FROM payment_tags WHERE {where} GROUP BY label ORDER BY amount DESC", params).fetchall()
            by_region = conn.execute(f"SELECT COALESCE(NULLIF(region,''),'No Region') AS label, COUNT(*) AS count, SUM({AMOUNT_SQL}) AS amount FROM payment_tags WHERE {where} GROUP BY label ORDER BY amount DESC LIMIT 12", params).fetchall()
            by_aging = conn.execute(f"SELECT COALESCE(NULLIF(aging_bucket,''),'No Aging') AS label, COUNT(*) AS count, SUM({AMOUNT_SQL}) AS amount FROM payment_tags WHERE {where} GROUP BY label ORDER BY amount DESC", params).fetchall()
        return jsonify({"total": dict(total), "category": [dict(r) for r in by_category], "region": [dict(r) for r in by_region], "aging": [dict(r) for r in by_aging]})

    @app.get("/api/batches")
    def api_batches():
        scheduled = request.args.get("mode") == "scheduled"
        where, params = _where(request.args, scheduled)
        order = "target_payment_date ASC, provider ASC, date_received ASC" if scheduled else "provider ASC, date_received ASC"
        with connect(db_path) as conn:
            rows = conn.execute(f"""
                SELECT batch_no, provider, ({CATEGORY_SQL}) AS category, region, date_received,
                       aging_bucket, credit_term, {AMOUNT_SQL} AS amount,
                       target_payment_date, payment_priority, approval_status, payment_remarks,
                       cv_no, check_no, check_date
                FROM payment_tags
                WHERE {where}
                ORDER BY {order}
                LIMIT 1500
            """, params).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.post("/api/schedule-selected")
    def api_schedule_selected():
        payload = request.get_json(force=True, silent=True) or {}
        batch_numbers = [str(x).strip() for x in payload.get("batch_numbers", []) if str(x).strip()]
        target_date = str(payload.get("target_payment_date") or "").strip()
        if not batch_numbers or not target_date:
            return jsonify({"error": "Select batches and target payment date."}), 400
        placeholders = ",".join(["?"] * len(batch_numbers))
        with connect(db_path) as conn:
            rows = conn.execute(f"SELECT batch_no, provider FROM payment_tags WHERE batch_no IN ({placeholders})", batch_numbers).fetchall()
        values = {
            "tagged_for_payment": "YES",
            "target_payment_date": target_date,
            "payment_priority": payload.get("payment_priority", "NORMAL"),
            "approval_status": payload.get("approval_status", ""),
            "payment_remarks": payload.get("payment_remarks", ""),
            "tagged_date": datetime.now().strftime("%Y-%m-%d"),
        }
        for row in rows:
            upsert_tag(row["batch_no"], {**values, "provider": row["provider"]}, db_path=db_path, actor="payment_filters")
        return jsonify({"updated_rows": len(rows)})

    @app.post("/api/unschedule-selected")
    def api_unschedule_selected():
        payload = request.get_json(force=True, silent=True) or {}
        batch_numbers = [str(x).strip() for x in payload.get("batch_numbers", []) if str(x).strip()]
        if not batch_numbers:
            return jsonify({"error": "Select batches."}), 400
        placeholders = ",".join(["?"] * len(batch_numbers))
        with connect(db_path) as conn:
            rows = conn.execute(f"SELECT batch_no, provider FROM payment_tags WHERE batch_no IN ({placeholders})", batch_numbers).fetchall()
        for row in rows:
            upsert_tag(row["batch_no"], {"provider": row["provider"], "tagged_for_payment": "", "target_payment_date": "", "payment_priority": "", "approval_status": "", "payment_remarks": ""}, db_path=db_path, actor="payment_filters")
        return jsonify({"updated_rows": len(rows)})

    @app.get("/export/payments.csv")
    def export_payments():
        rows = get_all_tags(db_path)
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=payments_db_export.csv"})

    return app


HTML = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Claims Payment Workflow</title><style>
body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#f3f6fb;color:#172033}header{background:linear-gradient(135deg,#0f172a,#1e3a8a);color:white;padding:22px 28px}h1{margin:0 0 6px}main{padding:16px;max-width:1700px;margin:0 auto}.card{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:14px;margin-bottom:14px;box-shadow:0 2px 8px rgba(15,23,42,.08)}.tabs,.chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}button{border:1px solid #dbe3ef;border-radius:9px;background:white;padding:9px 12px;font-weight:800;cursor:pointer}.active,.primary{background:#1d4ed8!important;color:white!important}.good{background:#047857;color:white}.danger{color:#b91c1c;border-color:#fecaca}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.metric{background:#f8fafc;border:1px solid #dbe3ef;border-radius:12px;padding:12px}.metric b{display:block;font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:6px}.metric span{font-size:19px;font-weight:900}.filters{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;align-items:end}label{display:block;font-size:12px;color:#64748b;font-weight:800;margin-bottom:5px}input,select{width:100%;padding:9px;border:1px solid #dbe3ef;border-radius:9px}.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px}.bar{margin:9px 0}.bar-label{display:flex;justify-content:space-between;font-size:12px;font-weight:800}.bar-track{height:14px;background:#e2e8f0;border-radius:999px;overflow:hidden}.bar-fill{height:100%;background:linear-gradient(90deg,#1d4ed8,#60a5fa)}.wrap{overflow:auto;max-height:620px;border:1px solid #dbe3ef;border-radius:12px}.tbl{border-collapse:collapse;width:100%;min-width:1250px;font-size:12px}.tbl th,.tbl td{border-bottom:1px solid #dbe3ef;padding:8px;vertical-align:top;white-space:normal;overflow-wrap:anywhere}.tbl th{background:#f8fafc;position:sticky;top:0;z-index:1;text-align:left}.num{text-align:right}.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:end}.pill{display:inline-block;background:#eef2ff;color:#3730a3;border-radius:999px;padding:7px 10px;font-weight:900}.modal{display:none;position:fixed;inset:0;background:rgba(15,23,42,.55);align-items:center;justify-content:center;padding:18px}.modal.show{display:flex}.box{background:white;border-radius:16px;max-width:780px;width:100%;overflow:hidden}.box h3{background:#0f172a;color:white;margin:0;padding:16px}.box-body{padding:16px}.box-foot{padding:14px;border-top:1px solid #dbe3ef;text-align:right}.toast{display:none;position:fixed;right:18px;bottom:18px;background:#0f172a;color:white;border-radius:14px;padding:12px 14px;font-weight:800}.toast.show{display:block}
</style></head><body><header><h1>Claims Payment Workflow</h1><div>Filter unpaid batches, view amount graphs, and schedule selected batches.</div></header><main>
<section class="card"><div class="tabs"><button id="btnUnscheduled" class="active" onclick="setMode('unscheduled')">For Scheduling</button><button id="btnScheduled" onclick="setMode('scheduled')">Scheduled</button></div><div class="chips" id="catChips"></div><div class="filters"><div><label>Global Search</label><input id="q" placeholder="Provider, batch, CV, check, region"></div><div><label>Region</label><input id="region"></div><div><label>Aging</label><input id="aging" placeholder="Above 120, 61-90"></div><div><label>Date Received From</label><input id="date_from" type="date"></div><div><label>Date Received To</label><input id="date_to" type="date"></div><div><label>Amount Min</label><input id="amount_min" type="number"></div><div><label>Amount Max</label><input id="amount_max" type="number"></div><div id="targetFromBox"><label>Payment From</label><input id="target_from" type="date"></div><div id="targetToBox"><label>Payment To</label><input id="target_to" type="date"></div><button class="primary" onclick="loadAll()">Apply Filters</button></div></section>
<section class="grid" id="metrics"></section><section class="charts" id="charts"></section>
<section class="card"><div class="actions"><span id="selectedText" class="pill">0 selected</span><button class="good" onclick="openSchedule()" id="scheduleBtn">Schedule Selected</button><button class="danger" onclick="unschedule()" id="unscheduleBtn">Return Selected to For Scheduling</button><button onclick="location.href='/export/payments.csv'">Export DB CSV</button></div><br><div class="wrap" id="tableWrap"></div></section></main>
<div class="modal" id="modal"><div class="box"><h3>Schedule Selected Batches</h3><div class="box-body"><div class="filters"><div><label>Target Payment Date</label><input id="targetPaymentDate" type="date"></div><div><label>Priority</label><select id="priority"><option>NORMAL</option><option>HIGH</option><option>URGENT</option><option>LOW</option></select></div><div><label>Approval</label><select id="approval"><option></option><option>APPROVED</option><option>HOLD</option></select></div><div><label>Remarks</label><input id="remarks"></div></div></div><div class="box-foot"><button onclick="closeSchedule()">Cancel</button><button class="good" onclick="schedule()">Confirm Schedule</button></div></div></div><div id="toast" class="toast"></div>
<script>
let mode='unscheduled', category='All', rows=[]; const CATS=['All','Hospital','Medical Clinic','Dental Clinic','Professional'];
function peso(v){return 'PHP '+Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}function esc(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}function checked(){return [...document.querySelectorAll('.chk:checked')].map(x=>x.value)}function toastMsg(m){toast.textContent=m;toast.classList.add('show');setTimeout(()=>toast.classList.remove('show'),2500)}
function renderCats(){catChips.innerHTML=CATS.map(c=>'<button class="'+(c===category?'active':'')+'" onclick="category=\''+c+'\';renderCats();loadAll()">'+c+'</button>').join('')}
function params(){let p=new URLSearchParams({mode:mode,category:category});['q','region','aging','date_from','date_to','amount_min','amount_max','target_from','target_to'].forEach(id=>{let v=document.getElementById(id).value;if(v)p.set(id,v)});return p.toString()}
function setMode(m){mode=m;btnUnscheduled.classList.toggle('active',m==='unscheduled');btnScheduled.classList.toggle('active',m==='scheduled');targetFromBox.style.display=m==='scheduled'?'block':'none';targetToBox.style.display=m==='scheduled'?'block':'none';scheduleBtn.style.display=m==='unscheduled'?'inline-block':'none';unscheduleBtn.style.display=m==='scheduled'?'inline-block':'none';loadAll()}
async function loadAll(){let s=await (await fetch('/api/summary?'+params())).json();rows=await (await fetch('/api/batches?'+params())).json();renderSummary(s);renderCharts(s);renderTable();updateSelected()}
function renderSummary(s){metrics.innerHTML=[['Batches',s.total.count||0],['Amount',peso(s.total.amount||0)],['Category',category],['Mode',mode]].map(x=>'<div class="metric"><b>'+x[0]+'</b><span>'+x[1]+'</span></div>').join('')}
function chartBlock(title,data){let max=Math.max(...data.map(x=>Number(x.amount||0)),1);return '<div class="card"><h3>'+title+'</h3>'+data.map(r=>'<div class="bar"><div class="bar-label"><span>'+esc(r.label)+'</span><span>'+peso(r.amount||0)+'</span></div><div class="bar-track"><div class="bar-fill" style="width:'+(Number(r.amount||0)/max*100)+'%"></div></div></div>').join('')+'</div>'}
function renderCharts(s){charts.innerHTML=chartBlock('Amount by Category',s.category||[])+chartBlock('Amount by Region',s.region||[])+chartBlock('Amount by Aging',s.aging||[])}
function renderTable(){if(!rows.length){tableWrap.innerHTML='<div style="padding:14px;color:#64748b">No records found.</div>';return}let head='<thead><tr><th><input type="checkbox" onchange="document.querySelectorAll(\'.chk\').forEach(c=>c.checked=this.checked);updateSelected()"></th><th>Batch</th><th>Provider</th><th>Category</th><th>Region</th><th>Date Received</th><th>Aging</th><th>Credit</th><th class="num">Amount</th><th>Target Payment</th><th>Priority</th><th>CV</th><th>Check</th></tr></thead>';let body='<tbody>'+rows.map(r=>'<tr><td><input class="chk" type="checkbox" onchange="updateSelected()" value="'+esc(r.batch_no)+'"></td><td>'+esc(r.batch_no)+'</td><td>'+esc(r.provider)+'</td><td>'+esc(r.category)+'</td><td>'+esc(r.region)+'</td><td>'+esc(r.date_received)+'</td><td>'+esc(r.aging_bucket)+'</td><td>'+esc(r.credit_term)+'</td><td class="num">'+peso(r.amount)+'</td><td>'+esc(r.target_payment_date)+'</td><td>'+esc(r.payment_priority)+'</td><td>'+esc(r.cv_no)+'</td><td>'+esc(r.check_no)+'</td></tr>').join('')+'</tbody>';tableWrap.innerHTML='<table class="tbl">'+head+body+'</table>'}
function updateSelected(){let ids=checked();let amt=rows.filter(r=>ids.includes(String(r.batch_no))).reduce((a,r)=>a+Number(r.amount||0),0);selectedText.textContent=ids.length.toLocaleString()+' selected | '+peso(amt)}
function openSchedule(){if(!checked().length){alert('Select batches first.');return}modal.classList.add('show')}function closeSchedule(){modal.classList.remove('show')}
async function schedule(){let ids=checked();if(!targetPaymentDate.value){alert('Target payment date is required.');return}let res=await fetch('/api/schedule-selected',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_numbers:ids,target_payment_date:targetPaymentDate.value,payment_priority:priority.value,approval_status:approval.value,payment_remarks:remarks.value})});let out=await res.json();if(!res.ok){alert(out.error);return}closeSchedule();toastMsg('Scheduled '+out.updated_rows+' batches.');loadAll()}
async function unschedule(){let ids=checked();if(!ids.length){alert('Select scheduled batches first.');return}let res=await fetch('/api/unschedule-selected',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_numbers:ids})});let out=await res.json();if(!res.ok){alert(out.error);return}toastMsg('Returned '+out.updated_rows+' batches.');loadAll()}
['q','region','aging'].forEach(id=>document.getElementById(id).addEventListener('input',()=>{clearTimeout(window.t);window.t=setTimeout(loadAll,400)}));renderCats();setMode('unscheduled');
</script></body></html>
"""


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Run claims payment workflow app.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    args = parser.parse_args()
    app = create_app(args.db)
    print(f"{APP_TITLE} running at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
