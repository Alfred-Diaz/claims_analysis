from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request

from claims_analysis.payment_db import DEFAULT_DB_PATH, connect, get_all_tags, init_db, upsert_tag

APP_TITLE = "Claims Payment Workflow"
AMOUNT_SQL = "CAST(COALESCE(NULLIF(expected_check_amount,''), NULLIF(claims_amount,''), '0') AS REAL)"
CATEGORY_SQL = """
CASE
 WHEN UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%PROFESSIONAL%'
   OR UPPER(COALESCE(supplier_category_name,'') || ' ' || COALESCE(provider,'')) LIKE '%PROF FEE%'
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
VALID_CATEGORIES = {"Hospital", "Medical Clinic", "Dental Clinic", "Professional"}


def _category(args) -> str:
    value = (args.get("category") or "Hospital").strip()
    return value if value in VALID_CATEGORIES else "Hospital"


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> Flask:
    app = Flask(__name__)
    init_db(db_path)

    @app.get("/")
    def index():
        return HTML

    @app.get("/api/metrics")
    def metrics():
        with connect(db_path) as conn:
            row = conn.execute(f"""
                SELECT
                  SUM(CASE WHEN UPPER(COALESCE(payment_status,'UNPAID'))='UNPAID' AND COALESCE(target_payment_date,'')='' THEN 1 ELSE 0 END) for_scheduling_count,
                  SUM(CASE WHEN UPPER(COALESCE(payment_status,'UNPAID'))='UNPAID' AND COALESCE(target_payment_date,'')<>'' THEN 1 ELSE 0 END) scheduled_count,
                  SUM(CASE WHEN UPPER(COALESCE(payment_status,'UNPAID'))='UNPAID' AND COALESCE(target_payment_date,'')='' THEN {AMOUNT_SQL} ELSE 0 END) for_scheduling_amount,
                  SUM(CASE WHEN UPPER(COALESCE(payment_status,'UNPAID'))='UNPAID' AND COALESCE(target_payment_date,'')<>'' THEN {AMOUNT_SQL} ELSE 0 END) scheduled_amount
                FROM payment_tags
            """).fetchone()
        return jsonify(dict(row))

    @app.get("/api/providers")
    def providers():
        q = (request.args.get("q") or "").strip()
        category = _category(request.args)
        status_filter = "COALESCE(target_payment_date,'')<>''" if request.args.get("mode") == "scheduled" else "COALESCE(target_payment_date,'')=''"
        params: list[object] = [category]
        provider_filter = ""
        if q:
            provider_filter = "AND provider LIKE ?"
            params.append(f"%{q}%")
        with connect(db_path) as conn:
            rows = conn.execute(f"""
                SELECT provider, COALESCE(NULLIF(region,''),'No Region') region, COALESCE(NULLIF(credit_term,''),'') credit_term,
                       ({CATEGORY_SQL}) category, COUNT(*) batch_count, SUM({AMOUNT_SQL}) amount,
                       MIN(target_payment_date) earliest_payment_date, MAX(target_payment_date) latest_payment_date
                FROM payment_tags
                WHERE UPPER(COALESCE(payment_status,'UNPAID'))='UNPAID'
                  AND {status_filter}
                  AND COALESCE(provider,'')<>''
                  AND ({CATEGORY_SQL})=?
                  {provider_filter}
                GROUP BY provider, region, credit_term, category
                ORDER BY amount DESC, batch_count DESC, provider
                LIMIT 400
            """, params).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.get("/api/provider-batches")
    def provider_batches():
        provider = (request.args.get("provider") or "").strip()
        if not provider:
            return jsonify({"error": "Provider is required"}), 400
        category = _category(request.args)
        scheduled = request.args.get("mode") == "scheduled"
        status_filter = "COALESCE(target_payment_date,'')<>''" if scheduled else "COALESCE(target_payment_date,'')=''"
        order = "target_payment_date ASC, date_received ASC" if scheduled else "date_received ASC"
        with connect(db_path) as conn:
            rows = conn.execute(f"""
                SELECT batch_no, provider, ({CATEGORY_SQL}) category, supplier_category_name, region,
                       date_received, aging_bucket, credit_term, {AMOUNT_SQL} amount,
                       target_payment_date, payment_priority, approval_status, payment_remarks,
                       cv_no, check_no, check_date
                FROM payment_tags
                WHERE provider=?
                  AND UPPER(COALESCE(payment_status,'UNPAID'))='UNPAID'
                  AND {status_filter}
                  AND ({CATEGORY_SQL})=?
                ORDER BY {order}, {AMOUNT_SQL} DESC
            """, (provider, category)).fetchall()
        return jsonify([dict(r) for r in rows])

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
        values = {
            "payment_status": "UNPAID",
            "tagged_for_payment": "YES",
            "target_payment_date": target_date,
            "payment_priority": payload.get("payment_priority", "NORMAL"),
            "approval_status": payload.get("approval_status", ""),
            "payment_remarks": payload.get("payment_remarks", ""),
            "tagged_date": datetime.now().strftime("%Y-%m-%d"),
        }
        for row in rows:
            upsert_tag(row["batch_no"], {**values, "provider": row["provider"]}, db_path=db_path, actor="restore_payment_schedule")
        return jsonify({"updated_rows": len(rows)})

    @app.post("/api/unschedule-selected")
    def unschedule_selected():
        payload = request.get_json(force=True, silent=True) or {}
        batch_numbers = [str(x).strip() for x in payload.get("batch_numbers", []) if str(x).strip()]
        if not batch_numbers:
            return jsonify({"error": "Select batches."}), 400
        placeholders = ",".join(["?"] * len(batch_numbers))
        with connect(db_path) as conn:
            rows = conn.execute(f"SELECT batch_no, provider FROM payment_tags WHERE batch_no IN ({placeholders})", batch_numbers).fetchall()
        for row in rows:
            upsert_tag(row["batch_no"], {"provider": row["provider"], "tagged_for_payment": "", "target_payment_date": "", "payment_priority": "", "approval_status": "", "payment_remarks": ""}, db_path=db_path, actor="restore_payment_unschedule")
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
body{margin:0;font-family:Arial;background:#f3f6fb;color:#172033}header{background:linear-gradient(135deg,#0f172a,#1e3a8a);color:white;padding:24px 28px}main{padding:16px;max-width:1600px;margin:auto}.card{background:white;border:1px solid #dbe3ef;border-radius:16px;padding:15px;margin-bottom:15px;box-shadow:0 3px 12px rgba(15,23,42,.08)}button{border:1px solid #dbe3ef;background:white;border-radius:10px;padding:9px 12px;font-weight:800;cursor:pointer}.active,.primary{background:#1d4ed8!important;color:white!important}.good{background:#047857;color:white}.danger{color:#b91c1c;border-color:#fecaca}.tabs,.chips,.actions{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}.metric{background:#f8fafc;border:1px solid #dbe3ef;border-radius:12px;padding:12px}.metric b{display:block;color:#64748b;font-size:11px;text-transform:uppercase}.metric span{font-size:22px;font-weight:900}.search{display:grid;grid-template-columns:1fr auto;gap:10px}input,select{padding:9px;border:1px solid #dbe3ef;border-radius:9px;width:100%}.split{display:grid;grid-template-columns:390px minmax(0,1fr);gap:14px}.list{max-height:620px;overflow:auto;border:1px solid #dbe3ef;border-radius:12px}.provider{display:block;width:100%;text-align:left;border:0;border-bottom:1px solid #dbe3ef;border-radius:0;background:white;padding:12px}.provider.active{border-left:5px solid #1d4ed8;background:#dbeafe;color:#172033}.muted{color:#64748b;font-size:12px}.wrap{overflow:auto;max-height:620px;border:1px solid #dbe3ef;border-radius:12px}.tbl{border-collapse:collapse;width:100%;min-width:1150px;font-size:12px}.tbl th,.tbl td{border-bottom:1px solid #dbe3ef;padding:8px;vertical-align:top}.tbl th{background:#f8fafc;position:sticky;top:0;text-align:left}.num{text-align:right}.pill{background:#eef2ff;color:#3730a3;border-radius:999px;padding:7px 10px;font-weight:900}.modal{display:none;position:fixed;inset:0;background:rgba(15,23,42,.55);align-items:center;justify-content:center;padding:18px}.modal.show{display:flex}.box{background:white;border-radius:16px;max-width:780px;width:100%;overflow:hidden}.box h3{margin:0;background:#0f172a;color:white;padding:16px}.box-body{padding:16px}.box-foot{text-align:right;padding:14px;border-top:1px solid #dbe3ef}.form{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}@media(max-width:900px){.split{grid-template-columns:1fr}.search{grid-template-columns:1fr}}
</style></head><body><header><h1>Claims Payment Workflow</h1><div>Provider drilldown, batch selection, For Scheduling and Scheduled workflow.</div></header><main>
<section class='grid' id='metrics'></section>
<section class='card'><div class='tabs'><button id='forBtn' onclick="setMode('for')">For Scheduling</button><button id='schedBtn' onclick="setMode('scheduled')">Scheduled</button></div><div class='chips' id='catChips'></div><div class='search'><input id='providerSearch' placeholder='Search provider...' oninput='debouncedLoadProviders()'><button class='primary' onclick='loadProviders()'>Refresh</button></div></section>
<section class='card'><div class='split'><div><div class='muted'>Providers</div><div id='providers' class='list'></div></div><div><div class='actions'><span id='selectedText' class='pill'>0 selected</span><button id='scheduleBtn' class='good' onclick='openSchedule()'>Schedule Checked Batches</button><button id='unscheduleBtn' class='danger' onclick='unscheduleChecked()'>Return Checked to For Scheduling</button><button onclick="location.href='/export/payments.csv'">Export CSV</button></div><div id='summary' class='muted'></div><div id='batches' class='wrap'></div></div></div></section>
</main><div class='modal' id='modal'><div class='box'><h3>Schedule Selected Batches</h3><div class='box-body'><div class='form'><div><label>Target Payment Date</label><input id='targetDate' type='date'></div><div><label>Priority</label><select id='priority'><option>NORMAL</option><option>HIGH</option><option>URGENT</option><option>LOW</option></select></div><div><label>Approval</label><select id='approval'><option></option><option>APPROVED</option><option>HOLD</option></select></div><div><label>Remarks</label><input id='remarks'></div></div></div><div class='box-foot'><button onclick='closeSchedule()'>Cancel</button><button class='good' onclick='scheduleChecked()'>Confirm Save</button></div></div></div>
<script>
let mode='for',category='Hospital',selectedProvider='',batchRows=[],timer=null;const CATS=['Hospital','Medical Clinic','Dental Clinic','Professional'];
function peso(v){return 'PHP '+Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}function esc(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}function checked(){return [...document.querySelectorAll('.chk:checked')].map(x=>x.value)}
function setMode(m){mode=m;selectedProvider='';batchRows=[];forBtn.classList.toggle('active',m==='for');schedBtn.classList.toggle('active',m==='scheduled');scheduleBtn.style.display=m==='for'?'inline-block':'none';unscheduleBtn.style.display=m==='scheduled'?'inline-block':'none';loadProviders();renderBatches();loadMetrics()}
function renderCats(){catChips.innerHTML=CATS.map(c=>`<button class='${c===category?'active':''}' onclick="category='${c}';selectedProvider='';loadProviders();renderBatches()">${c}</button>`).join('')}
async function loadMetrics(){let m=await(await fetch('/api/metrics')).json();metrics.innerHTML=[['For Scheduling',m.for_scheduling_count],['Scheduled',m.scheduled_count],['For Scheduling Amount',peso(m.for_scheduling_amount)],['Scheduled Amount',peso(m.scheduled_amount)]].map(x=>`<div class='metric'><b>${x[0]}</b><span>${x[1]||0}</span></div>`).join('')}
function debouncedLoadProviders(){clearTimeout(timer);timer=setTimeout(loadProviders,300)}
async function loadProviders(){let q=providerSearch.value||'';let res=await fetch(`/api/providers?mode=${mode==='scheduled'?'scheduled':'for'}&category=${encodeURIComponent(category)}&q=${encodeURIComponent(q)}`);let rows=await res.json();providers.innerHTML=rows.map(r=>`<button class='provider ${r.provider===selectedProvider?'active':''}' onclick="selectProvider('${String(r.provider).replaceAll('\\','\\\\').replaceAll("'","\\'")}')"><b>${esc(r.provider)}</b><br><span class='muted'>${esc(r.region)} | ${Number(r.batch_count||0).toLocaleString()} batches | ${peso(r.amount)}${mode==='scheduled'?'<br>Payment: '+esc(r.earliest_payment_date)+' to '+esc(r.latest_payment_date):''}</span></button>`).join('')||'<div class="muted" style="padding:12px">No providers found.</div>'}
async function selectProvider(p){selectedProvider=p;await loadProviders();let res=await fetch(`/api/provider-batches?mode=${mode==='scheduled'?'scheduled':'for'}&category=${encodeURIComponent(category)}&provider=${encodeURIComponent(p)}`);batchRows=await res.json();renderBatches()}
function renderBatches(){if(!batchRows.length){batches.innerHTML='<div class="muted" style="padding:14px">Select a provider to view batches.</div>';summary.textContent='';updateSelected();return}let total=batchRows.reduce((a,r)=>a+Number(r.amount||0),0);summary.textContent=`${selectedProvider} | ${batchRows.length.toLocaleString()} batches | ${peso(total)}`;let h='<thead><tr><th><input type="checkbox" onchange="document.querySelectorAll(\'.chk\').forEach(c=>c.checked=this.checked);updateSelected()"></th><th>Batch</th><th>Category</th><th>Region</th><th>Date Received</th><th>Aging</th><th>Credit</th><th class="num">Amount</th><th>Target Payment</th><th>Priority</th><th>CV</th><th>Check</th></tr></thead>';let body='<tbody>'+batchRows.map(r=>`<tr><td><input class='chk' value='${esc(r.batch_no)}' type='checkbox' onchange='updateSelected()'></td><td>${esc(r.batch_no)}</td><td>${esc(r.category)}</td><td>${esc(r.region)}</td><td>${esc(r.date_received)}</td><td>${esc(r.aging_bucket)}</td><td>${esc(r.credit_term)}</td><td class='num'>${peso(r.amount)}</td><td>${esc(r.target_payment_date)}</td><td>${esc(r.payment_priority)}</td><td>${esc(r.cv_no)}</td><td>${esc(r.check_no)}</td></tr>`).join('')+'</tbody>';batches.innerHTML='<table class="tbl">'+h+body+'</table>';updateSelected()}
function updateSelected(){let ids=checked();let amount=batchRows.filter(r=>ids.includes(String(r.batch_no))).reduce((a,r)=>a+Number(r.amount||0),0);selectedText.textContent=ids.length.toLocaleString()+' selected | '+peso(amount)}
function openSchedule(){if(!checked().length){alert('Select batches first.');return}modal.classList.add('show')}function closeSchedule(){modal.classList.remove('show')}
async function scheduleChecked(){if(!targetDate.value){alert('Target payment date is required.');return}let res=await fetch('/api/schedule-selected',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_numbers:checked(),target_payment_date:targetDate.value,payment_priority:priority.value,approval_status:approval.value,payment_remarks:remarks.value})});let out=await res.json();if(!res.ok){alert(out.error);return}closeSchedule();await selectProvider(selectedProvider);loadMetrics()}
async function unscheduleChecked(){let ids=checked();if(!ids.length){alert('Select scheduled batches first.');return}let res=await fetch('/api/unschedule-selected',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_numbers:ids})});let out=await res.json();if(!res.ok){alert(out.error);return}await selectProvider(selectedProvider);loadMetrics()}
renderCats();setMode('for');
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
