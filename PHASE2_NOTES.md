# Phase 2 — Hospitals Integration (Progress & Handoff)

> Working branch: **`phase2-hospitals`** (not yet merged to `main`).
> Phase 1 = EMS station siting (done). Phase 2 = add **hospitals** as a second
> dataset and analyse hospital-service equity in Lebanon.

---

## 0. The core idea (read this first)

EMS and hospitals are **different problems**, and that distinction *is* a finding:

- **EMS** is a **coverage / response-time** problem → "where should we *build* new
  stations" is a valid question. Phase 1 answers it.
- **Hospitals** are **destinations with capacity & economics**. Lebanon does **not**
  have a hospital *shortage* (≈178 hospitals, ~10–15k beds, everyone within ~30 min).
  The real problems are **maldistribution, affordability (88% private), and
  conflict damage** — i.e. *distribution*, not *quantity*.

**So the honest thesis conclusion for hospitals is: Lebanon does not broadly need
new hospitals; it needs better distribution / public (affordable) capacity /
operational support.** The dashboard is built to show *where* and *what kind* of
gap each district has — not to fake "build here" pins.

This was validated against external ground truth (MSF / AUB): the model's
chronic-gap districts (Akkar, Hermel, Baalbek) match MSF's named gap regions.

---

## 1. Data pipeline

### Sources
| Source | What | License |
|---|---|---|
| **Lebanon Healthsites** (Global Healthsites / OpenStreetMap, via HDX) | hospital **locations** | ODbL (attribution + share-alike) |
| **Syndicate of Hospitals in Lebanon** (`syndicateofhospitals.org.lb`) | real **bed counts** (134 private hospitals) | public directory, academic use |
| Manual / Wikidata | coordinates for a few famous hospitals | — |

### Scripts & rebuild order
Run in this order to rebuild the hospital dataset from scratch:

```
1. scripts/prepare_hospitals.py        # raw GeoJSON -> clean hospital points
2. scripts/scrape_syndicate_hospitals.py   # (one-off) harvest Syndicate bed counts
3. scripts/enrich_hospital_beds.py     # merge real beds + classify public/private
4. scripts/phase1_ahp_explore.py       # build the dashboard (EMS + hospitals)
```

- **`prepare_hospitals.py`** — filters raw → hospitals only; polygon→centroid;
  Lebanon bbox; dedupe by `osm_id`; **excludes** unnamed, pharmacies, Red-Cross
  branches, dispensaries (مستوصف), and a reviewed list of mis-tagged non-hospitals
  (`EXCLUDE_OSM_IDS`). Keeps the psychiatric "Hospital of the Cross".
- **`scrape_syndicate_hospitals.py`** — rate-limited scrape of the Syndicate's
  per-hospital pages → `data/lebanon_hospitals_syndicate.csv` (134 hospitals, all
  with real beds). One-off; output is committed.
- **`enrich_hospital_beds.py`** — the bed/ownership brain. Idempotent (re-derives
  from raw each run). Produces the final `data/lebanon_hospitals.csv`.

### Final dataset — `data/lebanon_hospitals.csv` (178 hospitals)

| Column | Meaning |
|---|---|
| `name`, `lat`, `lon` | identity + location |
| `beds`, `beds_estimated` | bed count + real/imputed flag |
| `beds_source` | provenance: `osm-tag` / `syndicate-match` / `syndicate-arabic` / `syndicate-verified(...)` / `median-estimate` |
| `hospital_type` | `public` / `private` |
| `ownership_source` | `tagged` (confirmed) / `inferred` (defaulted to private) |
| `operator`, `operator_type`, `osm_id`, `geom_type` | OSM metadata |

**Current numbers:** 178 hospitals · **82 real beds / 96 estimated** ·
**28 public / 150 private** (82 tagged, 68 inferred) · 0 unknown · 0 non-hospitals.

### How real beds were obtained (82 of 178)
- 3 from OSM `beds` tags
- 35 Latin-name fuzzy matches to the Syndicate (Jaccard ≥ 0.5, with a 3-pair
  blocklist of reviewed false positives)
- **39 Arabic-name matches** — every Arabic-only hospital name was read by hand and
  matched to the Syndicate list (e.g. أوتيل ديو→Hôtel-Dieu 430, الصليب للأمراض
  العقلية→Psychiatric Hosp. of the Cross 907). Stored in `ARABIC_BED_MATCHES`
  (keyed by `osm_id`).
