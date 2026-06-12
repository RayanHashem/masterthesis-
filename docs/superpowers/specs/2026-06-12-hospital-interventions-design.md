# Hospital Analysis Tab — Recommended Interventions + Indicative Map Markers

**Date:** 2026-06-12
**Branch:** `phase2-hospitals`
**Scope:** Hospital Analysis tab only. EMS Analysis tab (incl. "Recommended New
Stations") is untouched.

## Problem

The Analysis tab's bottom section is a static HTML skeleton shared by both
datasets, so the hospital view inherits the EMS-only **"Recommended New
Stations"** header + Top-N dropdown and renders "No candidate stations
computed" (hospitals ship zero candidates by design). This is dead UI and
implies hospitals *should* have proposed sites — contradicting the thesis
(Lebanon needs distribution/affordability fixes, not new hospital pins).

## Design

### 1. Data additions (Python, `phase1_ahp_explore.py`)

- **`district` per hospital** — each record in `hospitals_supply` gains a
  `district` field via point-in-polygon against the same district frame used
  for the per-district `public_hospitals` / `total_hospitals` counts.
  Hospitals falling outside every polygon get `district: ''`.
- **`demand_center` per district** — each record in `hospital_districts_data`
  gains `demand_center: [lat, lon]`: the **population-weighted centroid** of
  WorldPop raster cells inside the district polygon (raster already loaded for
  the heatmap). Fallback if the raster mask is empty: district polygon
  centroid.

### 2. Dataset-aware bottom section (HTML skeleton + JS)

- The static skeleton's "Recommended New Stations" block (header, `
  #candidates-limit` select, `#candidates-list`) is wrapped so JS can swap its
  content per dataset:
  - **EMS:** exactly the current content and behavior (`renderCandidates()`).
  - **Hospitals:** header becomes **"Recommended Interventions"**; the same
    Top 5 / Top 10 / All dropdown; list rendered by a new
    `renderInterventions()`.
- `setActiveDataset()` triggers the swap (it already re-renders the Analysis
  tab content).

### 3. `computeInterventions()` (JS, client-side, pure read)

Per district, against the **live Model-tab settings** (`_getBenchmark()`,
`_getThreshold()`):

| Gap | Condition | Magnitude shown |
|---|---|---|
| `capacity` | `beds_per_1000 < benchmark` | beds short `= (benchmark − beds_per_1000) × population / 1000` |
| `no public` | `public_hospitals === 0` | district population affected |
| `access` | `min_travel_time_min > threshold` | district population beyond threshold |

- Districts with ≥ 1 gap, sorted worst-first by live `ahp_score`.
- Intervention text from a fixed mapping, combined when multiple gaps apply:
  - capacity → "Expand bed capacity at existing facilities"
  - no public → "Add public or contracted-affordable capacity"
  - access → "Operational / transport support"
- Card layout mirrors the EMS candidate cards (rank badge, gap chips,
  magnitude line, intervention line). Cards re-render when the benchmark or
  threshold sliders move (hook alongside the existing
  `recomputeAhpScores()`/`renderModelResults()` pipeline) and when the Top-N
  dropdown changes.
- Honest empty state: if no district has any gap, show "✓ No gaps at the
  current benchmark and threshold."

### 4. Map behavior on intervention-card click (option c)

Clicking a card calls the existing `onDistrictCardClick(district)` (fly-to +
white glow + profile card), **plus**:

- **Ghost demand-center marker** at `demand_center`: a dashed, translucent
  `L.circleMarker` (no fill or very low fill, dashed stroke) on the hospital
  top pane, with permanent tooltip *"Indicative demand center — not a site
  proposal"*. Only one ghost exists at a time; clicking another card moves it.
- **Facility highlight** — temporary halo (CSS class / box-shadow on
  `markerRef._icon`) on the district's relevant hospitals:
  - capacity gap → all hospitals in the district (public ones emphasized) —
    expansion candidates;
  - affordability gap (no public) → the district's **private** hospitals —
    contracting candidates;
  - both → all hospitals highlighted, public emphasized.
- **Clearing:** Reset Map, clicking a different card, or switching dataset
  removes the ghost and halos.

### 5. Unchanged

- EMS Analysis tab: candidate cards, placement-rule card, "Assess custom
  location", Top-N behavior.
- District Ranking table, summary cards, search/governorate filter.
- The 3-lens classification logic and the Model tab.

## Error handling / edge cases

- Hospital with no district match → excluded from facility highlights.
- District with `demand_center` missing/null → skip the ghost marker, still
  fly to the district.
- All weights/sliders interplay is read-only here — `computeInterventions()`
  never mutates district state.
- Dataset switch while a ghost is shown → ghost + halos removed in
  `setActiveDataset()`.

## Testing (manual, after rebuild)

1. Hospitals → Analysis: bottom section reads "Recommended Interventions";
   worst districts first (Akkar/Baalbek family at top); Metn present with
   "no public · 616k people".
2. Move Capacity Benchmark down to 1.0 → capacity cards shrink/disappear;
   raise to 6.0 → most districts appear. Threshold to 60 min → access chips
   vanish.
3. Click the Akkar card → map flies, white glow, ghost dashed circle at the
   populated plain (not the polygon centroid), halos on Akkar's hospitals.
4. Click Metn card → ghost moves, halos now on Metn's private hospitals only.
5. Reset Map → ghost + halos cleared.
6. EMS → Analysis: "Recommended New Stations" + candidate cards exactly as
   before.
