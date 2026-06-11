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
:root{--bg:#f3f6fb;--card:#fff;--text:#172033;--muted:#64748b;--border:#dbe3ef;--primary:#1d4ed8;--primary2:#2563eb;--good:#047857;--danger:#b91c1c;--warning:#b45309;--dark:#0f172a;--soft:#f8fafc;--shadow:0 10px 25px rgba(15,23,42,.08)}*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:linear-gradient(180deg,#eef4ff 0,#f8fafc 280px,#f3f6fb 100%);color:var(--text)}header{background:linear-gradient(135deg,#0f172a,#1e3a8a);color:white;padding:24px 30px 28px;border-bottom:1px solid rgba(255,255,255,.12)}header h1{margin:0;font-size:28px;letter-spacing:-.3px}header p{margin:8px 0 0;color:#dbeafe;font-size:13px}.header-row{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap}.badge{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.2);border-radius:999px;padding:8px 12px;font-size:12px;font-weight:800;color:#fff}main{padding:18px;max-width:1500px;margin:0 auto}.card{background:var(--card);border:1px solid var(--border);border-radius:18px;padding:16px;margin-bottom:16px;box-shadow:var(--shadow)}.card h3{margin:0 0 8px;font-size:18px}.section-title{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.form{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;align-items:end}.muted,label{color:var(--muted);font-size:12px}label{display:block;margin-bottom:5px;font-weight:700}input,select{width:100%;padding:10px 11px;border:1px solid var(--border);border-radius:11px;background:white;color:var(--text);outline:none}input:focus,select:focus{border-color:var(--primary);box-shadow:0 0 0 3px rgba(29,78,216,.12)}button{border:1px solid var(--border);background:white;padding:10px 13px;border-radius:11px;font-weight:800;cursor:pointer;transition:.15s}button:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(15,23,42,.12)}.primary{background:var(--primary);border-color:var(--primary);color:white}.good{background:var(--good);border-color:var(--good);color:white}.danger{color:var(--danger);border-color:#fecaca;background:#fff7f7}.metric-card{background:linear-gradient(180deg,#fff,#f8fafc);border:1px solid var(--border);border-radius:18px;padding:16px;box-shadow:0 4px 14px rgba(15,23,42,.05)}.metric-label{color:var(--muted);font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.04em}.metric{font-size:24px;font-weight:900;margin-top:7px;letter-spacing:-.4px}.metric-sub{color:var(--muted);font-size:12px;margin-top:5px}.week{border-left:6px solid var(--primary);position:relative;overflow:hidden}.week:after{content:"";position:absolute;top:0;right:0;width:80px;height:80px;background:rgba(37,99,235,.07);border-bottom-left-radius:80px}.over{border-left-color:var(--danger)}.ok{border-left-color:var(--good)}.warn{border-left-color:var(--warning)}.week-line{display:flex;justify-content:space-between;gap:10px;margin-top:8px;font-size:13px}.progress{height:9px;border-radius:999px;background:#e2e8f0;overflow:hidden;margin-top:12px}.progress span{display:block;height:100%;background:linear-gradient(90deg,var(--primary),#60a5fa);border-radius:999px}.progress.over span{background:linear-gradient(90deg,var(--danger),#f87171)}.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px}.tblwrap{overflow:auto;border:1px solid var(--border);border-radius:14px;background:white}.tbl{border-collapse:collapse;width:100%;min-width:920px;font-size:12px}.tbl th,.tbl td{border-bottom:1px solid var(--border);padding:10px;text-align:left;vertical-align:top}.tbl th{background:#f8fafc;color:#334155;font-size:11px;text-transform:uppercase;letter-spacing:.04em;position:sticky;top:0}.tbl tr:hover td{background:#f8fafc}.num{text-align:right}.status{display:inline-block;border-radius:999px;padding:4px 8px;font-weight:800;font-size:11px}.status.pending{background:#fef3c7;color:#92400e}.status.approved{background:#dcfce7;color:#166534}.status.rejected{background:#fee2e2;color:#991b1b}.toast{display:none;position:fixed;right:18px;bottom:18px;background:#0f172a;color:white;border-radius:14px;padding:12px 14px;box-shadow:0 14px 32px rgba(15,23,42,.25);z-index:20;font-weight:800}.toast.show{display:block}@media(max-width:900px){main{padding:12px}.two-col{grid-template-columns:1fr}.header-row{display:block}.badge{display:inline-block;margin-top:12px}.metric{font-size:20px}}
</style>
</head>
<body>
<header>
  <div class="header-row">
    <div>
      <h1>Claims Budget Management</h1>
      <p>Monthly budget control, fixed 4-week allocation, weekly reallocation, and Finance Manager approval workflow.</p>
    </div>
    <div class="badge">Default Budget: PHP 65,000,000</div>
  </div>
</header>
<main>
<section class="card">
  <div class="section-title"><h3>Budget Control Panel</h3><span class="muted">Claims amount is used as the budget consumption basis.</span></div>
  <div class="form">
    <div><label>Role</label><select id="role"><option>Finance Manager</option><option>Claims Manager</option></select></div>
    <div><label>Name</label><input id="userName" value="User"></div>
    <div><label>Budget Month</label><input id="budgetMonth" type="month"></div>
    <button class="primary" onclick="loadBudget()">Refresh Budget</button>
  </div>
</section>
<section id="summary" class="grid"></section>
<section class="card"><div class="section-title"><h3>Weekly Allocation</h3><span class="muted">Week 1: 1-7 | Week 2: 8-14 | Week 3: 15-21 | Week 4: 22-end</span></div><div id="weeks" class="grid"></div></section>
<div class="two-col">
  <section class="card"><h3>Additional Weekly Funds</h3><p class="muted">Adds funds to one week and deducts evenly from the other weeks. Monthly total stays unchanged.</p><div class="form"><div><label>Target Week</label><select id="weekNo"><option>1</option><option>2</option><option>3</option><option>4</option></select></div><div><label>Additional Amount</label><input id="weekAmount" type="number" placeholder="0.00"></div><div><label>Reason</label><input id="weekReason" placeholder="Reason for weekly reallocation"></div><button class="good" onclick="weeklyFunds()">Apply Reallocation</button></div></section>
  <section class="card"><h3>Monthly Additional Funds Request</h3><p class="muted">Creates a pending request. It will only apply after Finance Manager approval.</p><div class="form"><div><label>Requested Amount</label><input id="monthAmount" type="number" placeholder="0.00"></div><div><label>Reason</label><input id="monthReason" placeholder="Reason for monthly increase"></div><button class="good" onclick="monthlyRequest()">Submit Request</button></div></section>
</div>
<section class="card"><div class="section-title"><h3>Approval Queue</h3><span class="muted">Finance Manager approval required for monthly additional funds.</span></div><div id="requests" class="tblwrap"></div></section>
</main>
<div id="toast" class="toast"></div>
<script>
function peso(v){return 'PHP '+Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}
function pct(v){return Math.max(0,Math.min(100,Number(v||0))).toFixed(0)}
function esc(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}
function currentMonth(){return new Date().toISOString().slice(0,7)}
function showToast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2600)}
document.getElementById('budgetMonth').value=currentMonth()
async function loadBudget(){
  const m=document.getElementById('budgetMonth').value||currentMonth();
  const data=await (await fetch('/api/budget?month='+encodeURIComponent(m))).json();
  const month=data.month||{}; const weeks=data.weeks||[];
  const used=weeks.reduce((a,w)=>a+Number(w.used_budget||0),0);
  const remaining=weeks.reduce((a,w)=>a+Number(w.remaining_budget||0),0);
  const total=Number(month.total_monthly_budget||0); const util=total?used/total*100:0;
  document.getElementById('summary').innerHTML=[
    ['Base Monthly Budget', peso(month.base_monthly_budget), 'Default monthly fund allocation'],
    ['Approved Additional', peso(month.approved_additional_budget), 'Approved monthly increases'],
    ['Total Monthly Budget', peso(month.total_monthly_budget), 'Base plus approved additional'],
    ['Scheduled Used', peso(used), pct(util)+'% utilization'],
    ['Remaining', peso(remaining), 'Available after scheduled claims']
  ].map(([l,v,s])=>`<div class="metric-card"><div class="metric-label">${l}</div><div class="metric">${v}</div><div class="metric-sub">${s}</div></div>`).join('');
  document.getElementById('weeks').innerHTML=weeks.map(w=>{
    const allocated=Number(w.allocated_budget||0), used=Number(w.used_budget||0), rem=Number(w.remaining_budget||0);
    const u=allocated?used/allocated*100:0; const cls=rem<0?'over':u>85?'warn':'ok';
    return `<div class="metric-card week ${cls}"><div class="metric-label">Week ${w.week_no}</div><div class="metric-sub">${esc(w.week_start)} to ${esc(w.week_end)}</div><div class="week-line"><b>Allocated</b><span>${peso(allocated)}</span></div><div class="week-line"><b>Used</b><span>${peso(used)}</span></div><div class="week-line"><b>Remaining</b><span>${peso(rem)}</span></div><div class="progress ${rem<0?'over':''}"><span style="width:${pct(u)}%"></span></div><div class="metric-sub">${u.toFixed(2)}% utilized</div></div>`
  }).join('');
  renderRequests(data.requests||[]);
}
function statusClass(s){s=String(s||'').toLowerCase();return s.includes('approved')?'approved':s.includes('rejected')?'rejected':'pending'}
function renderRequests(rows){
  if(!rows.length){document.getElementById('requests').innerHTML='<div style="padding:16px" class="muted">No budget requests for this month.</div>';return}
  document.getElementById('requests').innerHTML=`<table class="tbl"><thead><tr><th>ID</th><th>Month</th><th class="num">Requested Add</th><th class="num">Requested Total</th><th>Status</th><th>Reason</th><th>Action</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.id}</td><td>${esc(r.budget_month)}</td><td class="num">${peso(r.requested_additional_amount)}</td><td class="num">${peso(r.requested_total_budget)}</td><td><span class="status ${statusClass(r.status)}">${esc(r.status)}</span></td><td>${esc(r.reason)}</td><td>${r.status==='PENDING'?`<button class="good" onclick="approveReq(${r.id})">Approve</button> <button class="danger" onclick="rejectReq(${r.id})">Reject</button>`:''}</td></tr>`).join('')}</tbody></table>`;
}
async function weeklyFunds(){
  const payload={budget_month:budgetMonth.value,week_no:weekNo.value,amount:weekAmount.value,reason:weekReason.value,created_by:userName.value};
  const res=await fetch('/api/budget/weekly',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await res.json(); if(!res.ok){alert(data.error);return} showToast('Weekly budget reallocated.'); loadBudget();
}
async function monthlyRequest(){
  const payload={budget_month:budgetMonth.value,amount:monthAmount.value,reason:monthReason.value,requested_by:userName.value};
  const res=await fetch('/api/budget/monthly-request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await res.json(); if(!res.ok){alert(data.error);return} showToast('Monthly request submitted.'); loadBudget();
}
async function approveReq(id){
  if(role.value!=='Finance Manager'){alert('Finance Manager only.');return}
  const res=await fetch(`/api/budget/monthly-request/${id}/approve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved_by:userName.value})});
  const data=await res.json(); if(!res.ok){alert(data.error);return} showToast('Request approved.'); loadBudget();
}
async function rejectReq(id){
  if(role.value!=='Finance Manager'){alert('Finance Manager only.');return}
  const res=await fetch(`/api/budget/monthly-request/${id}/reject`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved_by:userName.value})});
  const data=await res.json(); if(!res.ok){alert(data.error);return} showToast('Request rejected.'); loadBudget();
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
