# Lebanon EMS & Hospitals — Project Summary

> **Master's research project — Rayan Hashem.**
> A multi-criteria (Analytic Hierarchy Process / AHP) **gap assessment of Lebanon's
> health-emergency infrastructure** at the *qadaa* (district) level, delivered as a
> single interactive dashboard with a live in-browser AHP model and an optional
> local-only **EMS Copilot** chat assistant. All data processing and AI inference
> runs locally — no data leaves the machine.

This is the **one-stop summary** of the whole project. For deep detail see
`PROJECT_NOTES.md` (overall) and `PHASE2_NOTES.md` (hospitals handoff).

---

## 1. The big picture

The project covers **two phases / two datasets** that answer **two different
questions** about Lebanon's emergency-health system. The fact that they are
*different problems* is itself a finding.

| Phase | Dataset | Question | Honest framing |
|---|---|---|---|
| **Phase 1** | **EMS Stations** | *Where should we build new EMS stations?* | A **coverage / response-time** problem — "build here" pins are valid. |
| **Phase 2** | **Hospitals** | *Where are the hospital-service gaps, and what kind?* | A **distribution / affordability / operational** problem — Lebanon does **not** need more hospitals, so the view proposes **no** new pins. |

Both phases run the **same AHP engine** (`run_supply_analysis(...)`) over the same
26 districts, switched live in the dashboard via a **Dataset dropdown**. Phase 1's
EMS view is unchanged and regression-baselined; Phase 2 adds the hospital dataset
and a redesigned, honest hospital workflow.

---

## 2. Shared foundation (both phases)

### Geography & population
- **26 districts** (*qadaa*), boundaries from **GADM 4.1** (admin level 2).
- **Population** from **WorldPop 2024 CN**, 1 km constrained raster.
  Total ≈ **5.8 million** people.
- **Road travel time** from the **OpenStreetMap** road graph via OSMnx, cached to
  `data/road_graph_lebanon.graphml` (~360 MB; the dashboard build loads it, ~5 min).

### The AHP model
Each district gets an **AHP score** = weighted sum of **min-max normalized [0,1]**
criteria, then is classified into **High / Medium / Low** by **quantile thresholds**
(High = top 20%, Medium = 21–50%, Low = bottom 50%). Quantile-based means changing
weights changes the *ranking order*, not *how many* districts are flagged High.

### The dashboard
One self-contained file, `data/phase1_ahp_dashboard.html`, built from `templates/*`
by `scripts/phase1_ahp_explore.py`. Strict **black-and-white chrome** so the map's
color encoding (district priority) stands out. Tabs: **Model**, **Analysis**,
**Filters**, plus a floating selected-district card and the **EMS Copilot** button.

---

## 3. Phase 1 — EMS Stations

### Problem
Emergency response is a **coverage** problem: minimize how long it takes an
ambulance to reach the population. Valid to ask *"where to build a new station."*

### Data
- **52 EMS stations** plotted (operational snapshot, `EMS_Station_Locations.xlsx`).
- District boundaries + WorldPop + OSM road graph (shared foundation above).

### AHP criteria & default weights
| # | Criterion | Weight | Measures |
|---|---|---|---|
| C1 | Travel-Time Gap | **50%** | Road minutes from district centroid to nearest EMS station (higher = worse). |
| C2 | Population Density | **30%** | People per km² (denser → higher priority). |
| C3 | Exposed Population | **20%** | Population beyond the coverage threshold (default **10 min**). |

`AHP Score = 0.5·norm_access_gap + 0.3·norm_pop_density + 0.2·norm_exposed_pop`

- **Coverage threshold (10 min)** is a policy line used by C3 only; tunable live.
- **Standards encoded** (`scripts/lebanon_ems_rules.py`): Lebanese Red Cross / IFRC
  INP 2023 (80% of calls within 9 min, 85% within 13 min); European 8-min
  life-threatening benchmark; MoPH Karar 473/2021 licensing.

### EMS dashboard
- Map markers: **existing EMS stations as red "+" badges** (match the legend);
  **proposed/suggested stations as teal "+" pins**.
