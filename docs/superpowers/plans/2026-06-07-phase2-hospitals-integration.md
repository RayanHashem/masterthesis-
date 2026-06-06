# Phase 2 — Hospital Dataset Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Lebanon hospitals as a second selectable dataset in the dashboard, running the full AHP analysis with hospitals as the supply layer, toggled by a dropdown.

**Architecture:** Refactor the supply-dependent stages of `scripts/phase1_ahp_explore.py` into one reusable function that takes a set of supply points + config and returns a complete result set. Call it twice (EMS, Hospitals). Embed both result sets into the HTML as a `DATASETS` object; a JS controller rebinds the active dataset and re-renders all panels and map layers client-side — reusing the existing client-side layer pattern (`initCandidatesLayer`).

**Tech Stack:** Python (geopandas, networkx, osmnx, rasterio, folium, pandas), vanilla JS + Leaflet, HTML/CSS templates.

**Testing note:** This repo has no test framework and the pipeline is heavy (360 MB graphml). Validation is done via *runnable gates*: the data-prep script carries real `assert` checks; the pipeline refactor is verified by diffing the EMS result set against a captured baseline; the dashboard is verified by a manual toggle checklist. Commit after every task.

---

## File Structure

**Create:**
- `scripts/prepare_hospitals.py` — cleans `lebanon_healthsites.geojson` → `lebanon_hospitals.csv` + `.geojson`. One job: data prep.
- `data/lebanon_hospitals.csv`, `data/lebanon_hospitals.geojson` — generated artifacts.
- `data/_baseline_ems_districts.json` — temporary EMS regression baseline (deleted in final task).

**Modify:**
- `scripts/phase1_ahp_explore.py` — extract supply-parameterized analysis function; run for EMS + Hospitals; build `DATASETS`.
- `templates/phase1_ahp_dashboard.js` — dataset-switch controller; rebind globals; client-side supply markers.
- `templates/phase1_ahp_dashboard.html` — dataset dropdown in panel header.
- `templates/phase1_ahp_dashboard.css` — dropdown styling.

---

## Task 1: Hospital data-prep script

**Files:**
- Create: `scripts/prepare_hospitals.py`
- Output: `data/lebanon_hospitals.csv`, `data/lebanon_hospitals.geojson`

- [ ] **Step 1: Write the prep script with built-in assertions**

Create `scripts/prepare_hospitals.py`:

