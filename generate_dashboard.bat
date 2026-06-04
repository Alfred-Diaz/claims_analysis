@echo off
setlocal

echo ========================================
echo Claims Analysis - HTML Dashboard Generator
echo ========================================
echo.

if not exist "reports\latest" (
    echo reports\latest does not exist yet.
    echo Run the claims analysis first before generating the dashboard.
    pause
    exit /b 1
)

python -m claims_analysis.html_dashboard --reports-dir reports/latest

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Dashboard generation failed.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo Dashboard generated successfully.
echo Opening reports\latest\dashboard.html...
start "" "reports\latest\dashboard.html"
echo.
pause
