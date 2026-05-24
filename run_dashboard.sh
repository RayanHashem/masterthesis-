#!/bin/bash
# Lebanon EMS AHP Dashboard Launcher (Mac/Linux)
cd "$(dirname "$0")"

echo "================================================================"
echo " Lebanon EMS - AHP Dashboard + Copilot Launcher"
echo "================================================================"
echo ""

# Use the shared venv from lebanon-ems
PYTHON="lebanon-ems/venv/bin/python"

# ---- 1) Verify venv -----------------------------------------------
if [ ! -f "$PYTHON" ]; then
    echo "[ERROR] Python venv not found at lebanon-ems/venv."
    echo "Run this once to create it:"
    echo "  python3 -m venv lebanon-ems/venv"
    echo "  lebanon-ems/venv/bin/pip install -r requirements.txt"
    exit 1
fi
echo "[1/5] Found Python venv. OK."

# ---- 2) Check deps (no install needed — venv is pre-built) --------
echo "[2/5] Verifying dependencies..."
"$PYTHON" -c "import geopandas, folium, rasterio, osmnx" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "[ERROR] Missing dependencies. Run: lebanon-ems/venv/bin/pip install -r requirements.txt"
    exit 1
fi
echo "      OK."

# ---- 3) Build the AHP dashboard HTML ------------------------------
echo "[3/5] Building AHP dashboard HTML..."
export PYTHONIOENCODING=utf-8
if [ ! -f "lebanon-ems-ahp/data/road_graph_lebanon.graphml" ]; then
    echo "      Road graph cache missing. Skipping OpenStreetMap download."
    export LEBANON_EMS_SKIP_OSM=1
else
    unset LEBANON_EMS_SKIP_OSM
fi
"$PYTHON" lebanon-ems-ahp/scripts/phase1_ahp_explore.py
if [ $? -ne 0 ]; then
    echo "[ERROR] Dashboard build failed. See messages above."
    exit 1
fi

# ---- 4) Try to start Ollama (optional) ----------------------------
echo "[4/5] Checking optional Ollama AI service..."
if ! command -v ollama &>/dev/null; then
    echo "      Ollama not installed. Copilot will use deterministic mode only."
    echo "      To enable natural-language answers, install from https://ollama.com"
else
    echo "      Ollama detected. Starting service in background..."
    ollama serve >/dev/null 2>&1 &
    ollama pull qwen2.5:3b >/dev/null 2>&1 &
fi

# ---- 5) Launch Copilot backend + open dashboard -------------------
echo "[5/5] Starting Copilot backend on http://127.0.0.1:8000 ..."
PYTHONIOENCODING=utf-8 "$PYTHON" -m uvicorn --app-dir lebanon-ems-ahp/scripts copilot_server:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

echo "      Waiting for backend to come up..."
sleep 4

echo "      Opening dashboard in your browser..."
open "lebanon-ems-ahp/data/phase1_ahp_dashboard.html"

echo ""
echo "================================================================"
echo " Done."
echo ""
echo " - Dashboard is open in your browser."
echo " - Copilot backend is running (PID $BACKEND_PID)."
echo " - Press Ctrl+C in this terminal to stop the backend."
echo "================================================================"
echo ""

# Keep script alive so backend stays running
wait $BACKEND_PID