- 5 hand-verified large hospitals (Dar Al-Ajaza 700, AUBMC 400, Dar Al-Amal 220,
  St George 210, Bahman 200), spatially merged onto existing OSM points.
- The remaining 96 are **median-imputed** and flagged `beds_estimated=True`.

### Companion data files
- `data/lebanon_hospitals_syndicate.csv` — 134-hospital Syndicate reference (real beds)
- `data/hospitals_manual_coords.csv` — template for famous hospitals still needing
  coordinates (mostly resolved now via Arabic matches; Saideh 600 still pending)
- `data/lebanon_hospitals.geojson` — the points for mapping

---

## 2. Dashboard

Single self-contained file: `data/phase1_ahp_dashboard.html` (built by
`phase1_ahp_explore.py` from the `templates/` files). Open it directly in a browser.

### Dataset selector
A **Dataset** dropdown (panel header) switches between **EMS Stations** and
**Hospitals**. Everything re-renders client-side via `setActiveDataset()` in
`templates/phase1_ahp_dashboard.js`. Both result sets are embedded as a `DATASETS`
JS object built in Python. **EMS view is unchanged from Phase 1** (verified at
every step against a regression baseline).

### Hospital map
- **"H" badge markers** colored by ownership: 🔵 public (larger/bolder) · 🔴 private.
  Rendered on a dedicated top pane so they sit above the heatmap/choropleth.
- **Click a hospital** → bottom-left **detail card** (status, beds, location, operator).
- District polygons recolored by the **hospital** AHP priority.

### Hospital tabs
- **Analysis** — *3-lens equity diagnostic* (the main deliverable). District table
  graded on **Capacity** (beds/1,000 vs national benchmark → NEED/Adequate/No-need),
  **Access** (travel time → Good/Fair/Poor), **Affordability** (has a public
  hospital? → Public ✓ / No public). Worst-served first; click a row for the full
  district profile. Summary cards: Hospitals / Public Hospitals / Need Capacity /
  No Public Hospital.
- **Model** — coverage threshold (default 30 min) + dataset-aware weight presets
  (Balanced/Access/Population, including the 4th `bed_gap` criterion) + live
  recompute + hospital **proposals** (see below).
- **Filters** — **Hospital Ownership** filter (Public / Private / Both) +
  Map Layers (EMS-only layers are hidden for hospitals; only District Boundaries
  & Population Heatmap remain).

### Analysis methodology (Python, `run_supply_analysis` + grid)
- The Phase-1 AHP engine was **generalized** (`run_supply_analysis(...)`) and runs
  once per dataset (EMS supply = stations; Hospital supply = hospitals).
- Hospital AHP criteria (4): Travel-Time Gap, Population Density, Exposed Population
  (30-min threshold), **Bed Capacity Gap** (inverse beds/1,000). Weights tunable live.
- **NEED classification** = beds/1,000 vs **national benchmark** (computed from data,
  currently ~3.54) + an access clause.
- **Hospital proposals** = grid cells under-served (>15 min from a hospital) in the
  top score tier, clustered, **filtered to serve ≥5,000 people**. ~11–12 proposals
  that vary by preset and land in genuinely under-served regions. (Honest framing:
  these answer "where are meaningful populations far from a hospital", i.e. an
  *access-gap* lens — they complement, not replace, the capacity/affordability view.)

---

## 3. Key findings (for the write-up)

- **Validated vs MSF/AUB:** chronic-gap districts (Akkar, Hermel, Baalbek) match
  MSF's named regions → external validation of the method.
- **Capacity gaps:** Akkar (beds/1,000 ≈ 1.69), Baalbek (2.05), Minieh-Danieh, etc.
- **Affordability gaps (distinct from capacity):** **Metn (≈616k people, 0 public
  hospitals), Aley, Koura** — adequate beds, good access, but no affordable option.
  Separating the lenses is what makes this honest and non-trivial.
- **Public vs private:** 28 public (≈16%) vs 150 private — matches the literature
  (~28 public, ~88% private, ~10% of beds public).

---

## 4. Known limitations / honest caveats

