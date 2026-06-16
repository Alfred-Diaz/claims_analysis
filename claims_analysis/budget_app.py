from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request

from claims_analysis.budget_db import (
    DEFAULT_DB_PATH,
    approve_monthly_budget_request,
    create_monthly_budget_request,
    ensure_month,
    month_key_from_date,
    reject_monthly_budget_request,
    request_weekly_additional_funds,
)

APP_TITLE = "Claims Budget Management"


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> Flask:
    app = Flask(__name__)
    ensure_month(month_key_from_date(), db_path)

    @app.get("/")
    def index():
        return HTML

    @app.get("/api/budget")
    def api_budget():
        budget_month = request.args.get("month") or month_key_from_date()
        return jsonify(ensure_month(budget_month, db_path))

    @app.post("/api/budget/weekly")
    def api_weekly():
        payload = request.get_json(force=True, silent=True) or {}
        try:
            data = request_weekly_additional_funds(
                payload.get("budget_month") or month_key_from_date(),
                int(payload.get("week_no") or 1),
                float(payload.get("amount") or 0),
                payload.get("reason", ""),
                payload.get("created_by", "Claims Manager"),
                db_path,
                payload.get("pool_code", "MEDICAL"),
            )
            return jsonify(data)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/budget/monthly-request")
    def api_monthly_request():
        payload = request.get_json(force=True, silent=True) or {}
        try:
            row = create_monthly_budget_request(
                payload.get("budget_month") or month_key_from_date(),
                float(payload.get("amount") or 0),
                payload.get("reason", ""),
                payload.get("requested_by", "Claims Manager"),
                db_path,
                payload.get("pool_code", "MEDICAL"),
            )
            return jsonify(row)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/budget/monthly-request/<int:request_id>/approve")
    def api_approve(request_id: int):
        payload = request.get_json(force=True, silent=True) or {}
        try:
            data = approve_monthly_budget_request(request_id, payload.get("approved_by", "Finance Manager"), payload.get("remarks", ""), db_path)
            return jsonify(data)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/budget/monthly-request/<int:request_id>/reject")
    def api_reject(request_id: int):
        payload = request.get_json(force=True, silent=True) or {}
        try:
            data = reject_monthly_budget_request(request_id, payload.get("approved_by", "Finance Manager"), payload.get("remarks", ""), db_path)
            return jsonify(data)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    return app