- **Suggested New EMS Stations** layer — **32 candidate** sites across presets
  (grid/cluster logic on the travel-time field).
- Model tab: live weight sliders, coverage threshold, priority chips, top-N
  districts. Analysis tab: KPIs, district ranking with score bars, candidate
  stations. Filters tab: toggle layers (districts, EMS, candidates, coverage).
- Spacing heuristics for candidates use **transparent demo thresholds** (1.5 km
  urban / 5 km rural) — Lebanon does not codify EMS base spacing.

---

## 4. Phase 2 — Hospitals

### The thesis (read this first)
Lebanon has **≈179 hospitals, ~10–15k beds, and almost everyone is within ~30 min**
of one. There is **no hospital *shortage*.** The real problems are
**maldistribution, affordability (≈88% private), and conflict damage** — i.e.
*distribution*, not *quantity*. **So the honest conclusion is: Lebanon does not
broadly need new hospitals; it needs better distribution / affordable (public)
capacity / operational support.** The dashboard shows *where* and *what kind* of gap
each district has, and deliberately proposes **no** "build-here" pins.

Validated against external ground truth: the model's chronic-gap districts
(**Akkar, Hermel, Baalbek**) match **MSF / AUB**'s named gap regions.

### Data pipeline (rebuild order)
```
1. scripts/prepare_hospitals.py        # raw GeoJSON -> clean hospital points
2. scripts/scrape_syndicate_hospitals.py   # (one-off) harvest Syndicate bed counts
3. scripts/enrich_hospital_beds.py     # merge real beds + classify public/private
4. scripts/phase1_ahp_explore.py       # build the dashboard (EMS + hospitals)
```

| Source | What | License |
|---|---|---|
| **Lebanon Healthsites** (Global Healthsites / OpenStreetMap, via HDX) | hospital **locations** | ODbL (attribution + share-alike) |
| **Syndicate of Hospitals in Lebanon** | real **bed counts** (134 private hospitals) | public directory, academic use |
| MoPH Health Facility Locator / Wikipedia / Wikidata / manual | public-hospital beds & a few coordinates | — |

- `prepare_hospitals.py` — filters raw → hospitals only; polygon→centroid; Lebanon
  bbox; dedupe by `osm_id`; excludes unnamed, pharmacies, Red-Cross branches,
  dispensaries, and reviewed mis-tagged non-hospitals.
- `scrape_syndicate_hospitals.py` — rate-limited scrape → 134-hospital reference
  (`data/lebanon_hospitals_syndicate.csv`). One-off; output committed.
- `enrich_hospital_beds.py` — the bed/ownership brain (idempotent). Produces the
  final `data/lebanon_hospitals.csv` and `data/lebanon_hospitals.geojson`.

### Final dataset — `data/lebanon_hospitals.csv`
**179 hospitals · 96 real beds / 83 estimated · 28 public / 151 private**
(82 ownership-tagged, 69 inferred). Each row records bed provenance (`beds_source`:
`osm-tag` / `syndicate-match` / `syndicate-arabic` / `public-moph-locator` /
`public-wikipedia` / `manual` / `median-estimate`) and a real/imputed flag.

**How the 96 real beds were obtained:** 3 from OSM tags; 35 Latin-name fuzzy
matches to the Syndicate; **39 Arabic-name matches** (every Arabic name read by hand
and confirmed against the Syndicate, June 2026); 5 hand-verified large hospitals
(Dar Al-Ajaza 700, AUBMC 400, …); **13 public hospitals** with authoritative beds
(RHUH 544 via Wikipedia; 12 via the MoPH locator — Saida 122, Nabatieh 100, Tripoli
78, …). The remaining 83 are **median-imputed (≈100 beds)** and flagged
`(estimated)` in the map popup. Real beds skew to the **largest** facilities, so the
Bed-Capacity-Gap criterion is materially driven by real capacity.

### Hospital AHP model (differs from EMS in 3 ways)
1. **4th criterion — Bed Capacity Gap** (inverse of beds/1,000 per district).
   Default weights: **Travel-Time 0.30 · Density 0.30 · Exposed 0.25 · Beds 0.15**
   (population-dominant by design).
