# Hospital Recommended Interventions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hospital Analysis tab's dead "Recommended New Stations" section with a live "Recommended Interventions" list whose cards fly to the district, drop an indicative demand-center ghost marker, and halo the relevant existing hospitals.

**Architecture:** Python adds two data fields at build time (`district` per hospital, `demand_center` per district). The JS template adds a dataset dispatcher (`renderActionsSection`) over the existing `#candidates-list` slot: EMS keeps `renderCandidates()` verbatim; hospitals get `computeInterventions()` (pure read of live benchmark/threshold) + `renderInterventions()` + ghost/halo map artifacts with explicit clearing. Spec: `docs/superpowers/specs/2026-06-12-hospital-interventions-design.md`.

**Tech Stack:** Python (geopandas/rasterio build script), vanilla JS template, CSS template. No automated tests — verification is rebuild (~5 min) + browser checklist.

---

### Task 0: Commit pending working-tree changes

The tree holds the finished EMS-Model-redesign work (templates + rebuilt dashboard). Commit it first so this feature's commits are clean.

- [ ] **Step 1:**

```bash
cd "/Users/apple/Desktop/EMS project"
git add templates/ data/phase1_ahp_dashboard.html
git commit -m "feat(ui): unify EMS Model tab onto the compact setup+weights design"
```

---

### Task 1: Python — `district` per hospital + `demand_center` per district

**Files:**
- Modify: `scripts/phase1_ahp_explore.py` (~line 673 after `total_hospitals`; `build_hospital_districts_data` ~line 1568; `hospitals_supply` loop ~line 1580; HTML skeleton ~line 1657)

- [ ] **Step 1: Demand centers.** After the line `hosp_districts['total_hospitals'] = hosp_districts['NAME_2'].map(lambda n: int(_all_by_name.get(n, 0)))` insert:

```python
# Indicative demand centers: population-weighted centroid of the WorldPop
# sample points inside each district (drives the "ghost" marker on the
# hospital Recommended Interventions cards). Fallback: polygon centroid.
_dc_by_name = {}
try:
    _dc_pts = gpd.sjoin(raster_gdf,
                        hosp_districts[['NAME_2', 'geometry']].to_crs(raster_gdf.crs),
                        how='inner', predicate='within')
    for _nm, _grp in _dc_pts.groupby('NAME_2'):
        _w = float(_grp['population'].sum())
        if _w > 0:
            _dc_by_name[_nm] = [
                round(float((_grp.geometry.y * _grp['population']).sum() / _w), 5),
                round(float((_grp.geometry.x * _grp['population']).sum() / _w), 5),
            ]
except Exception as _e:
    print(f"  ⚠ Demand centers from raster failed ({_e}); using polygon centroids")
for _, _row in hosp_districts.iterrows():
    if _row['NAME_2'] not in _dc_by_name:
        _c = _row.geometry.centroid
        _dc_by_name[_row['NAME_2']] = [round(float(_c.y), 5), round(float(_c.x), 5)]
hosp_districts['demand_center'] = hosp_districts['NAME_2'].map(_dc_by_name.get)
print(f"  ✓ Demand centers: {len(_dc_by_name)} districts")
```

- [ ] **Step 2: Embed in district JSON.** In `build_hospital_districts_data`, after the line `'afford_class': str(row.get('afford_class', 'public')),` add:

```python
            'demand_center': row.get('demand_center') if isinstance(row.get('demand_center'), list) else None,
```

- [ ] **Step 3: District per hospital.** Replace:

```python
hospitals_supply = []
for _, r in hospitals_df.iterrows():
    nm = _clean_str(r['name'])
    hospitals_supply.append({
        'lat': float(r['lat']), 'lon': float(r['lon']),
        'name': nm if nm else 'Unnamed hospital',
        'beds': int(r['beds']), 'beds_estimated': bool(r['beds_estimated']),
        'operator': _clean_str(r.get('operator', '')),
        'htype': _clean_str(r.get('hospital_type', '')) or 'private',
        'osrc': _clean_str(r.get('ownership_source', '')),
    })
```

with:

