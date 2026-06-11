from __future__ import annotations

from pathlib import Path

from flask import Flask, Response, send_file

APP_TITLE = "Claims Analysis Portal"
DEFAULT_DASHBOARD = "reports/latest/dashboard.html"


def create_app(dashboard_path: str | Path = DEFAULT_DASHBOARD) -> Flask:
    app = Flask(__name__)
    dashboard_file = Path(dashboard_path)

    @app.get("/")
    def index():
        return HTML

    @app.get("/dashboard")
    def dashboard():
        if dashboard_file.exists():
            return send_file(dashboard_file.resolve())
        return Response(
            "<h2 style='font-family:Arial'>Dashboard file not found</h2>"
            f"<p style='font-family:Arial'>Expected file: <code>{dashboard_file}</code></p>"
            "<p style='font-family:Arial'>Please run: <code>python -m claims_analysis.html_dashboard --reports-dir reports/latest</code></p>",
            mimetype="text/html",
            status=404,
        )

    return app


HTML = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Claims Analysis Portal</title><style>
:root{--bg:#f3f6fb;--text:#172033;--muted:#64748b;--border:#dbe3ef;--primary:#1d4ed8;--dark:#0f172a;--danger:#b91c1c;--shadow:0 10px 25px rgba(15,23,42,.08)}*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--text);height:100vh;overflow:hidden}.shell{display:grid;grid-template-columns:285px minmax(0,1fr);height:100vh}.sidebar{background:linear-gradient(180deg,#0f172a,#111827);color:white;padding:20px 16px;display:flex;flex-direction:column;gap:14px}.brand{padding:6px 8px 14px;border-bottom:1px solid rgba(255,255,255,.14)}.brand h1{font-size:22px;margin:0 0 6px}.brand p{font-size:12px;color:#cbd5e1;margin:0;line-height:1.4}.nav{display:flex;flex-direction:column;gap:8px}.nav button{width:100%;text-align:left;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.06);color:#e5e7eb;border-radius:12px;padding:12px 13px;font-weight:800;cursor:pointer}.nav button.active{background:white;color:#0f172a;border-color:white}.nav button.locked{opacity:.38;cursor:not-allowed}.nav small{display:block;color:#94a3b8;font-weight:400;margin-top:3px}.status{margin-top:auto;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-radius:12px;padding:12px;font-size:12px;color:#cbd5e1;line-height:1.5}.code{font-family:Consolas,monospace;background:#f8fafc;border:1px solid var(--border);border-radius:8px;padding:2px 6px;color:#334155}.main{display:flex;flex-direction:column;min-width:0}.topbar{height:62px;background:white;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 18px}.topbar h2{margin:0;font-size:18px}.actions{display:flex;gap:8px;align-items:center}.actions a,.actions button{border:1px solid var(--border);background:white;border-radius:9px;padding:8px 10px;text-decoration:none;color:var(--text);font-size:12px;font-weight:800;cursor:pointer}.actions a.primary{background:var(--primary);border-color:var(--primary);color:white}.actions button.danger{color:var(--danger);border-color:#fecaca}.framewrap{flex:1;padding:14px;min-height:0}.framecard{height:100%;background:white;border:1px solid var(--border);border-radius:16px;overflow:hidden;box-shadow:var(--shadow)}iframe{width:100%;height:100%;border:0}.home{padding:22px;overflow:auto;height:100%}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}.card{background:white;border:1px solid var(--border);border-radius:16px;padding:18px;box-shadow:0 1px 4px rgba(15,23,42,.06)}.card h3{margin:0 0 8px}.card p{color:var(--muted);font-size:13px;line-height:1.45}.login{position:fixed;inset:0;background:rgba(15,23,42,.76);z-index:99;display:flex;align-items:center;justify-content:center;padding:18px}.login-card{width:min(460px,96%);background:white;border-radius:18px;padding:22px;box-shadow:0 25px 60px rgba(0,0,0,.35)}.login-card h2{margin:0 0 8px}.login-card p{color:var(--muted);font-size:13px}.field{margin-top:12px}.field label{display:block;color:var(--muted);font-size:12px;margin-bottom:5px;font-weight:800}.field input{width:100%;padding:10px;border:1px solid var(--border);border-radius:10px}.login-card button{margin-top:14px;width:100%;background:var(--primary);color:white;border:0;border-radius:10px;padding:11px;font-weight:800;cursor:pointer}.login-error{display:none;margin-top:10px;background:#fee2e2;color:#991b1b;border:1px solid #fecaca;border-radius:10px;padding:9px;font-size:12px}.hint{margin-top:12px;background:#f8fafc;border:1px solid var(--border);border-radius:10px;padding:10px;color:#475569;font-size:12px;line-height:1.45}@media(max-width:900px){body{overflow:auto}.shell{grid-template-columns:1fr;height:auto}.main{height:80vh}.framewrap{padding:8px}}
</style></head><body>
<div id="loginPanel" class="login"><div class="login-card"><h2>Claims Analysis Portal Login</h2><p>Enter assigned credentials to access your role-based modules.</p><div class="field"><label>Username</label><input id="loginUsername" autocomplete="username" placeholder="username"></div><div class="field"><label>Password</label><input id="loginPassword" type="password" autocomplete="current-password" placeholder="password" onkeydown="if(event.key==='Enter')login()"></div><button onclick="login()">Login</button><div id="loginError" class="login-error">Invalid username or password.</div><div class="hint"><b>Default users</b><br>admin / admin123<br>claims / claims123<br>finance / finance123</div></div></div>
<div class="shell"><aside class="sidebar"><div class="brand"><h1>Claims Portal</h1><p>One housing module for dashboard, scheduling, and budgeting.</p><p id="userBadge" style="margin-top:8px;color:#facc15">Not logged in</p></div><nav class="nav"><button id="navHome" class="active" onclick="showHome()">Home <small>System overview and startup status</small></button><button id="navDashboard" onclick="loadFrame('Dashboard','/dashboard','navDashboard')">Dashboard <small>Claims analysis HTML dashboard</small></button><button id="navPayment" data-role="Claims Manager,Admin" onclick="guardedLoad('Payment Scheduling',paymentUrl(),'navPayment')">Payment Scheduling <small>Claims Manager / Admin</small></button><button id="navBudget" data-role="Finance Manager,Admin" onclick="guardedLoad('Budget Management',budgetUrl(),'navBudget')">Budget Management <small>Finance Manager / Admin</small></button></nav><div class="status"><b>Startup:</b><br><span class="code">python run_claims_portal.py</span><br><br>Portal: <span id="portalHost">5049</span><br>Payment: <span id="paymentHost">5050</span><br>Budget: <span id="budgetHost">5051</span></div></aside><section class="main"><div class="topbar"><h2 id="pageTitle">Home</h2><div class="actions"><button onclick="refreshCurrent()">Refresh View</button><a id="openNew" class="primary" href="/" target="_blank">Open in New Tab</a><button class="danger" onclick="logout()">Logout</button></div></div><div class="framewrap"><div id="homePanel" class="home framecard"><h2>Claims Analysis Portal</h2><p style="color:#64748b">Use the left menu to open each module inside this portal.</p><div class="grid"><div class="card"><h3>Dashboard</h3><p>Reconciliation KPIs, charts, provider analytics, aging, and claims reports.</p></div><div class="card"><h3>Payment Scheduling</h3><p>Claims Manager workflow for For Scheduling, Scheduled, provider drilldown, and batch scheduling.</p></div><div class="card"><h3>Budget Management</h3><p>Finance Manager workflow for monthly budget, fixed 4-week allocation, weekly reallocation, and approvals.</p></div></div><div class="card" style="margin-top:14px"><h3>Recommended Startup</h3><p><span class="code">python run_claims_portal.py</span></p><p id="networkInfo" style="color:#64748b"></p></div></div><div id="framePanel" class="framecard" style="display:none"><iframe id="mainFrame" src="about:blank"></iframe></div></div></section></div>
<script>
const USERS={admin:{password:'admin123',name:'Administrator',role:'Admin'},claims:{password:'claims123',name:'Claims Manager',role:'Claims Manager'},finance:{password:'finance123',name:'Finance Manager',role:'Finance Manager'}};
let currentUrl='/';let currentUser='';let currentRole='';
function baseHost(){return window.location.hostname||'127.0.0.1'}function paymentUrl(){return window.location.protocol+'//'+baseHost()+':5050'}function budgetUrl(){return window.location.protocol+'//'+baseHost()+':5051'}function setNetworkLabels(){portalHost.textContent=baseHost()+':5049';paymentHost.textContent=baseHost()+':5050';budgetHost.textContent=baseHost()+':5051';networkInfo.textContent='Current portal host: '+baseHost()+'. Embedded modules will use this same host.'}
function setActive(id){['navHome','navDashboard','navPayment','navBudget'].forEach(x=>document.getElementById(x).classList.toggle('active',x===id))}function hasAccess(navId){const btn=document.getElementById(navId);const allowed=(btn.dataset.role||'').split(',').filter(Boolean);return allowed.length===0||allowed.includes(currentRole)}function applyAccess(){['navPayment','navBudget'].forEach(id=>document.getElementById(id).classList.toggle('locked',!hasAccess(id)))}
function login(){const u=loginUsername.value.trim().toLowerCase();const p=loginPassword.value;const rec=USERS[u];if(!rec||rec.password!==p){loginError.style.display='block';return}currentUser=rec.name;currentRole=rec.role;sessionStorage.setItem('claimsPortalUser',currentUser);sessionStorage.setItem('claimsPortalRole',currentRole);userBadge.textContent=currentUser+' | '+currentRole;loginPanel.style.display='none';loginError.style.display='none';applyAccess();showHome()}
function restoreLogin(){currentUser=sessionStorage.getItem('claimsPortalUser')||'';currentRole=sessionStorage.getItem('claimsPortalRole')||'';if(currentUser&&currentRole){userBadge.textContent=currentUser+' | '+currentRole;loginPanel.style.display='none';applyAccess();}}
function logout(){sessionStorage.removeItem('claimsPortalUser');sessionStorage.removeItem('claimsPortalRole');currentUser='';currentRole='';loginPanel.style.display='flex';mainFrame.src='about:blank';showHome()}
function showHome(){setActive('navHome');pageTitle.textContent='Home';homePanel.style.display='block';framePanel.style.display='none';openNew.href='/';currentUrl='/'}function guardedLoad(title,url,navId){if(!hasAccess(navId)){alert('Access restricted for '+currentRole+'.');return}loadFrame(title,url,navId)}function loadFrame(title,url,navId){setActive(navId);pageTitle.textContent=title;homePanel.style.display='none';framePanel.style.display='block';mainFrame.src=url;openNew.href=url;currentUrl=url}function refreshCurrent(){if(currentUrl==='/'){location.reload();return}mainFrame.src=currentUrl}
setNetworkLabels();restoreLogin();
</script></body></html>
"""


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Run Claims Analysis Portal.")
    parser.add_argument("--dashboard", default=DEFAULT_DASHBOARD)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5049)
    args = parser.parse_args()
    app = create_app(args.dashboard)
    print(f"{APP_TITLE} running at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