```python
"""Phase 2 — Clean raw Healthsites GeoJSON into a project-scoped hospitals dataset.

Input:  data/lebanon_healthsites.geojson  (Global Healthsites, HDX, ODbL)
Output: data/lebanon_hospitals.csv  and  data/lebanon_hospitals.geojson
"""
import json
import os
import statistics

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), 'data')
SRC = os.path.join(DATA_DIR, 'lebanon_healthsites.geojson')
OUT_CSV = os.path.join(DATA_DIR, 'lebanon_hospitals.csv')
OUT_GEOJSON = os.path.join(DATA_DIR, 'lebanon_hospitals.geojson')

# Lebanon bounding box (lon_min, lon_max, lat_min, lat_max)
BBOX = (35.0, 37.0, 33.0, 34.8)


def centroid(geom):
    t = geom['type']
    c = geom['coordinates']
    if t == 'Point':
        return c[0], c[1]
    if t == 'Polygon':
        ring = c[0]
    elif t == 'MultiPolygon':
        ring = c[0][0]
    elif t == 'LineString':
        ring = c
    elif t == 'MultiLineString':
        ring = c[0]
    else:
        return None
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def parse_beds(val):
    try:
        return int(float(str(val).split(';')[0].strip()))
    except (ValueError, AttributeError, TypeError):
        return None


def main():
    with open(SRC, encoding='utf-8') as f:
        gj = json.load(f)

    rows = []
    for feat in gj['features']:
        p = feat.get('properties', {}) or {}
        if p.get('amenity') != 'hospital' and p.get('healthcare') != 'hospital':
            continue
        g = feat.get('geometry')
        if not g:
            continue
        cc = centroid(g)
        if not cc:
            continue
        lon, lat = cc
        if not (BBOX[0] <= lon <= BBOX[1] and BBOX[2] <= lat <= BBOX[3]):
            continue
        rows.append({
            'name': (p.get('name:en') or p.get('name') or '').strip(),
            'lat': round(lat, 6),
            'lon': round(lon, 6),
            'beds_raw': parse_beds(p.get('beds')),
            'operator': (p.get('operator') or '').strip(),
            'operator_type': (p.get('operator_type') or '').strip(),
            'osm_id': str(p.get('osm_id') or ''),
            'geom_type': g['type'],
        })

    # Dedupe by osm_id (keep first)
    seen = set()
    deduped = []
    for r in rows:
        key = r['osm_id'] or f"{r['lat']},{r['lon']}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    rows = deduped

    # Median imputation for missing beds, flagged
    known = [r['beds_raw'] for r in rows if r['beds_raw'] is not None]
    median_beds = int(statistics.median(known)) if known else 0
    for r in rows:
        if r['beds_raw'] is None:
            r['beds'] = median_beds
            r['beds_estimated'] = True
        else:
            r['beds'] = r['beds_raw']
            r['beds_estimated'] = False
        del r['beds_raw']

    # --- Assertions (validation gate) ---
    assert len(rows) > 100, f"Expected >100 hospitals, got {len(rows)}"
    for r in rows:
        assert isinstance(r['lat'], float) and isinstance(r['lon'], float)
        assert BBOX[2] <= r['lat'] <= BBOX[3], f"lat out of bbox: {r}"
        assert BBOX[0] <= r['lon'] <= BBOX[1], f"lon out of bbox: {r}"
        assert isinstance(r['beds'], int)
        assert isinstance(r['beds_estimated'], bool)
    assert len({r['osm_id'] for r in rows if r['osm_id']}) == \
        len([r for r in rows if r['osm_id']]), "duplicate osm_id remains"

    # --- Write CSV ---
    import csv
    fields = ['name', 'lat', 'lon', 'beds', 'beds_estimated',
              'operator', 'operator_type', 'osm_id', 'geom_type']
    with open(OUT_CSV, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    # --- Write GeoJSON (points only) ---
    out_features = [{
        'type': 'Feature',
        'geometry': {'type': 'Point', 'coordinates': [r['lon'], r['lat']]},
        'properties': {k: r[k] for k in fields if k not in ('lat', 'lon')},
    } for r in rows]
    with open(OUT_GEOJSON, 'w', encoding='utf-8') as fh:
        json.dump({'type': 'FeatureCollection', 'features': out_features}, fh)

    est = sum(1 for r in rows if r['beds_estimated'])
    print(f"OK: {len(rows)} hospitals  | beds known: {len(rows) - est}  "
          f"estimated: {est}  median_beds: {median_beds}")
    print(f"Wrote {OUT_CSV}")
    print(f"Wrote {OUT_GEOJSON}")


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Run it (validation gate)**

Run: `cd "/Users/apple/Desktop/EMS project" && source venv/bin/activate && python scripts/prepare_hospitals.py`
Expected: prints `OK: 201 hospitals ...` (count may vary slightly if source updated), no AssertionError, both files written.

- [ ] **Step 3: Spot-check the CSV**

Run: `python -c "import csv; rows=list(csv.DictReader(open('data/lebanon_hospitals.csv'))); print(len(rows)); print(rows[0]); print('estimated:', sum(r['beds_estimated']=='True' for r in rows))"`
Expected: row count matches, first row has name/lat/lon/beds/beds_estimated keys.

- [ ] **Step 4: Commit**

```bash
git add scripts/prepare_hospitals.py data/lebanon_hospitals.csv data/lebanon_hospitals.geojson
git commit -m "feat: hospital data-prep script with median bed imputation"
```

---

## Task 2: Capture EMS regression baseline

The refactor in Tasks 3–4 must not change EMS results. Capture the current EMS district scores as a baseline to diff against.

**Files:**
- Output: `data/_baseline_ems_districts.json` (temporary)

- [ ] **Step 1: Run the current pipeline to (re)generate the EMS sidecar**

Run: `cd "/Users/apple/Desktop/EMS project" && source venv/bin/activate && python scripts/phase1_ahp_explore.py`
Expected: completes, writes `data/phase1_ahp_districts.json` and `data/phase1_ahp_dashboard.html`.

- [ ] **Step 2: Snapshot the sidecar as baseline**

Run: `cp data/phase1_ahp_districts.json data/_baseline_ems_districts.json && wc -c data/_baseline_ems_districts.json`
Expected: a non-empty file is copied.

- [ ] **Step 3: Commit the baseline (temporary)**

```bash
git add data/_baseline_ems_districts.json
git commit -m "chore: capture EMS AHP baseline for Phase 2 regression check"
```

---

## Task 3: Extract supply-parameterized analysis function (EMS path unchanged)

Refactor sections **5d (travel time/coverage)** and **5e (AHP scoring)** of `scripts/phase1_ahp_explore.py` into a function `run_supply_analysis(...)`. First call it once for EMS and confirm identical output to the baseline. Do **not** touch criteria yet (still 3 EMS criteria).

**Files:**
- Modify: `scripts/phase1_ahp_explore.py` (sections 5d–5e, ~lines 364–541)

- [ ] **Step 1: Define the function**

Insert a new function just above section 5d (after the road-graph load, ~line 364). It encapsulates the existing 5d + 5e logic, parameterized by supply points, coverage threshold, and AHP weights. Use the *exact* existing computation — copy the bodies verbatim, replacing `ems_valid[lon_col]/[lat_col]` with the passed `supply_lons/supply_lats`, the literal `10`/`600` coverage threshold with `threshold_min`/`threshold_min*60`, and the weights `W_C1,W_C2,W_C3` with passed weights.

```python
def run_supply_analysis(districts, G, best_time_lookup_graph, supply_lons, supply_lats,
                        threshold_min, weights, criteria_config):
    """Run travel-time coverage + AHP scoring for one supply layer.

    Returns a dict with: districts (a copy with min_travel_time_min, covered,
    norm_* and ahp_score/priority columns), coverage_gdf, best_time_s.
    `weights` is (w_c1, w_c2, w_c3[, w_c4]); `criteria_config` is the list of
    criterion dicts to embed for this dataset.
    """
    d = districts.copy()
    # ---- (5d body: snap supply nodes, multi_source_dijkstra, per-district
    #       min_travel_time_min + covered flag, coverage polygon) ----
    #   * replace station_lons/station_lats with supply_lons/supply_lats
    #   * replace `<= 10` with `<= threshold_min`
    #   * replace `t <= 600` with `t <= threshold_min * 60`
    #   * write d['min_travel_time_min'], d['covered'] (renamed from covered_10min)
    # ---- (5e body: area_km2, _c1_raw, pop_density, exposed_population using
    #       d['covered'], minmax_normalize, weighted ahp_score, quantile labels) ----
    #   * use weights[0],weights[1],weights[2] instead of W_C1,W_C2,W_C3
    return {'districts': d, 'coverage_gdf': coverage_gdf, 'best_time_s': best_time_s}