1. **96/178 beds still estimated** — the small/obscure hospitals not in the
   Syndicate's 134. About as good as open data allows.
2. **68/150 private ownerships are *inferred*** (not tag-confirmed). The **public**
   set (28) is tag-confirmed and matches the literature — that's the part the
   affordability lens depends on.
3. **No operational-status data.** The biggest gap. The model counts every hospital
   as fully functioning, so it **misses the conflict-damaged South** (Nabatieh /
   Bint Jbeil come out "Adequate" though MSF says they're hardest hit). The fix is
   **WHO HeRAMS** (Health Resources & Services Availability Monitoring System),
   which tracks facility functional status — not yet integrated.
4. **Bed imputation distorts a few rural districts** (e.g. Hermel still shows
   "Adequate" partly due to imputed beds + catchment effects).
5. **1 famous hospital still lacks coordinates:** Saideh (600 beds). Paste lat/lon
   into `data/hospitals_manual_coords.csv` and re-run enrich + pipeline.

---

## 5. TODO / where to continue

**Open product decisions / next features:**
- [ ] **Model tab** for hospitals — decide its purpose (currently threshold +
      presets + proposals; may want to simplify/relabel for hospitals).
- [ ] **Dataset-aware legend** — top-left legend still shows EMS labels
      (High/Med/Low · Existing EMS · Proposed site); make it show
      "Public / Private hospital · Proposed location" for hospitals.
- [ ] **4th lens placeholder** — add a greyed-out "Operational status (HeRAMS —
      data needed)" column to acknowledge the conflict dimension.

**Data improvements (in priority order):**
- [ ] **Operational status (WHO HeRAMS)** — the highest-value addition; fixes the
      conflict-South blind spot.
- [ ] **MoPH public-hospital beds** — confirm/fill public bed counts (Open Data
      Lebanon has a 2021 MoPH public-hospital Excel).
- [ ] Resolve the last manual coordinate (Saideh).
- [ ] Optional: public-beds-per-capita affordability metric (we have ownership + beds).

**Housekeeping:**
- [ ] Merge `phase2-hospitals` → `main` when ready (use
      `superpowers:finishing-a-development-branch` or a normal PR).
- [ ] Final quality pass on the Arabic matches (spot-check, confirm no duplicates).

---

## 6. File map

```
scripts/
  prepare_hospitals.py        # clean raw -> hospital points (+ exclusions)
  scrape_syndicate_hospitals.py  # harvest Syndicate bed counts (one-off)
  enrich_hospital_beds.py     # real beds + public/private classification
  phase1_ahp_explore.py       # builds the dashboard (EMS + hospitals)
templates/
  phase1_ahp_dashboard.html   # page skeleton (sentinels replaced at build)
  phase1_ahp_dashboard.css    # styles (incl. hospital markers / cards / badges)
  phase1_ahp_dashboard.js     # all client logic (dataset toggle, tabs, markers)
data/
  lebanon_healthsites.geojson      # raw source (1,356 facilities)
  lebanon_hospitals.csv            # FINAL cleaned + enriched (178 hospitals)
  lebanon_hospitals.geojson        # final points for mapping
  lebanon_hospitals_syndicate.csv  # Syndicate reference (134, real beds)
  hospitals_manual_coords.csv      # manual coords (Saideh pending)
  phase1_ahp_dashboard.html        # the built dashboard (open this)
docs/superpowers/
  specs/2026-06-07-phase2-hospitals-integration-design.md
  plans/2026-06-07-phase2-hospitals-integration.md
PROJECT_NOTES.md                   # overall project (Phase 1 + Phase 2 section)
PHASE2_NOTES.md                    # this file
```

## 7. Rebuild / run cheatsheet

```bash
source venv/bin/activate
# Full hospital data rebuild (only needed if raw data or scripts change):
python scripts/prepare_hospitals.py
# python scripts/scrape_syndicate_hospitals.py   # one-off, already committed
python scripts/enrich_hospital_beds.py
# Build the dashboard (loads a 360 MB road graph — takes ~5 min):
python scripts/phase1_ahp_explore.py
open data/phase1_ahp_dashboard.html
```

**Attribution (required, ODbL):** Hospital locations — Global Healthsites Mapping
Project / OpenStreetMap via HDX. Bed counts — Syndicate of Hospitals in Lebanon.
