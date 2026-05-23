# Lebanon EMS Coverage Analysis — AHP Edition

A multi-criteria (Analytic Hierarchy Process) gap assessment of Lebanon's
Emergency Medical Services coverage at the *qadaa* (district) level, with
an interactive dashboard, a live in-browser AHP model, and a local-only
**EMS Copilot** chat assistant.

> **Master's research project — Rayan Hashem.**
> All data processing and AI inference runs locally; no data leaves your machine.

---

## Quick start (Windows)

### Option A — One-click launcher (recommended)

1. Open **Windows File Explorer** and navigate to this folder.
2. Double-click **`run_dashboard.bat`**.
3. Two windows appear:
   - **EMS Copilot Backend** — keep this open while you use the dashboard.
   - **Launcher** — you can close it once the dashboard has loaded.
4. Your default browser opens `data/phase1_ahp_dashboard.html`.

If anything fails, the launcher pauses on every error so you can read the message.

### Option B — Manual (PowerShell)

```powershell
cd "C:\path\to\lebanon-ems-ahp"

# First-time setup
py -3.13 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# Build the dashboard (also writes the AHP sidecar JSON the Copilot reads)
$env:PYTHONIOENCODING = 'utf-8'
.\venv\Scripts\python.exe scripts\phase1_ahp_explore.py

# Open the dashboard
Start-Process .\data\phase1_ahp_dashboard.html

# (Optional) Start the Copilot backend in a separate window
.\venv\Scripts\python.exe -m uvicorn --app-dir scripts copilot_server:app --host 127.0.0.1 --port 8000
```

### Option C — macOS / Linux

```bash
cd lebanon-ems-ahp
python3.13 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt

python scripts/phase1_ahp_explore.py
open data/phase1_ahp_dashboard.html         # macOS
# xdg-open data/phase1_ahp_dashboard.html   # Linux

uvicorn --app-dir scripts copilot_server:app --host 127.0.0.1 --port 8000
```

---

## Enabling the AI Copilot (optional)