```

> Note: rename the column `covered_10min` → `covered` inside the function so it
> is threshold-agnostic. Update the two downstream readers (grid section 5g and
> analytics section 7) to use `covered` in Step 3.

- [ ] **Step 2: Call it once for EMS, replacing the inline 5d/5e blocks**

Where sections 5d/5e used to run inline, replace with:

```python
EMS_WEIGHTS = (0.5, 0.3, 0.2)
EMS_THRESHOLD_MIN = 10
ems_result = run_supply_analysis(
    districts_agg, G, G,
    ems_valid[lon_col].values, ems_valid[lat_col].values,
    EMS_THRESHOLD_MIN, EMS_WEIGHTS, CRITERIA_CONFIG,
)
districts_agg = ems_result['districts']
coverage_gdf = ems_result['coverage_gdf']
best_time_s = ems_result['best_time_s']
```

Keep `CRITERIA_CONFIG` and `DEFAULT_COVERAGE_THRESHOLD_MIN` defined before this call (move their definitions above if needed).

- [ ] **Step 3: Fix the two downstream readers of the renamed column**

In section 5g (~line 626) and section 7 (~line 1254), replace `covered_10min` with `covered`:
- `grid_cells_gdf` uses its own coverage column — leave grid columns as-is; only change references to `districts_agg['covered_10min']`.
- Section 7: `uncovered_mask = districts_agg['covered'] == False`.

Run: `grep -n "covered_10min" scripts/phase1_ahp_explore.py`
Expected: only grid-cell references remain (grid keeps its own name); no `districts_agg['covered_10min']` left.

- [ ] **Step 4: Run the pipeline (validation gate)**

Run: `python scripts/phase1_ahp_explore.py`
Expected: completes without error; prints AHP High/Medium/Low counts.

- [ ] **Step 5: Diff EMS results against baseline**

Run:
```bash
python -c "
import json
a=json.load(open('data/_baseline_ems_districts.json'))
b=json.load(open('data/phase1_ahp_districts.json'))
ka={d['district_name']:round(d['ahp_score'],3) for d in a}
kb={d['district_name']:round(d['ahp_score'],3) for d in b}
diffs={k:(ka[k],kb.get(k)) for k in ka if ka[k]!=kb.get(k)}
print('DISTRICTS:',len(a),len(b),'| score diffs:',diffs)
assert not diffs, diffs
print('EMS UNCHANGED ✓')
"
```
Expected: `EMS UNCHANGED ✓` (no score diffs). If diffs appear, the refactor altered behavior — fix before continuing.

- [ ] **Step 6: Commit**

```bash
git add scripts/phase1_ahp_explore.py
git commit -m "refactor: extract run_supply_analysis; EMS results unchanged"
```

---

## Task 4: Add bed-capacity criterion (C4) to the analysis function

Extend `run_supply_analysis` to optionally compute a 4th criterion — beds per 1,000 population per district (cost: fewer beds = higher priority). Gated so the EMS call (3 weights, no beds) is unaffected.

**Files:**
- Modify: `scripts/phase1_ahp_explore.py` (`run_supply_analysis`)

- [ ] **Step 1: Add an optional `supply_beds` parameter and C4 computation**

Change the signature to accept supply point bed counts and district names for aggregation:

```python
def run_supply_analysis(districts, G, _g2, supply_lons, supply_lats,
                        threshold_min, weights, criteria_config,
                        supply_beds=None):
