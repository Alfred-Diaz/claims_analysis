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
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claims Analysis Portal</title>
<style>
:root{--bg:#f3f6fb;--panel:#ffffff;--text:#172033;--muted:#64748b;--border:#dbe3ef;--primary:#1d4ed8;--dark:#0f172a;--active:#dbeafe}*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--text);height:100vh;overflow:hidden}.shell{display:grid;grid-template-columns:280px minmax(0,1fr);height:100vh}.sidebar{background:var(--dark);color:white;padding:20px 16px;display:flex;flex-direction:column;gap:14px}.brand{padding:6px 8px 14px;border-bottom:1px solid rgba(255,255,255,.14)}.brand h1{font-size:22px;margin:0 0 6px}.brand p{font-size:12px;color:#cbd5e1;margin:0;line-height:1.4}.nav{display:flex;flex-direction:column;gap:8px}.nav button{width:100%;text-align:left;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.06);color:#e5e7eb;border-radius:12px;padding:12px 13px;font-weight:800;cursor:pointer}.nav button.active{background:white;color:#0f172a;border-color:white}.nav small{display:block;color:#94a3b8;font-weight:400;margin-top:3px}.status{margin-top:auto;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-radius:12px;padding:12px;font-size:12px;color:#cbd5e1;line-height:1.5}.main{display:flex;flex-direction:column;min-width:0}.topbar{height:62px;background:white;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 18px}.topbar h2{margin:0;font-size:18px}.actions{display:flex;gap:8px;align-items:center}.actions a,.actions button{border:1px solid var(--border);background:white;border-radius:9px;padding:8px 10px;text-decoration:none;color:var(--text);font-size:12px;font-weight:800;cursor:pointer}.actions a.primary{background:var(--primary);border-color:var(--primary);color:white}.framewrap{flex:1;padding:14px;min-height:0}.framecard{height:100%;background:white;border:1px solid var(--border);border-radius:16px;overflow:hidden;box-shadow:0 2px 8px rgba(15,23,42,.08)}iframe{width:100%;height:100%;border:0}.home{padding:22px;overflow:auto;height:100%}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}.card{background:white;border:1px solid var(--border);border-radius:16px;padding:18px;box-shadow:0 1px 4px rgba(15,23,42,.06)}.card h3{margin:0 0 8px}.card p{color:var(--muted);font-size:13px;line-height:1.45}.code{font-family:Consolas,monospace;background:#f8fafc;border:1px solid var(--border);border-radius:8px;padding:2px 6px;color:#334155}.mobile-note{display:none}@media(max-width:900px){body{overflow:auto}.shell{grid-template-columns:1fr;height:auto}.sidebar{position:relative}.main{height:80vh}.mobile-note{display:block;color:#facc15;font-size:12px}.framewrap{padding:8px}}
</style>
</head>
<body>
<div class="shell">
  <aside class="sidebar">
    <div class="brand">
      <h1>Claims Portal</h1>
      <p>One housing module for dashboard, scheduling, and budgeting.</p>
      <p class="mobile-note">Tip: use desktop width for best embedded view.</p>
    </div>
    <nav class="nav">
      <button id="navHome" class="active" onclick="showHome()">Home <small>System overview and startup status</small></button>
      <button id="navDashboard" onclick="loadFrame('Dashboard','/dashboard','navDashboard')">Dashboard <small>Claims analysis HTML dashboard</small></button>
      <button id="navPayment" onclick="loadFrame('Payment Scheduling','http://127.0.0.1:5050','navPayment')">Payment Scheduling <small>For Scheduling and Scheduled modules</small></button>
      <button id="navBudget" onclick="loadFrame('Budget Management','http://127.0.0.1:5051','navBudget')">Budget Management <small>Monthly and weekly budget controls</small></button>
    </nav>
    <div class="status">
      <b>Current startup:</b><br>
      <span class="code">python run_claims_portal.py</span><br><br>
      Portal: 5049<br>
      Payment: 5050<br>
      Budget: 5051
    </div>
  </aside>
  <section class="main">
    <div class="topbar">
      <h2 id="pageTitle">Home</h2>
      <div class="actions">
        <button onclick="refreshCurrent()">Refresh View</button>
        <a id="openNew" class="primary" href="/" target="_blank">Open in New Tab</a>
      </div>
    </div>
    <div class="framewrap">
      <div id="homePanel" class="home framecard">
        <h2>Claims Analysis Portal</h2>
        <p style="color:#64748b">Use the left menu to open each module inside this portal.</p>
        <div class="grid">
          <div class="card"><h3>Dashboard</h3><p>Shows reconciliation KPIs, charts, provider analytics, aging, and claims reports generated in <span class="code">reports/latest/dashboard.html</span>.</p></div>
          <div class="card"><h3>Payment Scheduling</h3><p>Handles For Scheduling, Scheduled, category tabs, provider drilldown, calendar view, and batch scheduling.</p></div>
          <div class="card"><h3>Budget Management</h3><p>Handles PHP 65,000,000 default monthly budget, fixed four-week allocation, weekly reallocation, monthly fund requests, and Finance Manager approval queue.</p></div>
        </div>
        <div class="card" style="margin-top:14px">
          <h3>Recommended Startup</h3>
          <p>Run this single command from the project folder:</p>
          <p><span class="code">python run_claims_portal.py</span></p>
        </div>
      </div>
      <div id="framePanel" class="framecard" style="display:none"><iframe id="mainFrame" src="about:blank"></iframe></div>
    </div>
  </section>
</div>
<script>
let currentUrl='/';
function setActive(id){['navHome','navDashboard','navPayment','navBudget'].forEach(x=>document.getElementById(x).classList.toggle('active',x===id));}
function showHome(){setActive('navHome');document.getElementById('pageTitle').textContent='Home';document.getElementById('homePanel').style.display='block';document.getElementById('framePanel').style.display='none';document.getElementById('openNew').href='/';currentUrl='/';}
function loadFrame(title,url,navId){setActive(navId);document.getElementById('pageTitle').textContent=title;document.getElementById('homePanel').style.display='none';document.getElementById('framePanel').style.display='block';document.getElementById('mainFrame').src=url;document.getElementById('openNew').href=url;currentUrl=url;}
function refreshCurrent(){if(currentUrl==='/'){location.reload();return}document.getElementById('mainFrame').src=currentUrl;}
</script>
</body>
</html>
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