The Copilot answers natural-language questions like *"Which districts are highest
priority?"* or *"Where can I open an EMS center in Ras al Nabeh, Beirut?"*. It
runs **100 % locally** via [Ollama](https://ollama.com) — no API key, no internet
calls.

1. Install Ollama: <https://ollama.com/download>
2. Pull the model (one-time, ~2 GB):
   ```powershell
   ollama pull qwen2.5:3b
   ```
3. Re-run `run_dashboard.bat` — it auto-detects Ollama and uses it.

Without Ollama, the Copilot still works in **deterministic mode** — it answers
lookup, ranking, comparison, AHP-explanation, and placement questions from the
data directly, just without free-form natural language phrasing.

**Hardware requirements:** ~3 GB disk, ~6 GB RAM while answering.

The Copilot reads `data/phase1_ahp_districts.json` (written automatically by
`scripts/phase1_ahp_explore.py`) so its answers stay aligned with the model
shown in the dashboard. Re-run the Python script after any model change to
keep them in sync.

---

## What's in the dashboard

| Section | What it shows |
|---|---|
| **Map** | Lebanon's districts colored by AHP priority (the only colored surface in the project). Click a polygon for a detail card. |
| **Model tab** | Live AHP weights (sliders), priority thresholds, a Live Results panel with priority chips and the top-N districts. |
| **Analysis tab** | Headline KPIs, district ranking table with score bars, recommended new-station candidates. |
| **Filters tab** | Toggle map layers (districts, EMS, candidates, coverage). |
| **Selected district card** | Floating bottom-left card; appears when you click a district on the map or in a table. |
| **EMS Copilot** | Floating circular **AI** button at the bottom right — opens a chat panel that talks to the local FastAPI backend. |

The dashboard chrome (panel, tables, chat UI) is rendered in a strict
**black-and-white** theme so the map's color encoding stands out unambiguously.

---

## AHP Model — How Scoring Works

### Criteria and Default Weights

| # | Criterion | Weight | What It Measures |
|---|---|---|---|
| C1 | Travel-Time Gap | **50 %** | Road travel time (minutes) from the district centroid to the nearest EMS station. Higher = worse. |
| C2 | Population Density | **30 %** | People per km² in the district. Denser → higher priority. |
| C3 | Exposed Population | **20 %** | Population beyond the coverage threshold (default 10 min). |

### Score Formula

```
AHP Score = 0.5 × norm_access_gap + 0.3 × norm_pop_density + 0.2 × norm_exposed_pop
```

All three components are **min-max normalized** to [0, 1] across districts
before weighting.

### Priority Classification

Districts are ranked by AHP score then classified using **quantile thresholds**:

- **High** — top 20 % of scores
- **Medium** — top 21–50 % of scores
- **Low** — bottom 50 % of scores

These thresholds are also adjustable live in the dashboard.

### Coverage Threshold vs. Travel-Time Gap

- **Travel-Time Gap (C1):** Continuous. Always active. Measures *how bad*.
- **Coverage Threshold:** A policy line (default 10 min). Used only for C3 — a
  district is "exposed" if its nearest station is beyond this threshold. Changing
  it re-classifies districts as covered/exposed and recalculates C3 live.

### Authoritative sources

- **Boundaries** — [GADM 4.1](https://gadm.org), admin level 2
- **Population** — [WorldPop 2024 CN](https://www.worldpop.org), 1 km constrained
- **Roads** — OpenStreetMap via OSMnx (cached to `data/road_graph_lebanon.graphml`)
- **Response standard** — Lebanese Red Cross / IFRC INP 2023: *80 % of calls
  within 9 min, 85 % within 13 min*
- **Licensing** — Lebanese Ministry of Public Health, Karar No. 473/2021
- **Critical-call benchmark** — European standard, 8 min for life-threatening calls

### Limitations

- Lebanon does not publicly codify a spatial spacing rule for EMS bases.
  The 1.5 km / 5 km thresholds are transparent **demo heuristics**, not statutes.
- Travel-time uses the OSM road graph; live traffic is not modeled.
- The EMS station list is an operational snapshot; it may not reflect every
  active facility.

---

## Saving Your Work / Version Control

The project uses **git** for checkpoints. The `.gitignore` excludes the venv,
caches, the generated dashboard, and the AHP sidecar JSON — re-running
`scripts/phase1_ahp_explore.py` rebuilds them.

```bash
git add -A
git commit -m "Phase X experiment"
git tag phaseX-complete
```

Restore with `git checkout phaseX-complete` or, destructively,
`git reset --hard phaseX-complete`.

---

## Project layout

```
lebanon-ems-ahp/
├─ run_dashboard.bat                 # One-click Windows launcher
├─ requirements.txt                  # Python dependencies
├─ .gitignore
├─ PROJECT_NOTES.md                  # ← this file
├─ data/
│  ├─ gadm41_LBN_2.json              # District boundaries (GADM 4.1)
│  ├─ EMS_Station_Locations.xlsx
│  ├─ lbn_pop_2024_CN_1km_R2025A_UA_v1.tif   # WorldPop raster
│  ├─ phase1_ahp_dashboard.html      # (generated)
│  ├─ phase1_ahp_districts.json      # (generated — read by Copilot)
│  └─ road_graph_lebanon.graphml     # (generated, cached OSM graph)
├─ templates/
│  ├─ phase1_ahp_dashboard.html      # Page shell
│  ├─ phase1_ahp_dashboard.css       # Black-and-white panel styles
│  └─ phase1_ahp_dashboard.js        # Client logic + Copilot chat client
└─ scripts/
   ├─ phase1_ahp_explore.py          # Builds the dashboard
   ├─ copilot_server.py              # FastAPI Copilot backend
   └─ lebanon_ems_rules.py           # Encoded standards + citations
```

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Esc` | Close the Copilot panel |

---

## Troubleshooting

**The launcher window closes immediately.**
Open it from **File Explorer**, not from inside an editor terminal. The launcher
pauses on every error path.

**"Copilot offline" indicator stays red.**
The FastAPI backend isn't running. Either run `run_dashboard.bat` or start it
manually:

```powershell
.\venv\Scripts\python.exe -m uvicorn --app-dir scripts copilot_server:app --host 127.0.0.1 --port 8000
```

**Copilot answers in deterministic mode only.**
Ollama isn't installed or `qwen2.5:3b` isn't pulled. See the AI Copilot section above.

**Copilot has no AHP data.**
Run `scripts/phase1_ahp_explore.py` once to generate `data/phase1_ahp_districts.json`.

**`UnicodeEncodeError` when running the script.**
Set `PYTHONIOENCODING=utf-8` first. The launcher does this automatically.

---

## Authors

Project by **Rayan Hashem** — Master's research on EMS coverage gap analysis in
Lebanon using the Analytic Hierarchy Process. All data processing and AI
inference runs locally; no data leaves your machine.