```

Inside, after the 3 existing normalized criteria, add (only when `supply_beds is not None` and `len(weights) == 4`):

```python
    if supply_beds is not None and len(weights) == 4:
        from shapely.geometry import Point as _P
        import geopandas as _gpd
        supply_pts = _gpd.GeoDataFrame(
            {'beds': supply_beds},
            geometry=[_P(lo, la) for lo, la in zip(supply_lons, supply_lats)],
            crs='EPSG:4326')
        if supply_pts.crs != d.crs:
            supply_pts = supply_pts.to_crs(d.crs)
        joined = _gpd.sjoin(supply_pts, d.reset_index(), how='left', predicate='within')
        beds_by_dist = joined.groupby('index_right')['beds'].sum()
        d['_beds_total'] = d.index.map(beds_by_dist).fillna(0.0)
        d['beds_per_1000'] = d.apply(
            lambda r: (r['_beds_total'] / (r['population'] / 1000.0))
            if r['population'] > 0 else 0.0, axis=1)
        # Cost criterion: fewer beds per capita = higher priority -> invert
        d['norm_bed_gap'] = 1.0 - minmax_normalize(d['beds_per_1000'])
        raw = (weights[0]*d['norm_access_gap'] + weights[1]*d['norm_pop_density']
               + weights[2]*d['norm_exposed_pop'] + weights[3]*d['norm_bed_gap'])
    else:
        raw = (weights[0]*d['norm_access_gap'] + weights[1]*d['norm_pop_density']
               + weights[2]*d['norm_exposed_pop'])
    d['ahp_score'] = raw.round(3)
```

Use `raw` for the quantile priority labels (replace the previous `_district_raw_score`).

- [ ] **Step 2: Re-run pipeline; confirm EMS still unchanged**

Run: `python scripts/phase1_ahp_explore.py` then re-run the Task 3 Step 5 diff command.
Expected: `EMS UNCHANGED ✓` (EMS passes `weights` of length 3 and `supply_beds=None`, so the `else` branch runs).

- [ ] **Step 3: Commit**

```bash
git add scripts/phase1_ahp_explore.py
git commit -m "feat: optional bed-capacity criterion (C4) in run_supply_analysis"
```

---

## Task 5: Run hospital analysis and build the DATASETS object

Load hospitals, run the analysis for them, and assemble both EMS and Hospital result sets into a single `DATASETS` JS object. Each dataset carries: `districts`, `supply` points, `criteria`, `stats`, `proposals`, `threshold`, `weights`, `label`, `supplyLabel`, `supplyIcon`.

**Files:**
- Modify: `scripts/phase1_ahp_explore.py` (after Task 4; section 8 data assembly)

- [ ] **Step 1: Load hospitals after EMS load**

After the EMS station load (section 2), add:

```python
HOSPITALS_FILE = os.path.join(DATA_DIR, 'lebanon_hospitals.csv')
hospitals_df = pd.read_csv(HOSPITALS_FILE)
hospitals_gdf = gpd.GeoDataFrame(
    hospitals_df,
    geometry=gpd.points_from_xy(hospitals_df['lon'], hospitals_df['lat']),
    crs='EPSG:4326')
