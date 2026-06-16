from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request

from claims_analysis.budget_db import ensure_month, month_key_from_date, pool_for_claim_sql
from claims_analysis.payment_db import DEFAULT_DB_PATH, connect, get_all_tags, init_db, upsert_tag

APP_TITLE = "Claims Payment Workflow"
AMOUNT_SQL = "CAST(COALESCE(NULLIF(expected_check_amount,''), NULLIF(claims_amount,''), '0') AS REAL)"
CATEGORY_SQL = """
CASE
 WHEN UPPER(COALESCE(supplier_category_name,'')||' '||COALESCE(provider,'')) LIKE '%PROF%'
   OR UPPER(COALESCE(provider,'')) LIKE 'DR %' THEN 'Professional'
 WHEN UPPER(COALESCE(supplier_category_name,'')||' '||COALESCE(provider,'')) LIKE '%DENTAL%'
   OR UPPER(COALESCE(supplier_category_name,'')||' '||COALESCE(provider,'')) LIKE '%DENTIST%' THEN 'Dental Clinic'
 WHEN UPPER(COALESCE(supplier_category_name,'')||' '||COALESCE(provider,'')) LIKE '%CLINIC%'
   OR UPPER(COALESCE(supplier_category_name,'')||' '||COALESCE(provider,'')) LIKE '%LABORATORY%'
   OR UPPER(COALESCE(supplier_category_name,'')||' '||COALESCE(provider,'')) LIKE '%DIAGNOSTIC%' THEN 'Medical Clinic'
 ELSE 'Hospital'
END
"""


