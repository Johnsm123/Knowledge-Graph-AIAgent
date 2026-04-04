@echo off
echo ========================================
echo Care Gap Management System - Startup
echo ========================================
echo.

echo Starting Backend API Server (Flask on port 5001)...
start cmd /k "cd /d %~dp0 && venv\Scripts\python -m src.care_gap_api"

timeout /t 3 /nobreak >nul

echo Starting Frontend Dev Server (Vite on port 5173)...
start cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo ========================================
echo Servers Starting...
echo ========================================
echo Backend API: http://localhost:5001
echo Frontend UI: http://localhost:5173
echo ========================================
echo.
echo Press any key to exit this window...
pause >nul