print(f"✓ Loaded {len(hospitals_gdf)} hospitals")
```

- [ ] **Step 2: Define hospital config and run the analysis**

After the EMS `run_supply_analysis` call, add:

```python
HOSPITAL_WEIGHTS = (0.30, 0.30, 0.25, 0.15)
HOSPITAL_THRESHOLD_MIN = 30
HOSPITAL_CRITERIA_CONFIG = [
    {'id': 'access_gap', 'label': 'Travel Time Gap',
     'description': 'Min. road travel time to nearest hospital (higher = worse)',
     'weight': 0.30, 'norm_key': 'norm_access_gap'},
    {'id': 'pop_density', 'label': 'Population Density',
     'description': 'Population per km² in the district',
     'weight': 0.30, 'norm_key': 'norm_pop_density'},
    {'id': 'exposed_pop', 'label': 'Exposed Population',
     'description': 'Population outside the coverage threshold (recalculated live)',
     'weight': 0.25, 'norm_key': 'norm_exposed_pop', 'dynamic': True},
    {'id': 'bed_gap', 'label': 'Bed Capacity Gap',
     'description': 'Inverse of hospital beds per 1,000 population (fewer beds = higher need)',
     'weight': 0.15, 'norm_key': 'norm_bed_gap'},
]
hosp_result = run_supply_analysis(
    districts_agg, G, G,
    hospitals_gdf['lon'].values, hospitals_gdf['lat'].values,
    HOSPITAL_THRESHOLD_MIN, HOSPITAL_WEIGHTS, HOSPITAL_CRITERIA_CONFIG,
    supply_beds=hospitals_gdf['beds'].values,
)
hosp_districts = hosp_result['districts']
```

> Note: `run_supply_analysis` copies `districts`, so the EMS and hospital runs do
> not interfere. Run EMS first (it sets `districts_agg` used downstream for the
> grid/EMS proposals), then run hospitals into a separate `hosp_districts`.

- [ ] **Step 3: Build a districts-data builder reused by both datasets**

Refactor the inline `districts_data` loop (section 8) into a function so both datasets serialize the same way:

```python
def build_districts_data(d):
    out = []
    for _, row in d.iterrows():
        tt = row.get('min_travel_time_min', None)
        rec = {
            'district_name': str(row.get('NAME_2', 'Unknown')),
            'governorate': str(row.get('NAME_1', 'Unknown')),
            'population': float(row.get('population', 0)),
            'area_km2': round(float(row.get('area_km2', 0)), 2),
            'pop_density': round(float(row.get('pop_density', 0)), 2),
            'exposed_population': float(row.get('exposed_population', 0)),
            'ahp_score': float(row.get('ahp_score', 0)),
            'ahp_priority': str(row.get('ahp_priority', 'Low')),
            'min_travel_time_min': round(float(tt), 2) if tt is not None and not pd.isna(tt) else None,
            'norm_access_gap': round(float(row.get('norm_access_gap', 0)), 4),
            'norm_pop_density': round(float(row.get('norm_pop_density', 0)), 4),
            'norm_exposed_pop': round(float(row.get('norm_exposed_pop', 0)), 4),
        }
        if 'norm_bed_gap' in d.columns:
            rec['norm_bed_gap'] = round(float(row.get('norm_bed_gap', 0)), 4)
            rec['beds_per_1000'] = round(float(row.get('beds_per_1000', 0)), 2)
        out.append(rec)
    return out
```

Use `build_districts_data(districts_agg)` for EMS (keep the existing `stations`/`ems_stations` field by adding `'stations': int(row.get('ems_stations', 0))` in the EMS path — pass a flag or post-add it) and `build_districts_data(hosp_districts)` for hospitals.

- [ ] **Step 4: Build the supply-points arrays for both datasets**

EMS reuses the existing `stations_data`. Add a hospitals supply array:

```python
hospitals_supply = []
for _, r in hospitals_df.iterrows():
    hospitals_supply.append({
        'lat': float(r['lat']), 'lon': float(r['lon']),
        'name': str(r['name']) if str(r['name']) else 'Unnamed hospital',
        'beds': int(r['beds']), 'beds_estimated': bool(r['beds_estimated']),
        'operator': str(r.get('operator', '') or ''),
    })