```python
# Map each hospital to its district (same join as the per-district counts)
# so intervention cards can halo the right facilities client-side.
_hosp_district_by_idx = {}
try:
    _hj = gpd.sjoin(hospitals_gdf.to_crs(hosp_districts.crs),
                    hosp_districts[['NAME_2', 'geometry']], how='left', predicate='within')
    _hj = _hj[~_hj.index.duplicated(keep='first')]
    _hosp_district_by_idx = _hj['NAME_2'].fillna('').to_dict()
except Exception as _e:
    print(f"  ⚠ hospital→district join failed: {_e}")

hospitals_supply = []
for _i, r in hospitals_df.iterrows():
    nm = _clean_str(r['name'])
    hospitals_supply.append({
        'lat': float(r['lat']), 'lon': float(r['lon']),
        'name': nm if nm else 'Unnamed hospital',
        'beds': int(r['beds']), 'beds_estimated': bool(r['beds_estimated']),
        'operator': _clean_str(r.get('operator', '')),
        'htype': _clean_str(r.get('hospital_type', '')) or 'private',
        'osrc': _clean_str(r.get('ownership_source', '')),
        'district': _clean_str(_hosp_district_by_idx.get(_i, '')),
    })
```

- [ ] **Step 4: Header id in the skeleton.** Change the line

```html
                        <div class="section-header" style="margin:0;">Recommended New Stations</div>
```

to

```html
                        <div class="section-header" style="margin:0;" id="actions-section-header">Recommended New Stations</div>
```

- [ ] **Step 5: Syntax check.** `venv/bin/python -c "import ast; ast.parse(open('scripts/phase1_ahp_explore.py').read())" && echo OK` → `OK`

- [ ] **Step 6: Commit.** `git add scripts/phase1_ahp_explore.py && git commit -m "feat(data): hospital district tags + per-district demand centers"`

---

### Task 2: JS — interventions module (compute, render, map artifacts, dispatcher)

**Files:**
- Modify: `templates/phase1_ahp_dashboard.js`

- [ ] **Step 1: Globals.** After `let _activePreset = 'balanced';   // active weight preset; null = user-customized` add:

```js
let _ghostMarker = null;      // indicative demand-center circle (hospitals)
let _haloHospitals = [];      // hospitals currently haloed by an intervention card
```

- [ ] **Step 2: Marker refs.** In `refreshSupplyLayer()`, inside the hospital branch, after `m.on('click', () => showHospitalDetail(s));` add:

```js
            s._mRef = m;
```

- [ ] **Step 3: The module.** Insert directly above `function renderModelTab() {`:

```js
// ── RECOMMENDED INTERVENTIONS (hospitals' counterpart of proposed stations) ──
const _GAP_CHIP   = { capacity: 'capacity', no_public: 'no public', access: 'access' };
const _GAP_ACTION = {
    capacity:  'Expand bed capacity at existing facilities',
    no_public: 'Add public or contracted-affordable capacity',
    access:    'Operational / transport support',
};

/** Pure read: districts with ≥1 gap vs the live benchmark/threshold, worst first. */
function computeInterventions() {
    const bench = _getBenchmark();
    const thr   = _getThreshold();
    const out = [];
    DISTRICTS.forEach(d => {
        const gaps = [];
        const pop = d.population || 0;
        const bpk = d.beds_per_1000 || 0;
        let bedsShort = 0;
        if (bpk < bench) { bedsShort = (bench - bpk) * pop / 1000; gaps.push('capacity'); }
        if ((d.public_hospitals || 0) === 0) gaps.push('no_public');
        const tt = d.min_travel_time_min;
        if (tt !== null && tt !== undefined && tt > thr) gaps.push('access');
        if (gaps.length) out.push({ d, gaps, bedsShort, pop });
    });
    out.sort((a, b) => (b.d.ahp_score || 0) - (a.d.ahp_score || 0));
    return out;
}

function renderInterventions() {
    const listEl = document.getElementById('candidates-list');
    if (!listEl) return;
    const items    = computeInterventions();
    const limitEl  = document.getElementById('candidates-limit');
    const limitVal = limitEl ? limitEl.value : '10';
    const n        = limitVal === 'all' ? items.length : Math.min(items.length, parseInt(limitVal, 10) || 10);
    const bench = _getBenchmark(), thr = _getThreshold();

    if (items.length === 0) {
        listEl.innerHTML = `<div class="empty-section">&#10003; No gaps at the current benchmark (${bench}/1k) and threshold (${thr} min)</div>`;
        return;
    }
    const intro = `<div class="decision-standards-card">
        <b>No new-hospital pins by design:</b> Lebanon's hospital gap is distribution &amp; affordability, not raw count.
        Each card names the gap and the honest intervention; click it to fly to the district, see an
        <i>indicative demand center</i> (dashed circle — where the affected population concentrates, not a site
        proposal), and the existing facilities the intervention would run through.</div>`;
    listEl.innerHTML = intro + items.slice(0, n).map((it, i) => {
        const dn = it.d.district_name;
        const chips = it.gaps.map(g => `<span class="iv-chip iv-${g}">${_GAP_CHIP[g]}</span>`).join('');
        const magParts = [];
        if (it.gaps.includes('capacity'))  magParts.push(`&#8776;${formatNum(Math.round(it.bedsShort))} beds short of ${bench}/1k`);
        if (it.gaps.includes('no_public')) magParts.push(`${formatNum(it.pop)} people, 0 public hospitals`);
        if (it.gaps.includes('access'))    magParts.push(`&gt;${thr} min to nearest hospital`);
        const actions = it.gaps.map(g => _GAP_ACTION[g]).join(' &middot; ');
        return `<div class="candidate-card iv-card" onclick="onInterventionClick('${esc(dn)}')">
            <div class="candidate-card-top">
                <span class="candidate-rank-badge">#${i + 1}</span>
                <b class="iv-district">${dn}</b>
                ${chips}
            </div>
            <div class="candidate-card-meta">${magParts.map(m => `<span class="candidate-metric">${m}</span>`).join('')}</div>
            <div class="iv-action">&#8594; ${actions}</div>
        </div>`;
    }).join('');
}

