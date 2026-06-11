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
            "<h2>Dashboard file not found</h2>"
            f"<p>Expected file: <code>{dashboard_file}</code></p>"
            "<p>Please run: <code>python -m claims_analysis.html_dashboard --reports-dir reports/latest</code></p>",
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
:root{--bg:#f3f6fb;--card:#fff;--text:#172033;--muted:#64748b;--border:#dbe3ef;--primary:#1d4ed8;--good:#047857;--dark:#0f172a}*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--text)}header{background:var(--dark);color:white;padding:26px 34px}header h1{margin:0 0 6px;font-size:28px}header p{margin:0;color:#cbd5e1}main{padding:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px}.card{background:var(--card);border:1px solid var(--border);border-radius:18px;padding:22px;box-shadow:0 2px 8px rgba(15,23,42,.08);min-height:220px;display:flex;flex-direction:column;justify-content:space-between}.card h2{margin:0 0 10px;font-size:22px}.card p{color:var(--muted);line-height:1.45}.btns{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}a.btn{display:inline-block;text-decoration:none;border-radius:10px;padding:11px 14px;font-weight:800;border:1px solid var(--border);color:var(--text);background:white}a.primary{background:var(--primary);border-color:var(--primary);color:white}a.good{background:var(--good);border-color:var(--good);color:white}.note{margin-top:22px;color:var(--muted);font-size:13px;background:white;border:1px solid var(--border);border-radius:14px;padding:14px}.code{font-family:Consolas,monospace;background:#f8fafc;border:1px solid var(--border);border-radius:8px;padding:2px 6px;color:#334155}
</style>
</head>
<body>
<header>
<h1>Claims Analysis Portal</h1>
<p>Single housing module for Dashboard, Payment Scheduling, and Budget Management.</p>
</header>
<main>
<div class="grid">
  <section class="card">
    <div>
      <h2>Claims Dashboard</h2>
      <p>Open the generated HTML dashboard for reconciliation, KPIs, provider analytics, aging, and report views.</p>
    </div>
    <div class="btns">
      <a class="btn primary" href="/dashboard" target="_blank">Open Dashboard</a>
    </div>
  </section>

  <section class="card">
    <div>
      <h2>Payment Scheduling</h2>
      <p>Open the Claims Payment Workflow app for For Scheduling, Scheduled, category tabs, provider drilldown, and calendar/list views.</p>
    </div>
    <div class="btns">
      <a class="btn good" href="http://127.0.0.1:5050" target="_blank">Open Payment App</a>
    </div>
  </section>

  <section class="card">
    <div>
      <h2>Budget Management</h2>
      <p>Open the Budget Management app for monthly budget, 4-week allocation, weekly reallocation, and monthly approval queue.</p>
    </div>
    <div class="btns">
      <a class="btn good" href="http://127.0.0.1:5051" target="_blank">Open Budget App</a>
    </div>
  </section>
</div>

<div class="note">
  <b>Startup requirement:</b> keep the portal, payment app, and budget app running in separate PowerShell windows for now.<br><br>
  Portal: <span class="code">python -m claims_analysis.portal_app</span><br>
  Payment Scheduling: <span class="code">python -m claims_analysis.payment_app</span><br>
  Budget Management: <span class="code">python -m claims_analysis.budget_app</span>
</div>
</main>
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