```

- [ ] **Step 5: Assemble the DATASETS object and inject it**

Replace the individual `DISTRICTS`/`STATIONS`/`CRITERIA_CONFIG` constants in `js_data` with a `DATASETS` object plus an active key. Keep `GOVERNORATES`, `MAX_POP`, `LEBANON_BOUNDS`, and `CANDIDATES_BY_PRESET`/`CANDIDATES` (EMS proposals) as-is for now (hospital proposals added in Step 6).

```python
datasets_obj = {
    'ems': {
        'label': 'EMS Stations',
        'supplyLabel': 'EMS Stations',
        'supplyIcon': 'ambulance',
        'threshold': EMS_THRESHOLD_MIN,
        'criteria': CRITERIA_CONFIG,
        'districts': build_districts_data_ems,   # EMS variant incl. 'stations'
        'supply': stations_data,
        'candidatesByPreset': candidates_by_preset_json,
    },
    'hospitals': {
        'label': 'Hospitals',
        'supplyLabel': 'Hospitals',
        'supplyIcon': 'hospital',
        'threshold': HOSPITAL_THRESHOLD_MIN,
        'criteria': HOSPITAL_CRITERIA_CONFIG,
        'districts': build_districts_data(hosp_districts),
        'supply': hospitals_supply,
        'candidatesByPreset': hosp_candidates_by_preset_json,  # from Step 6
    },
}
js_data = f"""        const DATASETS = {json.dumps(datasets_obj)};
        let ACTIVE_DATASET = 'ems';
        const GOVERNORATES = {json.dumps(governorates_list)};
        const MAX_POP = {max_population};
        const LEBANON_BOUNDS = {json.dumps(LEBANON_BOUNDS)};"""
```

- [ ] **Step 6: Generate hospital proposals (reuse the rule-based clustering)**

The grid + `_find_candidates_by_rule` logic (sections 5f–5h) currently runs once for EMS using `best_time_s`. Wrap the grid-scoring + candidate-finding into a helper `build_candidates(best_time_s, threshold_min)` returning `candidates_by_preset_json`, call it for EMS (`best_time_s`, 10) and hospitals (`hosp_result['best_time_s']`, 30). If time-boxed, set `hosp_candidates_by_preset_json = {'balanced': [], 'access': [], 'population': []}` as an interim and note it; proposals can be enabled in a follow-up. (Decision required during execution — see Open Questions.)

- [ ] **Step 7: Run pipeline (validation gate)**

Run: `python scripts/phase1_ahp_explore.py`
Expected: completes; prints both EMS and hospital AHP summaries.

- [ ] **Step 8: Verify DATASETS embedded in HTML**

Run: `grep -c "const DATASETS" data/phase1_ahp_dashboard.html`
Expected: `1`.
Run: `python -c "import re; h=open('data/phase1_ahp_dashboard.html').read(); print('hospitals' in h and 'ambulance' in h)"`
Expected: `True`.

- [ ] **Step 9: Commit**

```bash
git add scripts/phase1_ahp_explore.py
git commit -m "feat: run hospital analysis and embed DATASETS (ems + hospitals)"
```

---

## Task 6: JS dataset-switch controller

Make the JS read from the active dataset and add `setActiveDataset(key)` that rebinds the working globals and re-runs the render/init functions. The existing code uses module-level `const DISTRICTS`, `const STATIONS`, `const CRITERIA_CONFIG`, `var CANDIDATES_BY_PRESET`, `var CANDIDATES`. Convert these to mutable bindings sourced from `DATASETS[ACTIVE_DATASET]`.

**Files:**
- Modify: `templates/phase1_ahp_dashboard.js`

- [ ] **Step 1: Replace the removed constants with dataset-backed bindings**

At the top of the JS (the constants previously injected via `%%JS_DATA%%` are now `DATASETS`/`ACTIVE_DATASET`/`GOVERNORATES`/`MAX_POP`/`LEBANON_BOUNDS`). Add near the top of `phase1_ahp_dashboard.js`:

```javascript
let DISTRICTS = DATASETS[ACTIVE_DATASET].districts;
let STATIONS = DATASETS[ACTIVE_DATASET].supply;
let CRITERIA_CONFIG = DATASETS[ACTIVE_DATASET].criteria;
let CANDIDATES_BY_PRESET = DATASETS[ACTIVE_DATASET].candidatesByPreset;
let CANDIDATES = (CANDIDATES_BY_PRESET && CANDIDATES_BY_PRESET.balanced) || [];
let DEFAULT_COVERAGE_THRESHOLD = DATASETS[ACTIVE_DATASET].threshold;
```

> All existing functions referencing these names keep working. `const` → `let`
> is required so `setActiveDataset` can rebind them.

- [ ] **Step 2: Add the switch controller**

Add a new function (place it near `initFilters`, ~line 1017):

```javascript
function setActiveDataset(key) {
    if (!DATASETS[key]) return;
    ACTIVE_DATASET = key;
    const ds = DATASETS[key];
    DISTRICTS = ds.districts;
    STATIONS = ds.supply;
    CRITERIA_CONFIG = ds.criteria;
    CANDIDATES_BY_PRESET = ds.candidatesByPreset;
    CANDIDATES = (CANDIDATES_BY_PRESET && CANDIDATES_BY_PRESET.balanced) || [];
    DEFAULT_COVERAGE_THRESHOLD = ds.threshold;

    // Rebuild supply markers + candidates + colors + panels
    refreshSupplyLayer();         // Task 7
    initCandidatesLayer();
    initModelNormScores();
    recomputeAhpScores();
    updateMapDistrictColors();
    renderModelTab();
    renderFiltersTab();
    applyFilters();
    const f = getFilteredDistricts();
    renderAhpSummary(f);
    renderAhpRanking(f);
    renderCandidates();
}
```

> Cross-check the exact render function names against the file (they exist:
> `initCandidatesLayer`, `initModelNormScores`, `recomputeAhpScores`,
> `updateMapDistrictColors`, `renderModelTab`, `renderFiltersTab`,
> `applyFilters`, `getFilteredDistricts`, `renderAhpSummary`,
> `renderAhpRanking`, `renderCandidates`). Remove any call that does not exist
> and add the one that initializes that panel in `initDashboard`.

- [ ] **Step 3: Commit**

```bash
git add templates/phase1_ahp_dashboard.js
git commit -m "feat: setActiveDataset controller + dataset-backed globals"
```

---

## Task 7: Client-side supply markers (EMS ambulance vs hospital)

Currently EMS markers are drawn by Folium server-side. To toggle datasets, draw supply markers client-side from `STATIONS` as a Leaflet layer group (mirroring `initCandidatesLayer`), and remove/redraw on switch.

**Files:**
- Modify: `templates/phase1_ahp_dashboard.js`
- Modify: `scripts/phase1_ahp_explore.py` (stop adding the EMS marker layer via Folium, OR keep it but hide when hospitals active — see Step 1)

- [ ] **Step 1: Add a client-side supply layer**

Add to `phase1_ahp_dashboard.js`:

```javascript
let supplyLayerGroup = null;

