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
  have a hospital *shortage* (≈179 hospitals, ~10–15k beds, everyone within ~30 min).
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

### Final dataset — `data/lebanon_hospitals.csv` (179 hospitals)

| Column | Meaning |
|---|---|
| `name`, `lat`, `lon` | identity + location |
| `beds`, `beds_estimated` | bed count + real/imputed flag |
| `beds_source` | provenance: `osm-tag` / `syndicate-match` / `syndicate-arabic` / `syndicate-verified(...)` / `public-moph-locator` / `public-wikipedia` / `manual` / `median-estimate` |
| `hospital_type` | `public` / `private` |
| `ownership_source` | `tagged` (confirmed) / `inferred` (defaulted to private) |
| `operator`, `operator_type`, `osm_id`, `geom_type` | OSM metadata |

**Current numbers:** 179 hospitals · **96 real beds / 83 estimated** ·
**28 public / 151 private** (82 tagged, 69 inferred) · 0 unknown · 0 non-hospitals.
Public-hospital beds: **13 of 28 real** (5 large + 8 mid via MoPH locator), 15 imputed.

### How real beds were obtained (96 of 179)
- 3 from OSM `beds` tags
- 35 Latin-name fuzzy matches to the Syndicate (Jaccard ≥ 0.5, with a 3-pair
  blocklist of reviewed false positives)
- **39 Arabic-name matches** — every Arabic-only hospital name was read by hand and
  matched to the Syndicate list (e.g. أوتيل ديو→Hôtel-Dieu 430, الصليب للأمراض
  العقلية→Psychiatric Hosp. of the Cross 907). Stored in `ARABIC_BED_MATCHES`
  (keyed by `osm_id`). **All 39 spot-checked against the Syndicate (June 2026) —
  every bed count + region confirmed correct, no duplicates.**
- 5 hand-verified large hospitals (Dar Al-Ajaza 700, AUBMC 400, Dar Al-Amal 220,
  St George 210, Bahman 200), spatially merged onto existing OSM points.
