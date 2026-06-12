# Hospital Model Tab — "Settings → Gap" Design

> Date: 2026-06-10 · Branch: `phase2-hospitals` · Scope: **Hospitals view only**
> (the EMS Model tab is untouched). Step 1 of the per-tab hospital dashboard work.

## Goal

Turn the Hospitals **Model tab** into a place where the user (1) sets *how the system
works* via a few controls with sensible defaults, and (2) sees the resulting **gap
expressed in four terms**. Replaces the leftover EMS-style "proposed stations" results,
which don't fit the honest hospital thesis (Lebanon needs better *distribution /
affordability*, not "build-here" pins).

## Layout (top → bottom)

1. **Controls (Setup)** — first.
2. **Results (4 gap cards)** — below, driven by the controls.

(EMS keeps its current order/results; this layout applies only when
`ACTIVE_DATASET === 'hospitals'`.)

## Controls + default values (applied on load)

| Control | Default | Rationale |
|---|---|---|
| **Coverage threshold** (Access) | **30 min** | Reasonable "reach a hospital" target; already the project's hospital default. Slider 5–60, step 5. NOTE: Lebanon's longest district is ~21 min, so at 30 min the Access gap is **0** — shown as an honest "✓ No access gap" state (access isn't the problem; distribution/affordability are). Lower the slider (e.g. 15 min) to surface the chronic-gap regions. |
| **Capacity benchmark** (beds/1,000) | **national population-weighted average**, computed from the data and displayed as a number | Honest *distribution* lens — flags districts below the country's own average, matching the maldistribution thesis. Adjustable slider (range 1.0–6.0, step 0.1) so the user can test a target; default = the computed national average. |
| **Criterion weights** | **Balanced** preset | Neutral starting scenario. Existing preset buttons (Balanced / Access / Population), incl. the 4th `bed_gap` criterion. |

## The four gap cards

Each card = headline number + one plain-language sentence + expandable list of the
worst districts (click a district → existing district-profile behavior). National scope.

1. **Capacity (beds).**
   - Headline: `≈ N beds below benchmark · D districts under-capacity`.
   - `district_beds = beds_per_1000 × population / 1000`.
   - `shortfall = Σ over districts where beds_per_1000 < benchmark of (benchmark − beds_per_1000) × population / 1000`, rounded.
   - `D = count(beds_per_1000 < benchmark)` — **computed client-side against the current
     benchmark** (not the embedded `need_class`, which is tied to the Python-default
     benchmark), so the card stays correct when the benchmark slider moves.
   - Objective vs weights/threshold; **does** change with the benchmark control.

2. **Access (people).**
   - Headline: `≈ P people (X%) live >T min from a hospital · D districts poor access`.
   - `P = Σ exposed_population` (already recomputed client-side from the threshold).
   - `X% = P / Σ population`.
   - `D = count(access_class in {Fair, Poor})`.
   - Driven by the **threshold** control.

3. **Affordability (public).**
   - Headline: `D districts (≈ P people) have no public hospital`.
   - `D = count(public_hospitals == 0)`, `P = Σ population over those districts`.
   - Objective: independent of weights/threshold/benchmark.

4. **Overall priority.**
   - Headline: `Most under-served districts` + High/Med/Low counts.
   - Ranked by `ahp_score` (the weighted composite) descending; show top 5, expandable.
   - Driven by the **weights**.

## Live behavior

- Threshold change → recompute Access card (+ existing AHP exposed-pop criterion).
- Benchmark change → recompute Capacity card (shortfall + under-capacity count).
- Weights/preset change → recompute Overall priority card.
- Capacity & Affordability are objective and deliberately do **not** move with weights —
  surfaced as an honest teaching point (a one-line note), not a bug.
- Each card has a graceful **zero-state**: when its gap is 0 (e.g. Access at 30 min,
  or Affordability if all districts had a public hospital) it shows a green "✓ …"
  message instead of "0", so an empty gap reads as a finding, not a broken card.
- All client-side; **no Python re-run** needed (all required per-district fields are
  already embedded: `population`, `beds_per_1000`, `need_class`, `min_travel_time_min`,
  `exposed_population`, `public_hospitals`, `ahp_score`, `ahp_priority`, `access_class`,
  `afford_class`).

## Components touched (templates only; dashboard rebuilt via `phase1_ahp_explore.py`)

- `templates/phase1_ahp_dashboard.js`
  - `renderModelTab()` — branch on `ACTIVE_DATASET`: for hospitals, render controls-first
    + a benchmark control; for EMS, unchanged.
  - `renderModelResults()` — for hospitals, render the 4 gap cards; for EMS, unchanged
    (proposed-stations list).
  - New helpers: `computeHospitalGaps()` (pure function over `DISTRICTS` + current
    settings → the four metrics) and a benchmark getter with the computed default.
- `templates/phase1_ahp_dashboard.css` — styles for the gap cards (reuse existing
  `model-chip` / `model-results` patterns where possible).
- No data-pipeline or Python-analytics changes.

## Out of scope (later steps)

- Analysis / Filters / legend tabs (separate per-tab steps).
- HeRAMS 4th-lens placeholder.
- Editing individual criterion weights by hand (presets only, as today).

## Notes

- Per user instruction, **do not commit to git** until Phase 2 is complete (this spec
  is written but not committed).
