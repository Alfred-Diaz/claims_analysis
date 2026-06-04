@echo off
setlocal

echo ========================================
echo Claims Analysis - Large File Processor
echo ========================================
echo.

if not exist "data\raw" mkdir "data\raw"
if not exist "reports" mkdir "reports"
if not exist "archive" mkdir "archive"

set CLAIMS_FILE=data\raw\CLAIMS PROCESS-FINAL.csv
set CHECKS_FILE=data\raw\CHECK-DATE CREATED.csv
set AMOUNT_COLUMN=amount

echo Claims file: %CLAIMS_FILE%
echo Checks file: %CHECKS_FILE%
echo Amount column: %AMOUNT_COLUMN%
echo.

echo Starting large dataset processing...
python app.py --large --claims "%CLAIMS_FILE%" --checks "%CHECKS_FILE%" --amount-col "%AMOUNT_COLUMN%"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Processing failed. Review the terminal message and reports\history run_log.txt if created.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo Processing completed successfully.
echo Latest reports are in reports\latest
echo.
pause
