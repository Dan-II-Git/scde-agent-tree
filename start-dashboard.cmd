@echo off
REM ─────────────────────────────────────────────────────────────────────
REM SCDE Finance Dashboard — local launcher
REM Double-click this file to start the server and open the browser.
REM Closing this window stops the server.
REM ─────────────────────────────────────────────────────────────────────

cd /d "%~dp0"
title SCDE Finance Dashboard

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo ERROR: virtual environment not found at .venv\
    echo.
    echo Rebuild it with:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "db\scde.duckdb" (
    echo.
    echo ERROR: database not found at db\scde.duckdb
    echo.
    pause
    exit /b 1
)

echo Starting SCDE Finance Dashboard on http://127.0.0.1:8765 ...
echo Close this window or press Ctrl+C to stop.
echo.

REM Open the browser after a brief delay so the server has time to bind.
start "" /b cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:8765"

.venv\Scripts\python.exe -m app.server

echo.
echo Server stopped.
pause
