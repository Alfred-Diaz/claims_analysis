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
            )
            return jsonify(row)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/budget/monthly-request/<int:request_id>/approve")
    def api_approve(request_id: int):
        payload = request.get_json(force=True, silent=True) or {}
        try:
            data = approve_monthly_budget_request(
                request_id,
                payload.get("approved_by", "Finance Manager"),
                payload.get("remarks", ""),
                db_path,
            )
            return jsonify(data)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/budget/monthly-request/<int:request_id>/reject")
    def api_reject(request_id: int):
        payload = request.get_json(force=True, silent=True) or {}
        try:
            data = reject_monthly_budget_request(
                request_id,
                payload.get("approved_by", "Finance Manager"),
                payload.get("remarks", ""),
                db_path,
            )
            return jsonify(data)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    return app


HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claims Budget Management</title>
<style>
body{margin:0;font-family:Arial;background:#f3f6fb;color:#172033}header{background:#0f172a;color:white;padding:18px 24px}main{padding:16px}.card{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:14px;margin-bottom:14px;box-shadow:0 1px 3px rgba(15,23,42,.08)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}.form{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;align-items:end}label,.muted{color:#64748b;font-size:12px}input,select{width:100%;padding:8px;border:1px solid #dbe3ef;border-radius:8px}button{border:1px solid #dbe3ef;background:white;padding:9px 11px;border-radius:9px;font-weight:700;cursor:pointer}.primary{background:#1d4ed8;color:white}.good{background:#047857;color:white}.danger{color:#b91c1c;border-color:#fecaca}.metric{font-size:22px;font-weight:800}.week{border-left:5px solid #1d4ed8}.over{border-left-color:#b91c1c}.tblwrap{overflow:auto;border:1px solid #dbe3ef;border-radius:12px;background:white}.tbl{border-collapse:collapse;width:100%;min-width:850px;font-size:12px}.tbl th,.tbl td{border-bottom:1px solid #dbe3ef;padding:8px;text-align:left}.tbl th{background:#f8fafc}.num{text-align:right}
</style>
</head>
<body>
<header><h2>Claims Budget Management</h2><div>Default Monthly Budget: PHP 65,000,000 | Calendar Week | Uses Claims Amount</div></header>
<main>
<section class="card">
  <div class="form">
    <div><label>Role</label><select id="role"><option>Finance Manager</option><option>Claims Manager</option></select></div>
    <div><label>Name</label><input id="userName" value="User"></div>
    <div><label>Budget Month</label><input id="budgetMonth" type="month"></div>
    <button class="primary" onclick="loadBudget()">Load Budget</button>
  </div>
</section>
<section id="summary" class="grid"></section>
<section class="card"><h3>Weekly Allocation</h3><div id="weeks" class="grid"></div></section>
<section class="card"><h3>Request Additional Weekly Funds</h3><p class="muted">This keeps the monthly total unchanged and deducts evenly from other weeks.</p><div class="form"><input id="weekNo" type="number" placeholder="Week no"><input id="weekAmount" type="number" placeholder="Additional amount"><input id="weekReason" placeholder="Reason"><button class="good" onclick="weeklyFunds()">Apply Weekly Reallocation</button></div></section>
<section class="card"><h3>Monthly Additional Funds Request</h3><p class="muted">This requires Finance Manager approval before applying to the month.</p><div class="form"><input id="monthAmount" type="number" placeholder="Additional monthly amount"><input id="monthReason" placeholder="Reason"><button class="good" onclick="monthlyRequest()">Submit Monthly Request</button></div></section>
<section class="card"><h3>Approval Queue</h3><div id="requests" class="tblwrap"></div></section>
</main>
<script>
function peso(v){return Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}
function esc(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}
function currentMonth(){return new Date().toISOString().slice(0,7)}
document.getElementById('budgetMonth').value=currentMonth()
async function loadBudget(){
  const m=document.getElementById('budgetMonth').value||currentMonth();
  const data=await (await fetch('/api/budget?month='+encodeURIComponent(m))).json();
  const month=data.month||{}; const weeks=data.weeks||[];
  const used=weeks.reduce((a,w)=>a+Number(w.used_budget||0),0);
  const remaining=weeks.reduce((a,w)=>a+Number(w.remaining_budget||0),0);
  document.getElementById('summary').innerHTML=[
    ['Base Monthly Budget', peso(month.base_monthly_budget)],
    ['Approved Additional', peso(month.approved_additional_budget)],
    ['Total Monthly Budget', peso(month.total_monthly_budget)],
    ['Scheduled Used', peso(used)],
    ['Remaining', peso(remaining)]
  ].map(([l,v])=>`<div class="card"><div class="muted">${l}</div><div class="metric">${v}</div></div>`).join('');
  document.getElementById('weeks').innerHTML=weeks.map(w=>`<div class="card week ${Number(w.remaining_budget)<0?'over':''}"><b>Week ${w.week_no}</b><br><span class="muted">${esc(w.week_start)} to ${esc(w.week_end)}</span><br>Allocated: ${peso(w.allocated_budget)}<br>Used: ${peso(w.used_budget)}<br>Remaining: ${peso(w.remaining_budget)}</div>`).join('');
  renderRequests(data.requests||[]);
}
function renderRequests(rows){
  document.getElementById('requests').innerHTML=`<table class="tbl"><thead><tr><th>ID</th><th>Month</th><th class="num">Requested Add</th><th class="num">Requested Total</th><th>Status</th><th>Reason</th><th>Action</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.id}</td><td>${esc(r.budget_month)}</td><td class="num">${peso(r.requested_additional_amount)}</td><td class="num">${peso(r.requested_total_budget)}</td><td>${esc(r.status)}</td><td>${esc(r.reason)}</td><td>${r.status==='PENDING'?`<button class="good" onclick="approveReq(${r.id})">Approve</button> <button class="danger" onclick="rejectReq(${r.id})">Reject</button>`:''}</td></tr>`).join('')}</tbody></table>`;
}
async function weeklyFunds(){
  const payload={budget_month:budgetMonth.value,week_no:weekNo.value,amount:weekAmount.value,reason:weekReason.value,created_by:userName.value};
  const res=await fetch('/api/budget/weekly',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await res.json(); if(!res.ok){alert(data.error);return} alert('Weekly budget reallocated.'); loadBudget();
}
async function monthlyRequest(){
  const payload={budget_month:budgetMonth.value,amount:monthAmount.value,reason:monthReason.value,requested_by:userName.value};
  const res=await fetch('/api/budget/monthly-request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await res.json(); if(!res.ok){alert(data.error);return} alert('Monthly request submitted.'); loadBudget();
}
async function approveReq(id){
  if(role.value!=='Finance Manager'){alert('Finance Manager only.');return}
  const res=await fetch(`/api/budget/monthly-request/${id}/approve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved_by:userName.value})});
  const data=await res.json(); if(!res.ok){alert(data.error);return} loadBudget();
}
async function rejectReq(id){
  if(role.value!=='Finance Manager'){alert('Finance Manager only.');return}
  const res=await fetch(`/api/budget/monthly-request/${id}/reject`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved_by:userName.value})});
  const data=await res.json(); if(!res.ok){alert(data.error);return} loadBudget();
}
loadBudget();
</script>
</body>
</html>
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