HTML = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Claims Budget Management</title>
<style>
body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#f3f6fb;color:#172033}header{background:#0f172a;color:white;padding:22px 28px}header h1{margin:0 0 6px}main{padding:16px;max-width:1500px;margin:0 auto}.card{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:14px;margin-bottom:14px;box-shadow:0 2px 8px rgba(15,23,42,.08)}.form{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;align-items:end}label,.muted{font-size:12px;color:#64748b}label{display:block;margin-bottom:5px;font-weight:700}input,select{width:100%;padding:9px;border:1px solid #dbe3ef;border-radius:9px}button{border:1px solid #dbe3ef;border-radius:9px;background:white;padding:10px 12px;font-weight:800;cursor:pointer}.primary{background:#1d4ed8;color:white}.good{background:#047857;color:white}.danger{color:#b91c1c;border-color:#fecaca}.board{display:grid;grid-template-columns:1.1fr 2.8fr 1.2fr;border:3px solid #111;background:white;margin-bottom:14px}.cell{border-right:3px solid #111;border-bottom:3px solid #111;text-align:center;font-weight:900;padding:12px;min-height:62px;display:flex;justify-content:center;align-items:center;flex-direction:column}.cell:last-child{border-right:0}.green{background:#e2f0d9}.peach{background:#f8cbad}.cream{background:#fce4d6}.blue{background:#ddebf7}.title{font-size:22px}.amount{font-size:20px;margin-top:8px}.main-grid{display:grid;grid-template-columns:repeat(4,1fr)}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}.tab.active{background:#1d4ed8;color:white}.pool-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin-bottom:12px}.metric{background:#f8fafc;border:1px solid #dbe3ef;border-radius:12px;padding:12px}.metric b{display:block;font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:6px}.metric span{font-size:18px;font-weight:900}.tblwrap{overflow:auto;border:1px solid #dbe3ef;border-radius:12px}.tbl{border-collapse:collapse;width:100%;min-width:850px;font-size:12px}.tbl th,.tbl td{border-bottom:1px solid #dbe3ef;padding:9px;text-align:left}.tbl th{background:#f8fafc}.num{text-align:right}.status{border-radius:999px;padding:4px 8px;font-weight:800}.PENDING{background:#fef3c7;color:#92400e}.APPROVED{background:#dcfce7;color:#166534}.REJECTED{background:#fee2e2;color:#991b1b}@media(max-width:900px){.board{grid-template-columns:1fr}.main-grid{grid-template-columns:1fr}.cell{border-right:0}}
</style></head><body>
<header><h1>Claims Budget Management</h1><div>Budget pools with weekly allocation: Medical, Reimbursement, Dental, and Pampanga.</div></header>
<main>
<section class="card"><div class="form"><div><label>Role</label><select id="role"><option>Finance Manager</option><option>Claims Manager</option></select></div><div><label>Name</label><input id="userName" value="User"></div><div><label>Budget Month</label><input id="budgetMonth" type="month"></div><button class="primary" onclick="loadBudget()">Refresh Budget</button></div></section>
<section id="board" class="board"></section>
<section class="card"><h3>Weekly Budgets by Pool</h3><div id="tabs" class="tabs"></div><div id="poolSummary" class="pool-summary"></div><div id="weeks" class="tblwrap"></div></section>
<section class="card"><h3>Weekly Reallocation</h3><div class="form"><div><label>Pool</label><select id="weekPool"></select></div><div><label>Target Week</label><select id="weekNo"><option>1</option><option>2</option><option>3</option><option>4</option></select></div><div><label>Additional Amount</label><input id="weekAmount" type="number"></div><div><label>Reason</label><input id="weekReason"></div><button class="good" onclick="weeklyFunds()">Apply Reallocation</button></div></section>
<section class="card"><h3>Monthly Additional Funds Request</h3><div class="form"><div><label>Pool</label><select id="monthPool"></select></div><div><label>Requested Amount</label><input id="monthAmount" type="number"></div><div><label>Reason</label><input id="monthReason"></div><button class="good" onclick="monthlyRequest()">Submit Request</button></div></section>
<section class="card"><h3>Approval Queue</h3><div id="requests" class="tblwrap"></div></section>
</main>
<script>
let data=null;let activePool='MEDICAL';const order=['MEDICAL','REIMBURSEMENT','DENTAL','PAMPANGA'];
function peso(v){return Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}
function esc(v){return String(v||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}
function currentMonth(){return new Date().toISOString().slice(0,7)}
budgetMonth.value=currentMonth();
function getPool(code){return (data.pools||[]).find(function(p){return p.pool_code===code})||{pool_code:code,pool_name:code,total_monthly_budget:0,used_budget:0,remaining_budget:0,weeks:[]}}
async function loadBudget(){data=await (await fetch('/api/budget?month='+encodeURIComponent(budgetMonth.value||currentMonth()))).json();renderAll()}
function renderAll(){renderBoard();renderSelects();renderTabs();renderPool();renderRequests(data.requests||[])}
function renderBoard(){let med=getPool('MEDICAL'), rei=getPool('REIMBURSEMENT'), den=getPool('DENTAL'), pam=getPool('PAMPANGA');let main=Number(med.total_monthly_budget||0)+Number(rei.total_monthly_budget||0)+Number(den.total_monthly_budget||0);let all=main+Number(pam.total_monthly_budget||0);board.innerHTML='<div class="cell green" style="grid-row:span 2"><div class="title">BUDGET (ALL)</div><div class="amount">'+peso(all)+'</div></div><div class="cell peach"><div class="title">BUDGET MAIN</div></div><div class="cell blue" style="grid-row:span 2"><div class="title">BUDGET PAMPANGA</div><div class="amount">'+peso(pam.total_monthly_budget)+'</div></div><div class="main-grid"><div class="cell cream">MEDICAL<div class="amount">'+peso(med.total_monthly_budget)+'</div></div><div class="cell cream">REIMBURSEMENT<div class="amount">'+peso(rei.total_monthly_budget)+'</div></div><div class="cell cream">DENTAL<div class="amount">'+peso(den.total_monthly_budget)+'</div></div><div class="cell cream">TOTAL MAIN<div class="amount">'+peso(main)+'</div></div></div>'}
function renderSelects(){let html=(data.pools||[]).map(function(p){return '<option value="'+p.pool_code+'">'+esc(p.pool_name)+'</option>'}).join('');weekPool.innerHTML=html;monthPool.innerHTML=html}
function renderTabs(){tabs.innerHTML=(data.pools||[]).sort(function(a,b){return order.indexOf(a.pool_code)-order.indexOf(b.pool_code)}).map(function(p){return '<button class="tab '+(p.pool_code===activePool?'active':'')+'" onclick="activePool=\''+p.pool_code+'\';renderTabs();renderPool()">'+esc(p.pool_name)+'</button>'}).join('')}
function renderPool(){let p=getPool(activePool);poolSummary.innerHTML='<div class="metric"><b>Monthly Budget</b><span>'+peso(p.total_monthly_budget)+'</span></div><div class="metric"><b>Used</b><span>'+peso(p.used_budget)+'</span></div><div class="metric"><b>Remaining</b><span>'+peso(p.remaining_budget)+'</span></div>';weeks.innerHTML='<table class="tbl"><thead><tr><th>Week</th><th>Period</th><th class="num">Allocated</th><th class="num">Used</th><th class="num">Remaining</th></tr></thead><tbody>'+(p.weeks||[]).map(function(w){return '<tr><td>Week '+w.week_no+'</td><td>'+esc(w.week_start)+' to '+esc(w.week_end)+'</td><td class="num">'+peso(w.allocated_budget)+'</td><td class="num">'+peso(w.used_budget)+'</td><td class="num">'+peso(w.remaining_budget)+'</td></tr>'}).join('')+'</tbody></table>'}
function renderRequests(rows){if(!rows.length){requests.innerHTML='<div style="padding:12px" class="muted">No budget requests.</div>';return}requests.innerHTML='<table class="tbl"><thead><tr><th>ID</th><th>Pool</th><th>Month</th><th class="num">Requested Add</th><th>Status</th><th>Reason</th><th>Action</th></tr></thead><tbody>'+rows.map(function(r){return '<tr><td>'+r.id+'</td><td>'+esc(r.pool_code||'MEDICAL')+'</td><td>'+esc(r.budget_month)+'</td><td class="num">'+peso(r.requested_additional_amount)+'</td><td><span class="status '+esc(r.status)+'">'+esc(r.status)+'</span></td><td>'+esc(r.reason)+'</td><td>'+(r.status==='PENDING'?'<button class="good" onclick="approveReq('+r.id+')">Approve</button> <button class="danger" onclick="rejectReq('+r.id+')">Reject</button>':'')+'</td></tr>'}).join('')+'</tbody></table>'}
async function weeklyFunds(){let payload={budget_month:budgetMonth.value,pool_code:weekPool.value,week_no:weekNo.value,amount:weekAmount.value,reason:weekReason.value,created_by:userName.value};let res=await fetch('/api/budget/weekly',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});let out=await res.json();if(!res.ok){alert(out.error);return}data=out;activePool=weekPool.value;renderAll()}
async function monthlyRequest(){let payload={budget_month:budgetMonth.value,pool_code:monthPool.value,amount:monthAmount.value,reason:monthReason.value,requested_by:userName.value};let res=await fetch('/api/budget/monthly-request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});let out=await res.json();if(!res.ok){alert(out.error);return}loadBudget()}
async function approveReq(id){if(role.value!=='Finance Manager'){alert('Finance Manager only.');return}let res=await fetch('/api/budget/monthly-request/'+id+'/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved_by:userName.value})});let out=await res.json();if(!res.ok){alert(out.error);return}data=out;renderAll()}
async function rejectReq(id){if(role.value!=='Finance Manager'){alert('Finance Manager only.');return}let res=await fetch('/api/budget/monthly-request/'+id+'/reject',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved_by:userName.value})});let out=await res.json();if(!res.ok){alert(out.error);return}data=out;renderAll()}
loadBudget();
</script></body></html>
"""


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Run Claims Budget Management app.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5051)
    args = parser.parse_args()
    app = create_app(args.db)
    print(f"{APP_TITLE} running at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