/** Removes the ghost demand-center marker and any facility halos. */
function clearInterventionMapArtifacts() {
    if (_ghostMarker && map) map.removeLayer(_ghostMarker);
    _ghostMarker = null;
    _haloHospitals.forEach(s => {
        const el = s._mRef && s._mRef.getElement && s._mRef.getElement();
        const badge = el && el.querySelector('.hosp-marker');
        if (badge) badge.classList.remove('hosp-halo', 'hosp-halo-strong');
    });
    _haloHospitals = [];
}

/** Intervention card click: fly to district + ghost demand center + facility halos. */
function onInterventionClick(districtName) {
    clearInterventionMapArtifacts();
    onDistrictCardClick(districtName);
    const d = DISTRICTS.find(x => x.district_name === districtName);
    if (!d || !map) return;

    if (Array.isArray(d.demand_center) && d.demand_center.length === 2) {
        _ghostMarker = L.circleMarker([d.demand_center[0], d.demand_center[1]], {
            pane: 'supplyPane',
            radius: 14, color: '#ffffff', weight: 2, dashArray: '4 4',
            fillColor: '#ffffff', fillOpacity: 0.12,
        }).addTo(map);
        _ghostMarker.bindTooltip('Indicative demand center — not a site proposal', { direction: 'top' });
    }

    // Affordability-only gap → halo private hospitals (contracting candidates);
    // otherwise halo all of the district's hospitals (public emphasized).
    const it = computeInterventions().find(x => x.d.district_name === districtName);
    const privateOnly = !!it && it.gaps.includes('no_public') && !it.gaps.includes('capacity');
    (STATIONS || []).forEach(s => {
        if (s.district !== districtName) return;
        if (privateOnly && s.htype === 'public') return;
        const el = s._mRef && s._mRef.getElement && s._mRef.getElement();
        const badge = el && el.querySelector('.hosp-marker');
        if (badge) {
            badge.classList.add(s.htype === 'public' ? 'hosp-halo-strong' : 'hosp-halo');
            _haloHospitals.push(s);
        }
    });
}

