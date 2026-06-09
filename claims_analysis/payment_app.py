from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request

from claims_analysis.payment_db import DEFAULT_DB_PATH, connect, get_all_tags, init_db, upsert_tag

APP_TITLE = "Claims Payment Workflow"


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> Flask:
    app = Flask(__name__)
    init_db(db_path)

    @app.get("/")
    def index():
        return DASHBOARD_HTML

    @app.get("/api/metrics")
    def api_metrics():
        with connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN UPPER(COALESCE(payment_status,'')) = 'UNPAID' AND COALESCE(target_payment_date,'') = '' THEN 1 ELSE 0 END) AS for_scheduling_count,
                    SUM(CASE WHEN UPPER(COALESCE(payment_status,'')) = 'UNPAID' AND COALESCE(target_payment_date,'') <> '' THEN 1 ELSE 0 END) AS scheduled_count,
                    SUM(CASE WHEN UPPER(COALESCE(payment_status,'')) = 'UNPAID' AND COALESCE(target_payment_date,'') = '' THEN CAST(COALESCE(NULLIF(expected_check_amount,''),'0') AS REAL) ELSE 0 END) AS for_scheduling_amount,
                    SUM(CASE WHEN UPPER(COALESCE(payment_status,'')) = 'UNPAID' AND COALESCE(target_payment_date,'') <> '' THEN CAST(COALESCE(NULLIF(expected_check_amount,''),'0') AS REAL) ELSE 0 END) AS scheduled_amount
                FROM payment_tags
                """
            ).fetchone()
        return jsonify(dict(row))

    @app.get("/api/providers")
    def api_providers():
        q = (request.args.get("q") or "").strip()
        provider_filter = ""
        params: list[str] = []
        if q:
            provider_filter = "AND provider LIKE ?"
            params.append(f"%{q}%")
        with connect(db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT provider, region, credit_term,
                       COUNT(*) AS batch_count,
                       SUM(CAST(COALESCE(NULLIF(expected_check_amount,''),'0') AS REAL)) AS amount
                FROM payment_tags
                WHERE UPPER(COALESCE(payment_status,'')) = 'UNPAID'
                  AND COALESCE(target_payment_date,'') = ''
                  AND COALESCE(provider, '') <> ''
                  {provider_filter}
                GROUP BY provider, region, credit_term
                ORDER BY amount DESC, batch_count DESC, provider ASC
                LIMIT 300
                """,
                params,
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.get("/api/provider-batches")
    def api_provider_batches():
        provider = (request.args.get("provider") or "").strip()
        if not provider:
            return jsonify({"error": "Provider is required"}), 400
        with connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT batch_no, provider, supplier_category_name, region, date_received, aging_bucket,
                       credit_term, expected_check_amount, claims_amount, payment_priority,
                       tagged_for_payment, target_payment_date, approval_status, payment_remarks,
                       cv_no, check_no, check_date
                FROM payment_tags
                WHERE provider = ?
                  AND UPPER(COALESCE(payment_status,'')) = 'UNPAID'
                  AND COALESCE(target_payment_date,'') = ''
                ORDER BY CASE
                            WHEN aging_bucket LIKE '%ABOVE 120%' THEN 1
                            WHEN aging_bucket LIKE '%91-120%' THEN 2
                            WHEN aging_bucket LIKE '%61-90%' THEN 3
                            WHEN aging_bucket LIKE '%31-60%' THEN 4
                            ELSE 5
                         END,
                         date_received ASC,
                         CAST(COALESCE(NULLIF(expected_check_amount,''),'0') AS REAL) DESC
                """,
                (provider,),
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.get("/api/scheduled-providers")
    def api_scheduled_providers():
        q = (request.args.get("q") or "").strip()
        provider_filter = ""
        params: list[str] = []
        if q:
            provider_filter = "AND provider LIKE ?"
            params.append(f"%{q}%")
        with connect(db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT provider, region, credit_term,
                       COUNT(*) AS batch_count,
                       SUM(CAST(COALESCE(NULLIF(expected_check_amount,''),'0') AS REAL)) AS amount,
                       MIN(target_payment_date) AS earliest_payment_date,
                       MAX(target_payment_date) AS latest_payment_date
                FROM payment_tags
                WHERE UPPER(COALESCE(payment_status,'')) = 'UNPAID'
                  AND COALESCE(target_payment_date,'') <> ''
                  AND COALESCE(provider, '') <> ''
                  {provider_filter}
                GROUP BY provider, region, credit_term
                ORDER BY earliest_payment_date ASC, amount DESC, provider ASC
                LIMIT 300
                """,
                params,
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.get("/api/scheduled-provider-batches")
    def api_scheduled_provider_batches():
        provider = (request.args.get("provider") or "").strip()
        if not provider:
            return jsonify({"error": "Provider is required"}), 400
        with connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT batch_no, provider, supplier_category_name, region, date_received, aging_bucket,
                       credit_term, expected_check_amount, claims_amount, payment_priority,
                       tagged_for_payment, target_payment_date, approval_status, payment_remarks,
                       tagged_date, cv_no, check_no, check_date
                FROM payment_tags
                WHERE provider = ?
                  AND UPPER(COALESCE(payment_status,'')) = 'UNPAID'
                  AND COALESCE(target_payment_date,'') <> ''
                ORDER BY target_payment_date ASC, batch_no ASC
                """,
                (provider,),
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.post("/api/schedule-selected")
    def api_schedule_selected():
        payload = request.get_json(force=True, silent=True) or {}
        batch_numbers = [str(x).strip() for x in payload.get("batch_numbers", []) if str(x).strip()]
        if not batch_numbers:
            return jsonify({"error": "No batches selected"}), 400
        target_payment_date = str(payload.get("target_payment_date", "") or "").strip()
        if not target_payment_date:
            return jsonify({"error": "Target payment date is required"}), 400

        update_values = {
            "tagged_for_payment": "YES",
            "target_payment_date": target_payment_date,
            "payment_priority": payload.get("payment_priority", "HIGH"),
            "approval_status": payload.get("approval_status", ""),
            "payment_remarks": payload.get("payment_remarks", ""),
            "tagged_date": datetime.now().strftime("%Y-%m-%d"),
        }
        placeholders = ",".join(["?"] * len(batch_numbers))
        with connect(db_path) as conn:
            rows = conn.execute(f"SELECT batch_no, provider FROM payment_tags WHERE batch_no IN ({placeholders})", batch_numbers).fetchall()
        for row in rows:
            upsert_tag(row["batch_no"], {**update_values, "provider": row["provider"]}, db_path=db_path, actor="selected_batch_schedule")
        return jsonify({"updated_rows": len(rows)})

    @app.post("/api/unschedule-selected")
    def api_unschedule_selected():
        payload = request.get_json(force=True, silent=True) or {}
        batch_numbers = [str(x).strip() for x in payload.get("batch_numbers", []) if str(x).strip()]
        if not batch_numbers:
            return jsonify({"error": "No batches selected"}), 400
        placeholders = ",".join(["?"] * len(batch_numbers))
        with connect(db_path) as conn:
            rows = conn.execute(f"SELECT batch_no, provider FROM payment_tags WHERE batch_no IN ({placeholders})", batch_numbers).fetchall()
        for row in rows:
            upsert_tag(
                row["batch_no"],
                {"provider": row["provider"], "tagged_for_payment": "", "target_payment_date": "", "payment_priority": "", "approval_status": "", "payment_remarks": ""},
                db_path=db_path,
                actor="unschedule_selected",
            )
        return jsonify({"updated_rows": len(rows)})

    @app.get("/export/payments.csv")
    def export_payments():
        rows = get_all_tags(db_path)
        output = io.StringIO()
        if rows:
            fieldnames = list(rows[0].keys())
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=payments_db_export.csv"})

    return app


DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Claims Payment Workflow</title>
<style>
:root{--bg:#f3f6fb;--card:#fff;--text:#172033;--muted:#64748b;--border:#dbe3ef;--primary:#1d4ed8;--good:#047857;--danger:#b91c1c}*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--text)}header{background:#0f172a;color:#fff;padding:20px 26px}header h1{margin:0 0 5px;font-size:24px}header p{margin:0;color:#cbd5e1;font-size:13px}main{padding:18px}.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:14px;box-shadow:0 1px 3px rgba(15,23,42,.08);margin-bottom:14px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.metric-label{color:var(--muted);font-size:12px;margin-bottom:7px}.metric-value{font-size:23px;font-weight:800}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}.tab{border:1px solid var(--border);background:white;border-radius:999px;padding:10px 14px;cursor:pointer;font-weight:800}.tab.active{background:var(--primary);border-color:var(--primary);color:white}.search-row{display:grid;grid-template-columns:minmax(240px,1fr) auto;gap:10px;align-items:end}.schedule-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:10px;align-items:end}label{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}input,select{width:100%;padding:8px 9px;border:1px solid var(--border);border-radius:8px;background:white;font-family:inherit;font-size:12px}button{border:1px solid var(--border);background:white;padding:9px 11px;border-radius:9px;cursor:pointer;font-weight:700;font-size:12px}button.primary{background:var(--primary);color:white;border-color:var(--primary)}button.good{background:var(--good);color:white;border-color:var(--good)}button.danger{color:var(--danger);border-color:#fecaca}.note{color:var(--muted);font-size:12px}.module{display:none}.module.active{display:block}.treasury-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-top:12px}.summary-card{background:#f8fafc;border:1px solid var(--border);border-radius:12px;padding:10px;min-height:74px}.summary-label{color:var(--muted);font-size:11px;margin-bottom:6px}.summary-value{font-size:18px;font-weight:800;overflow-wrap:anywhere}.split{display:grid;grid-template-columns:380px minmax(0,1fr);gap:12px;margin-top:12px}.provider-list{max-height:560px;overflow:auto;border:1px solid var(--border);border-radius:12px;background:#fff}.provider-item{width:100%;text-align:left;border:0;border-bottom:1px solid var(--border);border-radius:0;background:#fff;padding:10px;font-weight:400}.provider-item.active{background:#dbeafe}.table-wrap{overflow:auto;max-height:560px;border:1px solid var(--border);border-radius:12px;background:white}.data-table{border-collapse:collapse;width:100%;min-width:1050px;font-size:11px;table-layout:fixed}.data-table th,.data-table td{border-bottom:1px solid var(--border);padding:7px 8px;text-align:left;vertical-align:top;white-space:normal;overflow-wrap:anywhere;line-height:1.25}.data-table th{position:sticky;top:0;background:#f8fafc;z-index:1}.col-money{text-align:right}.action-row{display:flex;gap:10px;justify-content:space-between;align-items:center;margin-top:12px;flex-wrap:wrap}.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(15,23,42,.55);z-index:1000;align-items:center;justify-content:center;padding:18px}.modal-backdrop.active{display:flex}.modal{width:min(720px,100%);background:#fff;border-radius:16px;box-shadow:0 25px 60px rgba(15,23,42,.35);border:1px solid var(--border);overflow:hidden}.modal-header{padding:16px 18px;background:#0f172a;color:white}.modal-header h3{margin:0;font-size:18px}.modal-body{padding:18px}.modal-footer{padding:14px 18px;border-top:1px solid var(--border);display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap}.selected-pill{display:inline-block;background:#eef2ff;color:#3730a3;border-radius:999px;padding:5px 10px;font-weight:800}.help-box{background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:10px;margin-top:10px;color:#1e40af;font-size:12px}@media(max-width:1000px){.split{grid-template-columns:1fr}.search-row{grid-template-columns:1fr}}
</style>
</head>
<body>
<header><h1>Claims Payment Workflow</h1><p>For Scheduling and Scheduled use the same provider drilldown layout.</p></header>
<main>
<section class="grid" id="metrics"></section>
<div class="tabs"><button id="tabForScheduling" class="tab active" onclick="setModule('forScheduling')">For Scheduling</button><button id="tabScheduled" class="tab" onclick="setModule('scheduled')">Scheduled</button></div>
<section id="forSchedulingModule" class="module active card">
<h3>For Scheduling</h3>
<div class="search-row"><div><label>Search Provider</label><input id="providerSearch" placeholder="Type provider name..." /></div><div><button class="primary" onclick="loadProviders()">Refresh Providers</button></div></div>
<div id="selectionSummary" class="note" style="margin-top:10px">Select a provider to view unscheduled unpaid batches.</div><div id="treasurySummary" class="treasury-grid"></div>
<div class="split"><div><div class="note" style="margin-bottom:6px">Providers with unscheduled unpaid batches</div><div id="providerList" class="provider-list"></div></div><div><div class="note" style="margin-bottom:6px">Unscheduled unpaid batches under selected provider</div><div id="providerBatchWrap" class="table-wrap"></div></div></div>
<div class="action-row"><div><span id="selectedActionText" class="selected-pill">0 selected</span></div><div><button class="danger" onclick="clearSelection()">Clear Selection</button><button class="good" onclick="openScheduleModal()">Schedule Checked Batches</button><button onclick="window.location.href='/export/payments.csv'">Export DB CSV</button></div></div>
</section>
<section id="scheduledModule" class="module card">
<h3>Scheduled</h3>
<div class="search-row"><div><label>Search Scheduled Provider</label><input id="scheduledProviderSearch" placeholder="Type provider name..." /></div><div><button class="primary" onclick="loadScheduledProviders()">Refresh Scheduled Providers</button></div></div>
<div id="scheduledSummary" class="note" style="margin-top:10px">Select a scheduled provider to view scheduled batches.</div><div id="scheduledTreasurySummary" class="treasury-grid"></div>
<div class="split"><div><div class="note" style="margin-bottom:6px">Providers with scheduled batches</div><div id="scheduledProviderList" class="provider-list"></div></div><div><div class="note" style="margin-bottom:6px">Scheduled batches under selected provider</div><div id="scheduledBatchWrap" class="table-wrap"></div></div></div>
<div class="action-row"><div><span id="scheduledSelectedText" class="selected-pill">0 selected</span></div><div><button class="danger" onclick="unscheduleChecked()">Return Checked to For Scheduling</button><button onclick="window.location.href='/export/payments.csv'">Export DB CSV</button></div></div>
</section>
</main>
<div id="scheduleModal" class="modal-backdrop"><div class="modal"><div class="modal-header"><h3>Schedule Selected Batches</h3></div><div class="modal-body"><div id="modalSummary" class="note" style="margin-bottom:12px">0 batches selected.</div><div class="schedule-grid"><div><label>Target Payment Date <b style="color:#b91c1c">*</b></label><input id="targetPaymentDate" type="date" /></div><div><label>Priority</label><select id="paymentPriority"><option value="HIGH">HIGH</option><option value="URGENT">URGENT</option><option value="NORMAL">NORMAL</option><option value="LOW">LOW</option></select></div><div><label>Approval</label><select id="approvalStatus"><option value="">No Approval Yet</option><option value="APPROVED">APPROVED</option><option value="HOLD">HOLD</option></select></div><div><label>Remarks</label><input id="paymentRemarks" placeholder="Payment batch remarks" /></div></div><div class="help-box">Final save will move checked batches from For Scheduling to Scheduled.</div></div><div class="modal-footer"><button onclick="closeScheduleModal()">Cancel</button><button class="good" onclick="confirmScheduleCheckedBatches()">Confirm Save Schedule</button></div></div></div>
<script>
let selectedProvider='';let providerBatches=[];let scheduledProvider='';let scheduledBatches=[];let providerTimer=null;let scheduledProviderTimer=null;
function num(v){const n=Number(String(v??'').replaceAll(',',''));return Number.isNaN(n)?0:n}function money(v){return num(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}function escapeHtml(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;')}function upper(v){return String(v??'').trim().toUpperCase()}function checkedBatchNumbers(){return[...document.querySelectorAll('.batch-check:checked')].map(x=>x.value)}function checkedScheduledNumbers(){return[...document.querySelectorAll('.scheduled-check:checked')].map(x=>x.value)}function agingRank(v){const a=upper(v);if(a.includes('ABOVE 120'))return 5;if(a.includes('91-120')||a.includes('90-120'))return 4;if(a.includes('61-90')||a.includes('60-90'))return 3;if(a.includes('31-60')||a.includes('30-60'))return 2;if(a.includes('0-30'))return 1;return 0}
function setModule(moduleName){document.getElementById('forSchedulingModule').classList.toggle('active',moduleName==='forScheduling');document.getElementById('scheduledModule').classList.toggle('active',moduleName==='scheduled');document.getElementById('tabForScheduling').classList.toggle('active',moduleName==='forScheduling');document.getElementById('tabScheduled').classList.toggle('active',moduleName==='scheduled');if(moduleName==='scheduled')loadScheduledProviders();else loadProviders();loadMetrics()}
async function loadMetrics(){const res=await fetch('/api/metrics');const m=await res.json();const items=[['For Scheduling',Number(m.for_scheduling_count||0).toLocaleString()],['Scheduled',Number(m.scheduled_count||0).toLocaleString()],['For Scheduling Amount',money(m.for_scheduling_amount||0)],['Scheduled Amount',money(m.scheduled_amount||0)]];document.getElementById('metrics').innerHTML=items.map(([l,v])=>`<div class="card"><div class="metric-label">${l}</div><div class="metric-value">${v}</div></div>`).join('')}
async function loadProviders(){const q=document.getElementById('providerSearch').value||'';const res=await fetch('/api/providers?q='+encodeURIComponent(q));const rows=await res.json();document.getElementById('providerList').innerHTML=rows.map(r=>`<button class="provider-item ${r.provider===selectedProvider?'active':''}" onclick="selectProvider('${escapeHtml(r.provider)}')"><b>${escapeHtml(r.provider)}</b><br><span class="note">${escapeHtml(r.region||'')} | ${escapeHtml(r.credit_term||'')} | ${Number(r.batch_count||0).toLocaleString()} batches | ${money(r.amount||0)}</span></button>`).join('')||'<div style="padding:12px" class="note">No providers for scheduling.</div>'}
async function selectProvider(provider){selectedProvider=provider;await loadProviders();const res=await fetch('/api/provider-batches?provider='+encodeURIComponent(provider));providerBatches=await res.json();renderProviderBatches();clearScheduleInputs()}
function rowsStats(rows, selected){const set=new Set(selected);const totalAmount=rows.reduce((a,r)=>a+num(r.expected_check_amount),0);const selectedAmount=rows.filter(r=>set.has(String(r.batch_no))).reduce((a,r)=>a+num(r.expected_check_amount),0);const dates=rows.map(r=>String(r.date_received||'')).filter(Boolean).sort();const highest=rows.reduce((best,r)=>agingRank(r.aging_bucket)>agingRank(best)?r.aging_bucket:best,'');const credit=[...new Set(rows.map(r=>r.credit_term).filter(Boolean))].join(', ');return{totalBatches:rows.length,totalAmount,selectedCount:selected.length,selectedAmount,remainingCount:rows.length-selected.length,remainingAmount:totalAmount-selectedAmount,oldestDate:dates[0]||'',highestAging:highest||'',creditTerm:credit||''}}
function renderSummary(targetId, stats, label){const items=[[`${label} Amount`,money(stats.totalAmount)],[`${label} Batches`,stats.totalBatches.toLocaleString()],['Selected Amount',money(stats.selectedAmount)],['Selected Batches',stats.selectedCount.toLocaleString()],['Remaining After Selection',money(stats.remainingAmount)],['Remaining Batch Count',stats.remainingCount.toLocaleString()],['Oldest Received',stats.oldestDate||'-'],['Highest Aging',stats.highestAging||'-'],['Credit Term',stats.creditTerm||'-']];document.getElementById(targetId).innerHTML=items.map(([l,v])=>`<div class="summary-card"><div class="summary-label">${escapeHtml(l)}</div><div class="summary-value">${escapeHtml(v)}</div></div>`).join('')}
function updateSelectionSummary(){const s=rowsStats(providerBatches,checkedBatchNumbers());document.getElementById('selectionSummary').textContent=`Selected Provider: ${selectedProvider||'None'} | Selected Batches: ${s.selectedCount.toLocaleString()} | Selected Amount: ${money(s.selectedAmount)} | Remaining After Selection: ${money(s.remainingAmount)}`;document.getElementById('selectedActionText').textContent=`${s.selectedCount.toLocaleString()} selected | ${money(s.selectedAmount)}`;renderSummary('treasurySummary',s,'Unscheduled')}
function renderProviderBatches(){if(!providerBatches.length){document.getElementById('providerBatchWrap').innerHTML='<div style="padding:14px" class="note">No unscheduled unpaid batches found.</div>';updateSelectionSummary();return}const header=`<thead><tr><th style="width:42px"><input type="checkbox" onchange="toggleAllBatches(this.checked)" /></th><th>Batch No</th><th>Date Received</th><th>Aging</th><th>Credit Term</th><th>Expected Check</th><th>CV No</th><th>Check No</th></tr></thead>`;const body=`<tbody>${providerBatches.map(r=>`<tr><td><input class="batch-check" type="checkbox" value="${escapeHtml(r.batch_no)}" onchange="updateSelectionSummary()" /></td><td>${escapeHtml(r.batch_no)}</td><td>${escapeHtml(r.date_received)}</td><td>${escapeHtml(r.aging_bucket)}</td><td>${escapeHtml(r.credit_term)}</td><td class="col-money">${money(r.expected_check_amount)}</td><td>${escapeHtml(r.cv_no||'')}</td><td>${escapeHtml(r.check_no||'')}</td></tr>`).join('')}</tbody>`;document.getElementById('providerBatchWrap').innerHTML=`<table class="data-table">${header}${body}</table>`;updateSelectionSummary()}
function toggleAllBatches(checked){document.querySelectorAll('.batch-check').forEach(x=>x.checked=checked);updateSelectionSummary()}
function clearSelection(){document.querySelectorAll('.batch-check').forEach(x=>x.checked=false);updateSelectionSummary();clearScheduleInputs()}
function clearScheduleInputs(){document.getElementById('targetPaymentDate').value='';document.getElementById('paymentPriority').value='HIGH';document.getElementById('approvalStatus').value='';document.getElementById('paymentRemarks').value=''}
function openScheduleModal(){const s=rowsStats(providerBatches,checkedBatchNumbers());if(!s.selectedCount){alert('Select at least one batch first.');return}document.getElementById('modalSummary').textContent=`${s.selectedCount.toLocaleString()} checked batches | Selected Amount: ${money(s.selectedAmount)} | Provider: ${selectedProvider}`;document.getElementById('scheduleModal').classList.add('active');document.getElementById('targetPaymentDate').focus()}
function closeScheduleModal(){document.getElementById('scheduleModal').classList.remove('active')}
async function confirmScheduleCheckedBatches(){const batch_numbers=checkedBatchNumbers();if(!batch_numbers.length){alert('Select at least one batch.');closeScheduleModal();return}if(!document.getElementById('targetPaymentDate').value){alert('Set the target payment date first.');document.getElementById('targetPaymentDate').focus();return}if(!confirm(`Final save: move ${batch_numbers.length.toLocaleString()} checked batches to Scheduled?`))return;const payload={batch_numbers,target_payment_date:document.getElementById('targetPaymentDate').value,payment_priority:document.getElementById('paymentPriority').value,approval_status:document.getElementById('approvalStatus').value,payment_remarks:document.getElementById('paymentRemarks').value};const res=await fetch('/api/schedule-selected',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await res.json();if(data.error){alert(data.error);return}alert(`Moved ${Number(data.updated_rows||0).toLocaleString()} checked batches to Scheduled.`);closeScheduleModal();await selectProvider(selectedProvider);await loadScheduledProviders();await loadMetrics()}
async function loadScheduledProviders(){const q=document.getElementById('scheduledProviderSearch').value||'';const res=await fetch('/api/scheduled-providers?q='+encodeURIComponent(q));const rows=await res.json();document.getElementById('scheduledProviderList').innerHTML=rows.map(r=>`<button class="provider-item ${r.provider===scheduledProvider?'active':''}" onclick="selectScheduledProvider('${escapeHtml(r.provider)}')"><b>${escapeHtml(r.provider)}</b><br><span class="note">${escapeHtml(r.region||'')} | ${escapeHtml(r.credit_term||'')} | ${Number(r.batch_count||0).toLocaleString()} batches | ${money(r.amount||0)}<br>Payment: ${escapeHtml(r.earliest_payment_date||'')} to ${escapeHtml(r.latest_payment_date||'')}</span></button>`).join('')||'<div style="padding:12px" class="note">No scheduled providers.</div>'}
async function selectScheduledProvider(provider){scheduledProvider=provider;await loadScheduledProviders();const res=await fetch('/api/scheduled-provider-batches?provider='+encodeURIComponent(provider));scheduledBatches=await res.json();renderScheduledBatches()}
function updateScheduledSelection(){const s=rowsStats(scheduledBatches,checkedScheduledNumbers());document.getElementById('scheduledSummary').textContent=`Selected Provider: ${scheduledProvider||'None'} | Scheduled Batches: ${s.totalBatches.toLocaleString()} | Scheduled Amount: ${money(s.totalAmount)} | Selected: ${s.selectedCount.toLocaleString()} / ${money(s.selectedAmount)}`;document.getElementById('scheduledSelectedText').textContent=`${s.selectedCount.toLocaleString()} selected | ${money(s.selectedAmount)}`;renderSummary('scheduledTreasurySummary',s,'Scheduled')}
function renderScheduledBatches(){if(!scheduledBatches.length){document.getElementById('scheduledBatchWrap').innerHTML='<div style="padding:14px" class="note">No scheduled batches found.</div>';updateScheduledSelection();return}const header=`<thead><tr><th style="width:42px"><input type="checkbox" onchange="toggleAllScheduled(this.checked)" /></th><th>Target Payment</th><th>Batch No</th><th>Date Received</th><th>Aging</th><th>Expected Check</th><th>Priority</th><th>Approval</th><th>Remarks</th></tr></thead>`;const body=`<tbody>${scheduledBatches.map(r=>`<tr><td><input class="scheduled-check" type="checkbox" value="${escapeHtml(r.batch_no)}" onchange="updateScheduledSelection()" /></td><td>${escapeHtml(r.target_payment_date)}</td><td>${escapeHtml(r.batch_no)}</td><td>${escapeHtml(r.date_received)}</td><td>${escapeHtml(r.aging_bucket)}</td><td class="col-money">${money(r.expected_check_amount)}</td><td>${escapeHtml(r.payment_priority)}</td><td>${escapeHtml(r.approval_status)}</td><td>${escapeHtml(r.payment_remarks)}</td></tr>`).join('')}</tbody>`;document.getElementById('scheduledBatchWrap').innerHTML=`<table class="data-table">${header}${body}</table>`;updateScheduledSelection()}
function toggleAllScheduled(checked){document.querySelectorAll('.scheduled-check').forEach(x=>x.checked=checked);updateScheduledSelection()}
async function unscheduleChecked(){const batch_numbers=checkedScheduledNumbers();if(!batch_numbers.length){alert('Select at least one scheduled batch.');return}if(!confirm(`Return ${batch_numbers.length.toLocaleString()} selected batches to For Scheduling?`))return;const res=await fetch('/api/unschedule-selected',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_numbers})});const data=await res.json();if(data.error){alert(data.error);return}alert(`Returned ${Number(data.updated_rows||0).toLocaleString()} batches to For Scheduling.`);await selectScheduledProvider(scheduledProvider);await loadProviders();await loadMetrics()}
document.getElementById('providerSearch').addEventListener('input',()=>{clearTimeout(providerTimer);providerTimer=setTimeout(loadProviders,300)});document.getElementById('scheduledProviderSearch').addEventListener('input',()=>{clearTimeout(scheduledProviderTimer);scheduledProviderTimer=setTimeout(loadScheduledProviders,300)});document.getElementById('scheduleModal').addEventListener('click',e=>{if(e.target.id==='scheduleModal')closeScheduleModal()});loadMetrics();loadProviders();
</script>
</body></html>
"""


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Run local database-backed claims payment workflow app.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    args = parser.parse_args()
    app = create_app(args.db)
    print(f"{APP_TITLE} running at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