function refreshSupplyLayer() {
    if (!map) return;
    if (supplyLayerGroup) { map.removeLayer(supplyLayerGroup); supplyLayerGroup = null; }
    const ds = DATASETS[ACTIVE_DATASET];
    const markers = STATIONS.map(s => {
        const color = ACTIVE_DATASET === 'hospitals' ? '#c0392b' : '#2c7fb8';
        const m = L.circleMarker([s.lat, s.lon], {
            radius: 5, color: '#fff', weight: 1, fillColor: color, fillOpacity: 0.9,
        });
        let html;
        if (ACTIVE_DATASET === 'hospitals') {
            const est = s.beds_estimated ? ' <em>(estimated)</em>' : '';
            html = `<b>${escapeHtml(s.name)}</b><br>Beds: ${s.beds}${est}` +
                   (s.operator ? `<br>${escapeHtml(s.operator)}` : '');
        } else {
            html = `<b>EMS Station</b><br>${escapeHtml(s.district_name || '')}`;
        }
        m.bindPopup(html);
        return m;
    });
    supplyLayerGroup = L.layerGroup(markers).addTo(map);
}
```

- [ ] **Step 2: Call it on init and ensure Folium EMS markers don't double-draw**

In `initDashboard` (after `initMapRefs`), call `refreshSupplyLayer()`. In `scripts/phase1_ahp_explore.py` section 6, remove the Folium-added EMS station markers (the `folium.Marker`/`CircleMarker` loop for `ems_valid`) so EMS points are drawn only client-side. Keep the districts/coverage Folium layers.

Run: `grep -n "folium" scripts/phase1_ahp_explore.py | grep -i "marker\|ems"`
Expected: identify the EMS marker loop to remove; districts/coverage layers untouched.

- [ ] **Step 3: Run pipeline + open dashboard (validation gate)**

Run: `python scripts/phase1_ahp_explore.py && open data/phase1_ahp_dashboard.html`
Expected: EMS markers appear (client-side) on load; no duplicate markers.

- [ ] **Step 4: Commit**

```bash
git add templates/phase1_ahp_dashboard.js scripts/phase1_ahp_explore.py
git commit -m "feat: client-side supply markers for dataset toggle"
```

---

## Task 8: Dataset selector dropdown (HTML + CSS + wiring)

**Files:**
- Modify: `templates/phase1_ahp_dashboard.html` (or the `panel_html` block in the Python script — confirm where the header lives)
- Modify: `templates/phase1_ahp_dashboard.css`
- Modify: `templates/phase1_ahp_dashboard.js`

- [ ] **Step 1: Add the dropdown to the panel header**

The header is built in `panel_html` inside `scripts/phase1_ahp_explore.py` (the `.panel-header` block). Add a dataset selector under the title:

```html
<div class="dataset-selector">
    <label for="dataset-select">Dataset</label>
    <select id="dataset-select">
        <option value="ems" selected>EMS Stations</option>
        <option value="hospitals">Hospitals</option>
    </select>