/** Dataset dispatcher for the Analysis tab's bottom section. */
function renderActionsSection() {
    const header = document.getElementById('actions-section-header');
    if (ACTIVE_DATASET === 'hospitals') {
        if (header) header.textContent = 'Recommended Interventions';
        renderInterventions();
    } else {
        if (header) header.textContent = 'Recommended New Stations';
        renderCandidates();
    }
}
```

- [ ] **Step 4: Reroute the generic `renderCandidates()` call sites** (those reachable in the hospital view) to `renderActionsSection()`:
  - `_toggleModelFilter` / `_toggleShowAllProposed` (~lines 876, 885): `renderCandidates();` → `renderActionsSection();`
  - `applyPreset` tail (~line 1046): `renderCandidates();` → `renderActionsSection();`
  - `resetModelDefaults` (~line 1093): `renderCandidates();` → `renderActionsSection();`
  - `setActiveDataset` (~line 1377): `if (typeof renderCandidates === 'function') renderCandidates();` → `if (typeof renderActionsSection === 'function') renderActionsSection();`
  - `initFilters` listener (~line 1404): `candidatesLimit.addEventListener('change', renderCandidates);` → `candidatesLimit.addEventListener('change', renderActionsSection);`
  - `initFilters` tail (~line 1429): `renderCandidates();` → `renderActionsSection();`

  Do NOT touch the `renderCandidates()` definition or its EMS internals.

- [ ] **Step 5: Live updates + clearing hooks.**
  - In `renderModelResults`, change `if (ACTIVE_DATASET === 'hospitals') { renderHospitalGapResults(el); return; }` to:

```js
    if (ACTIVE_DATASET === 'hospitals') { renderHospitalGapResults(el); renderInterventions(); return; }
```

  - In `setActiveDataset`, after `if (typeof hideHospitalDetail === 'function') hideHospitalDetail();` add:

```js
    if (typeof clearInterventionMapArtifacts === 'function') clearInterventionMapArtifacts();
```

  - In `resetMapView`, after `hideSelectedDistrictCard();` add:

```js
    clearInterventionMapArtifacts();
```

- [ ] **Step 6: Syntax.** `node --check templates/phase1_ahp_dashboard.js && echo SYNTAX_OK`

- [ ] **Step 7: Commit.** `git add templates/phase1_ahp_dashboard.js && git commit -m "feat(analysis): hospital Recommended Interventions list + ghost demand center + facility halos"`

---

### Task 3: CSS — chips, action line, ghost-adjacent halo styles

**Files:**
- Modify: `templates/phase1_ahp_dashboard.css` (append after `.model-weights-details summary:hover { color: var(--text-2); }`)

- [ ] **Step 1: Add:**

```css
/* ── RECOMMENDED INTERVENTIONS (hospital Analysis tab) ───────────────────── */
.iv-card { cursor: pointer; }

.iv-district { font-size: 13px; color: var(--text); flex: 1; }

.iv-chip {
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 2px 7px;
    border-radius: 9px;
    border: 1px solid var(--border-2);
    color: var(--text-2);
    white-space: nowrap;
}

.iv-capacity  { border-color: #e74c3c; color: #e74c3c; }
.iv-no_public { border-color: #9b59b6; color: #9b59b6; }
.iv-access    { border-color: #3498db; color: #3498db; }

.iv-action {
    margin-top: 6px;
    font-size: 11px;
    color: var(--text-2);
}

/* Facility halos for intervention highlights (public = stronger) */
.hosp-halo {
    box-shadow: 0 0 0 3px rgba(255,255,255,0.55), 0 0 12px 4px rgba(255,255,255,0.35);
    border-radius: 50%;
}

.hosp-halo-strong {
    box-shadow: 0 0 0 4px rgba(255,255,255,0.9), 0 0 16px 6px rgba(255,255,255,0.55);
    border-radius: 50%;
}
```

- [ ] **Step 2: Braces.** `python3 -c "s=open('templates/phase1_ahp_dashboard.css').read(); assert s.count('{')==s.count('}'); print('BRACES_OK')"`

- [ ] **Step 3: Commit.** `git add templates/phase1_ahp_dashboard.css && git commit -m "style(analysis): intervention card chips + facility halo styles"`

---

### Task 4: Rebuild + manual verification (spec §Testing)

- [ ] **Step 1:** `venv/bin/python scripts/phase1_ahp_explore.py 2>&1 | tail -3` → `Dashboard saved to: …`. Watch the log for `✓ Demand centers: 26 districts`.
- [ ] **Step 2:** `open data/phase1_ahp_dashboard.html` and run the spec's 6-point checklist (interventions list, slider live-updates, Akkar ghost+halos, Metn private-only halos, Reset Map clears, EMS regression).
- [ ] **Step 3:** Final commit: `git add -A data/phase1_ahp_dashboard.html && git commit -m "feat(analysis): rebuilt dashboard with hospital interventions"`