- **13 public/governmental hospitals** — the Syndicate covers private hospitals only,
  so the 28 governmental hospitals were all median-imputed. Real beds now come from
  authoritative sources, in `PUBLIC_BED_MATCHES` (keyed by `osm_id`):
  - **RHUH 544** (`public-wikipedia`; nominal physical capacity — ~200 functional
    under the funding crisis, see caveat #3).
  - **12 via the MoPH Health Facility Locator** (`public-moph-locator`), each the full
    per-department total (medicine+surgery+BGYN+pediatrics+ICU/CCU): Saida 122,
    Nabatieh 100, Tripoli 78, Elias Hraoui/Zahle 59, Sibline 57, Dr Abdullah Al Rassi
    55, Hasbaya 55, Rachaya 44, Bouar (=Ftouh Keserwan) 39, Sir Denniye 38, Bcharreh
    32, Jezzine 20.
  - *How they were scraped (June 2026):* MoPH profile pages render the bed table only
    when fetched with the hospital's correct URL slug (an id-only fetch returns a
    generic page); the **slug** resolves the content, with `…/view/3/188/73034/<slug>?
    facility_type=1` as a working anchor. See the one-off harvest in `/tmp/moph_fix.py`
    logic — the bed numbers are pasted into `PUBLIC_BED_MATCHES` for reproducibility.
  - Metric note: moph-locator = MoPH-registered beds; RHUH = documented physical
    capacity (the two conventions differ — see caveats).
  - **15 still imputed:** Baabda, Baalbek, Bint Jbeil, Qana, Mays El Jabal, Ehden,
    Tannourine, Hermel, Minieh, Orange Nassau, Kartaba, Deir El Qamar, Karantina,
    Kherbet Kanafar, Military — verified to have **no populated MoPH bed page** (or
    not in MoPH's governmental list at all). This is the open-data ceiling.
- **Saideh Hospital (600 beds, Metn/Baabda)** — was missing from OSM; added via
  `hospitals_manual_coords.csv` with coordinates from OSM node 3707567031
  ("Al Saydeh Hospital", Antelias) at 33.910062, 35.587414.
- The remaining 83 are **median-imputed** and flagged `beds_estimated=True`.

### Companion data files
- `data/lebanon_hospitals_syndicate.csv` — 134-hospital Syndicate reference (real beds)
- `data/hospitals_manual_coords.csv` — template for famous hospitals needing
  coordinates (all now resolved: Cross/Hotel-Dieu/Hammoud via Arabic matches; Saideh
  600 via the row's filled-in lat/lon)
- `data/lebanon_hospitals.geojson` — the final points for mapping (179 features, full
  enriched properties). **Now written by `enrich_hospital_beds.py`** so it always
  matches the final CSV (previously written by `prepare_hospitals.py` from raw, so it
  lagged enrichment).

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
  - **Recommended Interventions** (June 2026 — replaces the EMS "Recommended New
    Stations" section for hospitals; spec:
    `docs/superpowers/specs/2026-06-12-hospital-interventions-design.md`). The honest
    counterpart of EMS "build-here" pins: one card per gap district (worst-first by
    live AHP score), tagged with gap chips (`capacity` / `no public` / `access`),
    the magnitude (beds short, people with no public hospital, minutes beyond
    threshold), and the matching action ("expand existing capacity" / "add
    public/contracted-affordable capacity" / "operational + transport support").
    Cards recompute live with the Model-tab benchmark/threshold (`computeInterventions()`).
    **Clicking a card** flies to the district (white-glow boundary) and drops an
    **indicative demand-center ghost marker** (dashed translucent circle at the
    population-weighted centroid of the district's WorldPop cells — labelled *"not a
    site proposal"*) plus **halos the relevant existing hospitals** (capacity gap →
    all, public emphasized; affordability-only gap → private hospitals as contracting
    candidates). Reset Map / dataset switch clears the ghost + halos.
- **Model** — *redesigned for hospitals* (June 2026, spec:
  `docs/superpowers/specs/2026-06-10-hospital-model-tab-design.md`). A **"settings →
  gap"** tab: controls on top, results below.
  - **Controls:** Coverage Threshold (default 30 min), **Capacity Benchmark** (default
    = national pop-weighted beds/1,000 ≈ 3.6, adjustable 1.0–6.0), Criterion-Weight
    presets (Balanced/Access/Population, incl. the 4th `bed_gap`), Reset to Defaults.
  - **Results — "the gap in four terms"** (4 expandable cards, each → worst districts,
    click a district to fly there + open its profile):
    1. **Capacity** — `beds short` vs benchmark + # under-capacity districts (driven by
       the benchmark control).
    2. **Access** — exposed people & % beyond the threshold (driven by the threshold).
       At 30 min this is **0** → shown as a green "✓ No access gap" honest state.
    3. **Affordability** — # districts (and people) with **no public hospital** (objective).
    4. **Overall priority** — districts ranked by the weighted AHP score + High/Med/Low
       counts (driven by the weights).
  - All client-side (no Python re-run). The old EMS "proposed stations" results are
    **only shown for EMS**; the hospital Model tab never shows build-here pins.
  - **Setup + weights merged into one compact card** (June 2026, spec:
    `docs/superpowers/specs/2026-06-12-hospital-setup-weights-merge-design.md`). The
    controls are one row per slider; below them an always-visible **priority-formula
    line** ("30% travel · 30% density · 25% exposure · 15% beds — `Balanced`") and a
    collapsed **"Customize weights"** expander (preset chips + 4 **editable** weight
    sliders). Moving a slider flips the chip to `Custom`; presets include a 4th
    **Capacity** scenario (`bed_gap` 0.50). **The same compact design now drives the
    EMS Model tab too** — both datasets share one render path (`renderModelTab`),
    EMS keeping its proposed-stations results + "requires re-run" footer.
- **Filters** — **Hospital Ownership** filter (Public / Private / Both) +
  Map Layers (EMS-only layers are hidden for hospitals; only District Boundaries
  & Population Heatmap remain).

### Analysis methodology (Python, `run_supply_analysis` + grid)
- The Phase-1 AHP engine was **generalized** (`run_supply_analysis(...)`) and runs
  once per dataset (EMS supply = stations; Hospital supply = hospitals).
- Hospital AHP criteria (4): Travel-Time Gap, Population Density, Exposed Population
  (30-min threshold), **Bed Capacity Gap** (inverse beds/1,000). Weights tunable live.
- **NEED classification** = beds/1,000 vs **national benchmark** (computed from data,
  currently ~3.6) + an access clause.
- **Gap math (Model tab)** lives client-side in `computeHospitalGaps()` in
  `templates/phase1_ahp_dashboard.js` — a pure read over the embedded per-district
  fields, recomputed whenever the user moves the threshold/benchmark/preset:
  - Capacity beds-short `= Σ over districts with beds_per_1000 < benchmark of
    (benchmark − beds_per_1000) × population / 1000`.
  - Access exposed `= Σ population where min_travel_time_min > threshold` (and % of total).
  - Affordability `= count / Σpopulation of districts with public_hospitals == 0`.
  - Overall priority `=` districts sorted by the live weighted `ahp_score`.
- **Hospital proposals** (the old grid/cluster "build-here" candidates) are **not used
  in the hospital view** — replaced by the gap-in-four-terms readout, which is the
  honest framing (Lebanon needs distribution/affordability, not new pins). The
  proposal code still exists for EMS only.

---

## 3. Key findings (for the write-up)

- **Validated vs MSF/AUB:** chronic-gap districts (Akkar, Hermel, Baalbek) match
  MSF's named regions → external validation of the method.
- **Capacity gaps:** Akkar (beds/1,000 ≈ 1.69), Baalbek (2.05), Minieh-Danieh, etc.
- **Affordability gaps (distinct from capacity):** **Metn (≈616k people, 0 public
  hospitals), Aley, Koura** — adequate beds, good access, but no affordable option.
  Separating the lenses is what makes this honest and non-trivial.
- **Public vs private:** 28 public (≈16%) vs 151 private — matches the literature
  (~28 public, ~88% private, ~10% of beds public).

---

## 4. Known limitations / honest caveats

1. **83/179 beds still estimated** — the small/obscure hospitals not in the
   Syndicate's 134, plus 15 of the 28 governmental hospitals (13 now have real beds).
   About as good as open data allows.
2. **69/151 private ownerships are *inferred*** (not tag-confirmed). The **public**
   set (28) is tag-confirmed and matches the literature — that's the part the
   affordability lens depends on.
3. **No operational-status data.** The biggest gap. The model counts every hospital
   as fully functioning, so it **misses the conflict-damaged South** (Nabatieh /
   Bint Jbeil come out "Adequate" though MSF says they're hardest hit). The fix is
   **WHO HeRAMS** (Health Resources & Services Availability Monitoring System),
   which tracks facility functional status — not yet integrated.
4. **Bed imputation distorts a few rural districts** (e.g. Hermel still shows
   "Adequate" partly due to imputed beds + catchment effects).
5. ~~1 famous hospital still lacks coordinates: Saideh (600 beds).~~ **Resolved**
   (June 2026) — added at 33.910062, 35.587414. No manual coordinates outstanding.

---

## 5. TODO / where to continue

**Working through the hospital tabs one by one** (current plan):
- [x] **Model tab** — *done* (June 2026). Redesigned to "settings → gap in four terms"
      (see §2 and the spec). Controls-first, results below; honest zero-states.
      **Then (June 12–13) merged setup + criterion weights into one compact card with
      a live priority-formula line and a "Customize weights" expander (editable sliders
      + a 4th `Capacity` preset), and unified that compact design across EMS too** —
      see §2 and `specs/2026-06-12-hospital-setup-weights-merge-design.md`.
- [x] **Analysis tab** — *done* (June 12–13). Replaced the dead "Recommended New
      Stations" section (hospitals have no proposed pins) with **Recommended
      Interventions** + indicative demand-center ghost markers + facility halos
      (see §2 and `specs/2026-06-12-hospital-interventions-design.md`).
- [ ] **Filters tab** — review the hospital ownership filter + which map layers show.
- [ ] **Dataset-aware legend** — top-left legend still shows EMS labels
      (High/Med/Low · Existing EMS · Proposed site); make it show
      "Public / Private hospital" + what the district colors mean for hospitals.
- [ ] **4th lens placeholder** — add a greyed-out "Operational status (HeRAMS —
      data needed)" column to acknowledge the conflict dimension.

**Data improvements (in priority order):**
- [ ] **Operational status (WHO HeRAMS)** — the highest-value addition; fixes the
      conflict-South blind spot.
- [~] **MoPH public-hospital beds** — *done to the open-data ceiling* (June 2026).
      The Open Data Lebanon 2021 Excel link is **dead** (GCS access-denied) and no
      MoPH bulletin PDF lists per-hospital beds. Instead, harvested **12 hospitals**
      from the MoPH Health Facility Locator (slug-resolved profile pages) + RHUH from
      Wikipedia → **13 of 28 public hospitals now real**. The other 15 have no
      populated MoPH bed page (verified) — closing them needs a non-open source
      (HeRAMS or a direct MoPH request).
- [x] ~~Resolve the last manual coordinate (Saideh).~~ Done — see §1.
- [ ] Optional: public-beds-per-capita affordability metric (we have ownership + beds).

**Housekeeping:**
- [~] `phase2-hospitals` pushed to GitHub (June 13). Merge → `main` still pending —
      open a PR when ready (`superpowers:finishing-a-development-branch`).
- [x] ~~Final quality pass on the Arabic matches.~~ Done (June 2026) — all 39
      cross-checked against the Syndicate; every bed count + region correct, no dupes.

### Session log — June 12–13, 2026 (Model-tab + Analysis-tab polish)
- **Model tab merged & unified.** Setup controls + criterion weights are now one
  compact card (one-row sliders, live priority-formula line, collapsed "Customize
  weights" with editable sliders + presets incl. a new `Capacity` preset). The same
  compact design now drives **both** EMS and hospitals via a single `renderModelTab`.
- **District click → white-glow boundary** (the selected polygon lights up; clears on
  Reset Map / timeout).
- **Analysis tab: Recommended Interventions** (replaces "Recommended New Stations" for
  hospitals) with indicative demand-center ghost markers + facility halos (see §2).
- **Data:** each hospital now carries its `district`; each district carries a
  `demand_center` (population-weighted WorldPop centroid). Written by
  `phase1_ahp_explore.py`; needs a rebuild only when raw data/scripts change.
- **Two bugs found & fixed** (root-caused with a node repro harness, not guessed):
  1. *Switching to Hospitals showed stale EMS data in the Model tab.* Cause:
     `renderInterventions` referenced `esc`, which was a **local** const inside
     `renderHospitalGapResults` → `ReferenceError` thrown inside `setActiveDataset`
     **before** `renderModelTab` ran, so the panel kept its EMS content. Fix: hoisted
     a module-level `escJs()` used by both.
  2. *Reload with Hospitals selected rendered EMS.* Browsers restore `<select>` state
     but `ACTIVE_DATASET` reset to `'ems'` with no change event. Fix: `initFilters`
     now syncs `ACTIVE_DATASET` to the dropdown's restored value on load.

> **Honest-framing caveat (for the write-up):** the demand-center ghost marker is an
> *indicative* population centroid, **not** a recommended build site, and the facility
> halos are existing hospitals (expansion/contracting candidates) — the hospital view
> deliberately proposes *no* new pins. This is the "distribution & affordability, not
> quantity" thesis rendered as UI. (See also: AHP priority tiers are quantile-based, so
> weights change the *ranking order*, not *how many* districts are flagged High.)

---

## 6. File map

```
scripts/
  prepare_hospitals.py        # clean raw -> hospital points (+ exclusions)
  scrape_syndicate_hospitals.py  # harvest Syndicate bed counts (one-off)
  enrich_hospital_beds.py     # real beds (Syndicate + Arabic + PUBLIC_BED_MATCHES) +
                              #   public/private classification; also writes final geojson
  phase1_ahp_explore.py       # builds the dashboard (EMS + hospitals)
templates/
  phase1_ahp_dashboard.html   # page skeleton (sentinels replaced at build)
  phase1_ahp_dashboard.css    # styles (incl. hospital markers / cards / gap cards)
  phase1_ahp_dashboard.js     # all client logic (dataset toggle, tabs, gap math)
data/
  lebanon_healthsites.geojson      # raw source (1,356 facilities)
  lebanon_hospitals.csv            # FINAL cleaned + enriched (179 hospitals, 96 real beds)
  lebanon_hospitals.geojson        # final points for mapping (written by enrich)
  lebanon_hospitals_syndicate.csv  # Syndicate reference (134, real beds)
  hospitals_manual_coords.csv      # manual coords (all resolved)
  phase1_ahp_dashboard.html        # the built dashboard (open this)
docs/superpowers/
  specs/2026-06-07-phase2-hospitals-integration-design.md
  specs/2026-06-10-hospital-model-tab-design.md          # Model tab "settings -> gap" design
  specs/2026-06-12-hospital-setup-weights-merge-design.md # merged setup+weights compact card
  specs/2026-06-12-hospital-interventions-design.md       # Recommended Interventions + ghost markers
  plans/2026-06-07-phase2-hospitals-integration.md
  plans/2026-06-12-hospital-setup-weights-merge.md
  plans/2026-06-12-hospital-interventions.md
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

> Env note: use the project **`venv`** (`venv/bin/python …`). A system/anaconda Python
> may have a broken `rasterio` import (missing `libpoppler`) and the build will exit
> with "rasterio is not installed".

> The Model-tab gap math is **client-side** (`computeHospitalGaps()` in the JS template),
> so tweaking the gap cards' wording/logic only needs a dashboard rebuild — no data
> re-run. Editing `templates/*` then `python scripts/phase1_ahp_explore.py` is the loop.

**Attribution (required, ODbL):** Hospital locations — Global Healthsites Mapping
Project / OpenStreetMap via HDX. Bed counts — Syndicate of Hospitals in Lebanon.