</div>
```

- [ ] **Step 2: Style it**

Add to `templates/phase1_ahp_dashboard.css`:

```css
.dataset-selector { display:flex; align-items:center; gap:8px; margin-top:8px; }
.dataset-selector label { font-size:12px; font-weight:600; color:#cfd8dc; }
.dataset-selector select {
    flex:1; padding:6px 8px; border-radius:6px; border:1px solid #37474f;
    background:#263238; color:#eceff1; font-size:13px;
}
```

- [ ] **Step 3: Wire the change handler**

In `initDashboard` (or `initFilters`) in the JS, add:

```javascript
const dsSel = document.getElementById('dataset-select');
if (dsSel) dsSel.addEventListener('change', e => setActiveDataset(e.target.value));
```

- [ ] **Step 4: Run + manual toggle check (validation gate)**

Run: `python scripts/phase1_ahp_explore.py && open data/phase1_ahp_dashboard.html`
Manual checklist:
- Dropdown shows "EMS Stations" / "Hospitals".
- Switching to Hospitals: red hospital markers replace EMS markers; choropleth recolors; stat cards/ranking update; Model tab shows 4 criteria incl. "Bed Capacity Gap"; hospital popups show `Beds: N` and `(estimated)` where applicable.
- Switching back to EMS restores the original view (3 criteria, ambulance markers).

- [ ] **Step 5: Commit**

```bash
git add templates/phase1_ahp_dashboard.html templates/phase1_ahp_dashboard.css templates/phase1_ahp_dashboard.js scripts/phase1_ahp_explore.py
git commit -m "feat: dataset selector dropdown wired to setActiveDataset"
```

---

## Task 9: Final validation, cleanup, docs

**Files:**
- Delete: `data/_baseline_ems_districts.json`
- Modify: `PROJECT_NOTES.md` (add Phase 2 + 5th data source attribution)

- [ ] **Step 1: Final EMS regression check**

Run the Task 3 Step 5 diff command once more against the baseline.
Expected: `EMS UNCHANGED ✓`.

- [ ] **Step 2: Remove the temporary baseline**

```bash
git rm data/_baseline_ems_districts.json
```

- [ ] **Step 3: Document Phase 2 + ODbL attribution**

Add a short Phase 2 section to `PROJECT_NOTES.md`: the hospitals dataset (Lebanon Healthsites, Global Healthsites Mapping Project via HDX, ODbL — requires attribution + share-alike), the 4-criterion hospital model, and the dataset selector. List it as the project's 5th data source.

- [ ] **Step 4: Final commit**

```bash
git add PROJECT_NOTES.md
git commit -m "docs: Phase 2 hospital integration notes + ODbL attribution; drop baseline"
```

---

## Open Questions (resolve during execution)

1. **Hospital proposals (Task 5 Step 6):** enable rule-based hospital proposals now (wrap grid logic into `build_candidates`), or ship hospitals with the analysis/markers first and add proposals in a fast follow-up? Recommend wrapping it now if the grid logic cleanly accepts a `best_time_s`; otherwise interim-empty and follow up.
2. **EMS `stations` field:** the EMS districts records carry a `stations` count the hospital records don't. Confirm the ranking/popup JS tolerates a missing `stations` key for hospitals (guard with `d.stations ?? 0`).
3. **Copilot sidecar:** `copilot_server.py` reads `phase1_ahp_districts.json` (EMS). Decide whether to also emit a hospital sidecar — out of scope unless desired.

## Self-Review Notes

- **Spec coverage:** data cleaning (Task 1), generalized AHP engine (Tasks 3–4), 4 criteria incl. bed capacity (Task 4–5), 30-min threshold + population-dominant weights (Task 5 config), median-imputed/flagged beds (Tasks 1 + 7 popups), selector + client-side re-render (Tasks 6–8), testing/validation (gates throughout + Task 9). All spec sections map to tasks.
- **Type consistency:** column rename `covered_10min`→`covered` handled in Task 3 Step 3; render function names in Task 6 flagged for verification against the file; `norm_bed_gap`/`beds_per_1000` defined in Task 4 and consumed in Task 5 builder.
- **Adaptation:** TDD replaced by runnable validation gates (no test harness; heavy pipeline), per the testing note — this is the honest, accurate approach for this repo.
