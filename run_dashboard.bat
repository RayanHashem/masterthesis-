@echo off
title Lebanon EMS AHP Dashboard Launcher
cd /d "%~dp0"

echo ================================================================
echo  Lebanon EMS - AHP Dashboard + Copilot Launcher
echo ================================================================
echo.

REM ---- 1) Verify venv ---------------------------------------------
if not exist "venv\Scripts\python.exe" goto :no_venv
echo [1/5] Found Python venv. OK.

REM ---- 2) Install missing deps if needed ---------------------------
echo [2/5] Verifying dependencies...
"venv\Scripts\python.exe" -c "import geopandas, folium, rasterio, osmnx, fastapi, uvicorn, pydantic" 2>nul
if errorlevel 1 (
    echo       Installing missing deps from requirements.txt ...
    "venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :pip_failed
)
echo       OK.

REM ---- 3) Build the AHP dashboard HTML -----------------------------
echo [3/5] Building AHP dashboard HTML...
set PYTHONIOENCODING=utf-8
if not exist "data\road_graph_lebanon.graphml" (
    echo       Road graph cache missing. Skipping OpenStreetMap download for fast local launch.
    echo       To build full road-time coverage later, unset LEBANON_EMS_SKIP_OSM and re-run with internet.
    set LEBANON_EMS_SKIP_OSM=1
) else (
    set LEBANON_EMS_SKIP_OSM=
)
"venv\Scripts\python.exe" scripts\phase1_ahp_explore.py
if errorlevel 1 goto :build_failed

REM ---- 4) Try to start Ollama (optional, non-fatal) ----------------
echo [4/5] Checking optional Ollama AI service...
where ollama >nul 2>nul
if errorlevel 1 (
    echo       Ollama not installed. Copilot will use deterministic mode only.
    echo       To enable natural-language answers, install from:
    echo       https://ollama.com/download/windows
) else (
    echo       Ollama detected. Starting service in background...
    start "" /B ollama serve >nul 2>nul
    start "" /B ollama pull qwen2.5:3b >nul 2>nul
)

REM ---- 5) Launch Copilot backend + open the dashboard --------------
echo [5/5] Starting Copilot backend on http://127.0.0.1:8000 ...
start "EMS Copilot Backend (keep this open)" cmd /k "title EMS Copilot Backend && cd /d %~dp0 && set PYTHONIOENCODING=utf-8 && venv\Scripts\python.exe -m uvicorn --app-dir scripts copilot_server:app --host 127.0.0.1 --port 8000"

echo       Waiting for backend to come up...
timeout /t 4 /nobreak >nul

echo       Opening dashboard in your default browser...
start "" "data\phase1_ahp_dashboard.html"

echo.
echo ================================================================
echo  Done.
echo.
echo  - Dashboard is open in your browser.
echo  - The "EMS Copilot Backend" window must stay OPEN for the
echo    AI Copilot to work. Close it to stop the backend.
echo  - This window can be closed at any time.
echo ================================================================
echo.
pause
exit /b 0


:no_venv
echo.
echo [ERROR] Python venv not found at: %~dp0venv
echo Run this once to create it:
echo   py -3.13 -m venv venv
echo   venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
pause
exit /b 1

:pip_failed
echo.
echo [ERROR] pip install failed. Check your internet connection.
echo.
pause
exit /b 1

:build_failed
echo.
echo [ERROR] Dashboard build failed. See the messages above.
echo Try manually:
echo   venv\Scripts\python.exe scripts\phase1_ahp_explore.py
echo.
pause
exit /b 1