2. **30-minute coverage threshold** (vs 10 min for EMS) — the "access to definitive
   care" standard. At 30 min the access gap is effectively **0** → shown as an honest
   green "✓ No access gap" state.
3. **Capacity Benchmark** control — national pop-weighted **beds/1,000 ≈ 3.6**,
   adjustable 1.0–6.0; drives the NEED classification.

### Hospital dashboard
- **Map:** "**H**" badge markers colored by ownership — **🔵 blue = public**
  (`#2980b9`, larger), **🔴 red = private** (`#c0392b`). Click → bottom-left detail
  card (status, beds, location, operator). Districts recolored by the hospital AHP
  priority. **The map legend is dataset-aware** (shows Public/Private hospital for
  the hospital view, Existing EMS / Proposed site for EMS).
- **Analysis tab — the 3-lens equity diagnostic** (main deliverable): every district
  graded on **Capacity** (beds/1,000 vs benchmark), **Access** (travel time), and
  **Affordability** (has a public hospital?), worst-served first. Plus **Recommended
  Interventions** — one card per gap district (worst-first by live AHP score) tagged
  with gap chips (`capacity` / `no public` / `access`), the magnitude, and the honest
  matching action ("expand existing capacity" / "add public/contracted-affordable
  capacity" / "operational + transport support"). Clicking a card flies to the
  district (white-glow boundary), drops an **indicative demand-center ghost marker**
  (dashed circle at the population-weighted centroid — *"not a site proposal"*), and
  **halos the relevant existing hospitals**.
- **Model tab — "settings → gap in four terms":** controls on top (Coverage
  Threshold, Capacity Benchmark, weight presets incl. a 4th `Capacity` preset,
  editable weight sliders behind a "Customize weights" expander, live
  priority-formula line); results below as 4 expandable cards:
  1. **Capacity** — beds short vs benchmark + # under-capacity districts.
  2. **Access** — exposed people & % beyond threshold (0 at 30 min).
  3. **Affordability** — # districts / people with **no public hospital**.
  4. **Overall priority** — districts by weighted AHP score; **all High districts
     listed, Medium & Low collapsible**. High/Med/Low counts shown.
  All gap math is **client-side** (`computeHospitalGaps()`) — no Python re-run.
- **Filters tab:** Hospital Ownership filter (Public / Private / Both); EMS-only map
  layers are hidden for hospitals (only District Boundaries & Population Heatmap).

### Phase 2 key findings
- **Capacity gaps:** Akkar (beds/1,000 ≈ 1.69), Baalbek (2.05), Minieh-Danieh, …
- **Affordability gaps (distinct from capacity):** **Metn (≈616k people, 0 public
  hospitals), Aley, Koura** — adequate beds & access but no affordable option.
  Separating the lenses is what makes the analysis honest and non-trivial.
- **Public vs private:** 28 public (~16%) vs 151 private — matches the literature
  (~88% private, ~10% of beds public).

---

## 5. Datasets at a glance

| File | What | Notes |
|---|---|---|
| `data/gadm41_LBN_2.json` | 26 district boundaries | GADM 4.1, admin level 2 |
| `data/lbn_pop_2024_CN_1km_R2025A_UA_v1.tif` | Population raster | WorldPop 2024, 1 km |
| `data/road_graph_lebanon.graphml` | Road network | OSM via OSMnx (cached, ~360 MB) |
| `data/EMS_Station_Locations.xlsx` | 52 EMS stations | Phase 1 supply layer |
| `data/lebanon_healthsites.geojson` | Raw hospital source | 1,356 facilities (HDX/OSM) |
| `data/lebanon_hospitals.csv` | **Final hospitals** | 179 · 96 real beds · 28 public / 151 private |
| `data/lebanon_hospitals.geojson` | Final hospital points for mapping | written by `enrich_hospital_beds.py` |
| `data/lebanon_hospitals_syndicate.csv` | Syndicate reference | 134 hospitals, real beds |
| `data/hospitals_manual_coords.csv` | Manual coordinates | all resolved |
| `data/phase1_ahp_dashboard.html` | **The built dashboard** | open this |
| `data/phase1_ahp_districts.json` | AHP sidecar | read by the Copilot |

---

## 6. What we did (timeline)

- **Phase 1 (EMS, done):** built the AHP engine, the EMS coverage analysis, the
  dashboard (map + Model/Analysis/Filters tabs), 32 suggested-station candidates, and
  the local EMS Copilot. Encoded Lebanese/IFRC response standards.
- **Phase 2 (Hospitals, `phase2-hospitals` branch):**
  - Built the hospital data pipeline (clean → scrape Syndicate → enrich beds &
    ownership) → 179 hospitals with real beds where available.
  - Generalized the AHP engine to `run_supply_analysis(...)` and added the **Dataset
    dropdown** (`setActiveDataset`), keeping EMS unchanged.
  - Added the **4th criterion** (Bed Capacity Gap), 30-min threshold, capacity
    benchmark, and the 3-lens equity diagnostic.
  - **Redesigned the Model tab** to "settings → gap in four terms"; **merged setup +
    weights** into one compact card with a live priority-formula line and editable
    sliders — and unified that compact design across EMS too.
  - Replaced the dead "Recommended New Stations" (for hospitals) with **Recommended
    Interventions** + indicative demand-center ghost markers + facility halos.
  - Added per-hospital `district` tags and per-district `demand_center`.
  - Fixed two dataset-switch bugs (the `escJs` hoist; restoring `ACTIVE_DATASET` to
    the dropdown's reloaded value).
- **June 14 polish (this session):**
  - Removed the stale "Requires re-run: grid heatmap layers & coverage polygon" note
    from the Model footer.
  - Made the **map legend dataset-aware** (Public/Private hospital vs EMS labels).
  - Changed **existing EMS markers from blue dots to red "+" badges** to match the
    legend.
  - **Overall-priority card** now lists **all** High districts and makes **Medium &
    Low clickable/expandable** (was capped at top 5).

---

## 7. How to run

```bash
# from the project root
PYTHONIOENCODING=utf-8 venv/bin/python scripts/phase1_ahp_explore.py   # build (~5 min, loads road graph)
open data/phase1_ahp_dashboard.html                                    # open the dashboard
```
Or one-click: `bash run_dashboard.sh` (Mac/Linux) / `run_dashboard.bat` (Windows) —
also starts the optional Copilot backend.

> Use the project **`venv`** (`venv/bin/python …`). Editing `templates/*` then
> rebuilding is the loop — gap math is client-side, so wording/logic tweaks need
> only a rebuild, not a data re-run.

**Optional EMS Copilot:** answers natural-language questions 100% locally via
[Ollama](https://ollama.com) (`qwen2.5:3b`); without it, it still works in
deterministic lookup/ranking mode. Reads `data/phase1_ahp_districts.json`.

---

## 8. Honest limitations & caveats

1. **83/179 hospital beds still estimated** — the open-data ceiling for small/obscure
   hospitals and 15 of 28 governmental hospitals.
2. **69/151 private ownerships are *inferred*** (defaulted to private). The **public**
   set (28) is tag-confirmed — and the affordability lens depends on that part.
3. **No operational-status data** (the biggest gap). The model counts every hospital
   as fully functioning, so it **misses the conflict-damaged South** (Nabatieh / Bint
   Jbeil look "Adequate" though MSF says they're hardest hit). Fix: integrate **WHO
   HeRAMS** (facility functional status) — not yet done.
4. **Bed imputation distorts a few rural districts** (e.g. Hermel shows "Adequate"
   partly from imputed beds + catchment effects).
5. **EMS:** Lebanon doesn't codify a spatial spacing rule — the 1.5 km / 5 km
   candidate thresholds are transparent demo heuristics. Travel time uses the OSM
   graph (no live traffic). The EMS station list is an operational snapshot.

**Attribution (required, ODbL):** Hospital locations — Global Healthsites Mapping
Project / OpenStreetMap via HDX. Bed counts — Syndicate of Hospitals in Lebanon.

---

*Authored by Rayan Hashem — Master's research on Lebanon's EMS & hospital coverage
gaps using the Analytic Hierarchy Process. See `PROJECT_NOTES.md` and
`PHASE2_NOTES.md` for full detail.*