def _where(args, scheduled: bool):
    clauses = ["UPPER(COALESCE(payment_status,''))='UNPAID'"]
    clauses.append("COALESCE(target_payment_date,'')<>''" if scheduled else "COALESCE(target_payment_date,'')=''" )
    params = []
    q = (args.get("q") or "").strip()
    if q:
        clauses.append("(provider LIKE ? OR batch_no LIKE ? OR region LIKE ? OR cv_no LIKE ? OR check_no LIKE ?)")
        params += [f"%{q}%"] * 5
    category = (args.get("category") or "All").strip()
    if category != "All":
        clauses.append(f"({CATEGORY_SQL})=?")
        params.append(category)
    for key, col in [("region", "region"), ("aging", "aging_bucket")]:
        val = (args.get(key) or "").strip()
        if val:
            clauses.append(f"COALESCE({col},'') LIKE ?")
            params.append(f"%{val}%")
    for key, col, op in [("date_from", "date_received", ">="), ("date_to", "date_received", "<="), ("target_from", "target_payment_date", ">="), ("target_to", "target_payment_date", "<=")]:
        val = (args.get(key) or "").strip()
        if val and (scheduled or not key.startswith("target")):
            clauses.append(f"{col} {op} ?")
            params.append(val)
    return " AND ".join(clauses), params


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> Flask:
    app = Flask(__name__)
    init_db(db_path)

    @app.get("/")
    def index():
        return HTML

    @app.get("/api/summary")
    def summary():
        scheduled = request.args.get("mode") == "scheduled"
        where, params = _where(request.args, scheduled)
        with connect(db_path) as conn:
            total = conn.execute(f"SELECT COUNT(*) count, SUM({AMOUNT_SQL}) amount FROM payment_tags WHERE {where}", params).fetchone()
            cat = conn.execute(f"SELECT ({CATEGORY_SQL}) label, SUM({AMOUNT_SQL}) amount FROM payment_tags WHERE {where} GROUP BY label ORDER BY amount DESC", params).fetchall()
            reg = conn.execute(f"SELECT COALESCE(NULLIF(region,''),'No Region') label, SUM({AMOUNT_SQL}) amount FROM payment_tags WHERE {where} GROUP BY label ORDER BY amount DESC LIMIT 10", params).fetchall()
            aging = conn.execute(f"SELECT COALESCE(NULLIF(aging_bucket,''),'No Aging') label, SUM({AMOUNT_SQL}) amount FROM payment_tags WHERE {where} GROUP BY label ORDER BY amount DESC", params).fetchall()
        return jsonify({"total": dict(total), "category": [dict(r) for r in cat], "region": [dict(r) for r in reg], "aging": [dict(r) for r in aging]})

    @app.get("/api/batches")
    def batches():
        scheduled = request.args.get("mode") == "scheduled"
        where, params = _where(request.args, scheduled)
        order = "target_payment_date, provider, date_received" if scheduled else "provider, date_received"
        with connect(db_path) as conn:
            rows = conn.execute(f"""
                SELECT batch_no, provider, ({CATEGORY_SQL}) category, region, date_received,
                       aging_bucket, credit_term, {AMOUNT_SQL} amount, target_payment_date,
                       payment_priority, approval_status, cv_no, check_no
                FROM payment_tags WHERE {where} ORDER BY {order} LIMIT 1500
            """, params).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.post("/api/budget-check")
    def budget_check():
        payload = request.get_json(force=True, silent=True) or {}
        batch_numbers = [str(x).strip() for x in payload.get("batch_numbers", []) if str(x).strip()]
        target_date = str(payload.get("target_payment_date") or "").strip()
        if not batch_numbers or not target_date:
            return jsonify({"error": "Select batches and target payment date."}), 400
        month = month_key_from_date(target_date)
        budget = ensure_month(month, db_path)
        placeholders = ",".join(["?"] * len(batch_numbers))
        with connect(db_path) as conn:
            rows = conn.execute(f"SELECT batch_no,{AMOUNT_SQL} amount,({pool_for_claim_sql()}) pool_code FROM payment_tags WHERE batch_no IN ({placeholders})", batch_numbers).fetchall()
        selected = {}
        for row in rows:
            selected[row["pool_code"]] = selected.get(row["pool_code"], 0.0) + float(row["amount"] or 0)
        checks = []
        for pool_code, amount in selected.items():
            pool = next((p for p in budget.get("pools", []) if p.get("pool_code") == pool_code), None)
            week = next((w for w in (pool or {}).get("weeks", []) if str(w.get("week_start")) <= target_date <= str(w.get("week_end"))), None)
            remaining = float((week or {}).get("remaining_budget") or 0)
            checks.append({"pool_code": pool_code, "pool_name": (pool or {}).get("pool_name", pool_code), "week_no": (week or {}).get("week_no", ""), "selected_amount": amount, "remaining_budget": remaining, "after_schedule_remaining": remaining - amount, "within_budget": amount <= remaining})
        return jsonify({"month": month, "target_payment_date": target_date, "checks": checks, "within_budget": all(c["within_budget"] for c in checks)})

    @app.post("/api/schedule-selected")
    def schedule_selected():
        payload = request.get_json(force=True, silent=True) or {}
        batch_numbers = [str(x).strip() for x in payload.get("batch_numbers", []) if str(x).strip()]
        target_date = str(payload.get("target_payment_date") or "").strip()
        if not batch_numbers or not target_date:
            return jsonify({"error": "Select batches and target payment date."}), 400
        placeholders = ",".join(["?"] * len(batch_numbers))
        with connect(db_path) as conn:
            rows = conn.execute(f"SELECT batch_no, provider FROM payment_tags WHERE batch_no IN ({placeholders})", batch_numbers).fetchall()
        values = {"tagged_for_payment": "YES", "target_payment_date": target_date, "payment_priority": payload.get("payment_priority", "NORMAL"), "approval_status": payload.get("approval_status", ""), "payment_remarks": payload.get("payment_remarks", ""), "tagged_date": datetime.now().strftime("%Y-%m-%d")}
        for row in rows:
            upsert_tag(row["batch_no"], {**values, "provider": row["provider"]}, db_path=db_path, actor="payment_budget_check")
        ensure_month(month_key_from_date(target_date), db_path)
        return jsonify({"updated_rows": len(rows)})

    @app.post("/api/unschedule-selected")
    def unschedule_selected():
        payload = request.get_json(force=True, silent=True) or {}
        batch_numbers = [str(x).strip() for x in payload.get("batch_numbers", []) if str(x).strip()]
        if not batch_numbers:
            return jsonify({"error": "Select batches."}), 400
        placeholders = ",".join(["?"] * len(batch_numbers))
        with connect(db_path) as conn:
            rows = conn.execute(f"SELECT batch_no, provider, target_payment_date FROM payment_tags WHERE batch_no IN ({placeholders})", batch_numbers).fetchall()
        months = {month_key_from_date(r["target_payment_date"]) for r in rows if r["target_payment_date"]}
        for row in rows:
            upsert_tag(row["batch_no"], {"provider": row["provider"], "tagged_for_payment": "", "target_payment_date": "", "payment_priority": "", "approval_status": "", "payment_remarks": ""}, db_path=db_path, actor="payment_budget_check")
        for month in months:
            ensure_month(month, db_path)
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
<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Claims Payment Workflow</title><style>
body{margin:0;font-family:Arial;background:#f3f6fb;color:#172033}header{background:#0f172a;color:white;padding:22px 28px}main{padding:16px;max-width:1700px;margin:auto}.card{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:14px;margin-bottom:14px}.tabs,.chips,.actions{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}button{border:1px solid #dbe3ef;border-radius:9px;background:white;padding:9px 12px;font-weight:800;cursor:pointer}.active,.primary{background:#1d4ed8!important;color:white!important}.good{background:#047857;color:white}.danger{color:#b91c1c}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.metric{background:#f8fafc;border:1px solid #dbe3ef;border-radius:12px;padding:12px}.filters{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px}label{display:block;font-size:12px;color:#64748b;font-weight:800}input,select{width:100%;padding:9px;border:1px solid #dbe3ef;border-radius:9px}.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px}.bar{margin:9px 0}.bar-label{display:flex;justify-content:space-between;font-size:12px;font-weight:800}.bar-track{height:14px;background:#e2e8f0;border-radius:999px;overflow:hidden}.bar-fill{height:100%;background:#1d4ed8}.wrap{overflow:auto;max-height:620px;border:1px solid #dbe3ef;border-radius:12px}.tbl{border-collapse:collapse;width:100%;min-width:1250px;font-size:12px}.tbl th,.tbl td{border-bottom:1px solid #dbe3ef;padding:8px;vertical-align:top}.tbl th{background:#f8fafc;position:sticky;top:0}.num{text-align:right}.pill{background:#eef2ff;color:#3730a3;border-radius:999px;padding:7px 10px;font-weight:900}.modal{display:none;position:fixed;inset:0;background:rgba(15,23,42,.55);align-items:center;justify-content:center;padding:18px}.modal.show{display:flex}.box{background:white;border-radius:16px;max-width:900px;width:100%;overflow:hidden}.box h3{background:#0f172a;color:white;margin:0;padding:16px}.box-body{padding:16px}.box-foot{padding:14px;text-align:right}.ok{background:#dcfce7;color:#166534;border:1px solid #86efac;border-radius:10px;padding:10px;margin-top:10px}.bad{background:#fee2e2;color:#991b1b;border:1px solid #fecaca;border-radius:10px;padding:10px;margin-top:10px}.toast{display:none;position:fixed;right:18px;bottom:18px;background:#0f172a;color:white;border-radius:14px;padding:12px}.toast.show{display:block}
</style></head><body><header><h1>Claims Payment Workflow</h1><div>Filters, graphs, and budget validation before scheduling.</div></header><main>
<section class='card'><div class='tabs'><button id='btnUnscheduled' onclick="setMode('unscheduled')">For Scheduling</button><button id='btnScheduled' onclick="setMode('scheduled')">Scheduled</button></div><div class='chips' id='catChips'></div><div class='filters'><div><label>Search</label><input id='q'></div><div><label>Region</label><input id='region'></div><div><label>Aging</label><input id='aging'></div><div><label>Date From</label><input id='date_from' type='date'></div><div><label>Date To</label><input id='date_to' type='date'></div><div id='targetFromBox'><label>Payment From</label><input id='target_from' type='date'></div><div id='targetToBox'><label>Payment To</label><input id='target_to' type='date'></div><button class='primary' onclick='loadAll()'>Apply Filters</button></div></section>
<section class='grid' id='metrics'></section><section class='charts' id='charts'></section>
<section class='card'><div class='actions'><span id='selectedText' class='pill'>0 selected</span><button class='good' onclick='openSchedule()' id='scheduleBtn'>Schedule Selected</button><button class='danger' onclick='unschedule()' id='unscheduleBtn'>Return Selected</button><button onclick="location.href='/export/payments.csv'">Export CSV</button></div><div class='wrap' id='tableWrap'></div></section></main>
<div class='modal' id='modal'><div class='box'><h3>Schedule Selected Batches</h3><div class='box-body'><div class='filters'><div><label>Target Payment Date</label><input id='targetPaymentDate' type='date' onchange='budgetCheck()'></div><div><label>Priority</label><select id='priority'><option>NORMAL</option><option>HIGH</option><option>URGENT</option><option>LOW</option></select></div><div><label>Approval</label><select id='approval'><option></option><option>APPROVED</option><option>HOLD</option></select></div><div><label>Remarks</label><input id='remarks'></div></div><div id='budgetBox'></div></div><div class='box-foot'><button onclick='closeSchedule()'>Cancel</button><button class='good' onclick='schedule()'>Confirm Schedule</button></div></div></div><div id='toast' class='toast'></div>
<script>
let mode='unscheduled',category='All',rows=[],lastBudget=null;const CATS=['All','Hospital','Medical Clinic','Dental Clinic','Professional'];
function peso(v){return 'PHP '+Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}function esc(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}function checked(){return [...document.querySelectorAll('.chk:checked')].map(x=>x.value)}function toastMsg(m){toast.textContent=m;toast.classList.add('show');setTimeout(()=>toast.classList.remove('show'),2500)}
function renderCats(){catChips.innerHTML=CATS.map(c=>`<button class='${c===category?'active':''}' onclick="category='${c}';renderCats();loadAll()">${c}</button>`).join('')}
function params(){let p=new URLSearchParams({mode,category});['q','region','aging','date_from','date_to','target_from','target_to'].forEach(id=>{let v=document.getElementById(id).value;if(v)p.set(id,v)});return p.toString()}
function setMode(m){mode=m;btnUnscheduled.classList.toggle('active',m==='unscheduled');btnScheduled.classList.toggle('active',m==='scheduled');targetFromBox.style.display=m==='scheduled'?'block':'none';targetToBox.style.display=m==='scheduled'?'block':'none';scheduleBtn.style.display=m==='unscheduled'?'inline-block':'none';unscheduleBtn.style.display=m==='scheduled'?'inline-block':'none';loadAll()}
async function loadAll(){let s=await(await fetch('/api/summary?'+params())).json();rows=await(await fetch('/api/batches?'+params())).json();renderSummary(s);renderCharts(s);renderTable();updateSelected()}
function renderSummary(s){metrics.innerHTML=[['Batches',s.total.count||0],['Amount',peso(s.total.amount||0)],['Category',category],['Mode',mode]].map(x=>`<div class='metric'><b>${x[0]}</b><h3>${x[1]}</h3></div>`).join('')}
function chartBlock(title,data){let max=Math.max(...data.map(x=>Number(x.amount||0)),1);return `<div class='card'><h3>${title}</h3>`+data.map(r=>`<div class='bar'><div class='bar-label'><span>${esc(r.label)}</span><span>${peso(r.amount||0)}</span></div><div class='bar-track'><div class='bar-fill' style='width:${Number(r.amount||0)/max*100}%'></div></div></div>`).join('')+'</div>'}
function renderCharts(s){charts.innerHTML=chartBlock('Amount by Category',s.category||[])+chartBlock('Amount by Region',s.region||[])+chartBlock('Amount by Aging',s.aging||[])}
function renderTable(){if(!rows.length){tableWrap.innerHTML='<div style="padding:14px;color:#64748b">No records found.</div>';return}let h='<thead><tr><th><input type="checkbox" onchange="document.querySelectorAll(\'.chk\').forEach(c=>c.checked=this.checked);updateSelected()"></th><th>Batch</th><th>Provider</th><th>Category</th><th>Region</th><th>Date</th><th>Aging</th><th>Credit</th><th class="num">Amount</th><th>Target</th><th>Priority</th><th>CV</th><th>Check</th></tr></thead>';let b='<tbody>'+rows.map(r=>`<tr><td><input class='chk' type='checkbox' onchange='updateSelected()' value='${esc(r.batch_no)}'></td><td>${esc(r.batch_no)}</td><td>${esc(r.provider)}</td><td>${esc(r.category)}</td><td>${esc(r.region)}</td><td>${esc(r.date_received)}</td><td>${esc(r.aging_bucket)}</td><td>${esc(r.credit_term)}</td><td class='num'>${peso(r.amount)}</td><td>${esc(r.target_payment_date)}</td><td>${esc(r.payment_priority)}</td><td>${esc(r.cv_no)}</td><td>${esc(r.check_no)}</td></tr>`).join('')+'</tbody>';tableWrap.innerHTML='<table class="tbl">'+h+b+'</table>'}
function updateSelected(){let ids=checked();let amt=rows.filter(r=>ids.includes(String(r.batch_no))).reduce((a,r)=>a+Number(r.amount||0),0);selectedText.textContent=ids.length.toLocaleString()+' selected | '+peso(amt);if(modal.classList.contains('show'))budgetCheck()}
function openSchedule(){if(!checked().length){alert('Select batches first.');return}budgetBox.innerHTML='Set target payment date to validate budget.';modal.classList.add('show')}function closeSchedule(){modal.classList.remove('show')}
async function budgetCheck(){lastBudget=null;let ids=checked();if(!ids.length||!targetPaymentDate.value){budgetBox.innerHTML='Set target payment date to validate budget.';return}let res=await fetch('/api/budget-check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_numbers:ids,target_payment_date:targetPaymentDate.value})});let out=await res.json();if(!res.ok){budgetBox.innerHTML='<div class="bad">'+esc(out.error||'Budget check failed')+'</div>';return}lastBudget=out;budgetBox.innerHTML=out.checks.map(c=>`<div class='${c.within_budget?'ok':'bad'}'><b>${esc(c.pool_name)} / Week ${esc(c.week_no)}</b><br>Selected: ${peso(c.selected_amount)} | Remaining: ${peso(c.remaining_budget)} | After: ${peso(c.after_schedule_remaining)}</div>`).join('')}
async function schedule(){let ids=checked();if(!targetPaymentDate.value){alert('Target payment date is required.');return}await budgetCheck();if(lastBudget&&!lastBudget.within_budget&&!confirm('Selected amount exceeds weekly budget. Continue?'))return;let res=await fetch('/api/schedule-selected',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_numbers:ids,target_payment_date:targetPaymentDate.value,payment_priority:priority.value,approval_status:approval.value,payment_remarks:remarks.value})});let out=await res.json();if(!res.ok){alert(out.error);return}closeSchedule();toastMsg('Scheduled '+out.updated_rows+' batches.');loadAll()}
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
