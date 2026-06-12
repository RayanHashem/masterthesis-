# Hospital Setup + Weights Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an always-visible priority-formula line and a collapsed "Customize weights" expander (4 preset chips + 4 editable sliders) to the hospital Model tab's compact setup card.

**Architecture:** All UI lives in the `isHosp` branch of `renderModelTab()` in the JS template; the existing `recomputeAhpScores()` already reads `weight-<id>` sliders, so enabling them is enough to drive the math. A module-level `_activePreset` tracks which preset chip is active (`null` = Custom). The dashboard is a static HTML built by `scripts/phase1_ahp_explore.py` from `templates/`; there is **no automated test suite** — verification is rebuild + browser check, done once at the end (the build takes ~5 min, so we don't rebuild per task).

**Tech Stack:** Vanilla JS template (`templates/phase1_ahp_dashboard.js`), CSS template (`templates/phase1_ahp_dashboard.css`), Python build script (`scripts/phase1_ahp_explore.py`). Spec: `docs/superpowers/specs/2026-06-12-hospital-setup-weights-merge-design.md`.

**Conventions:** EMS view must be byte-identical in behavior. `pct-<id>` / `weight-<id>` / `preset-<name>` element ids are shared with the EMS weights block — safe because the Model tab renders only one dataset's markup at a time (`panel.innerHTML` is replaced on dataset switch). All DOM lookups in shared helpers are already null-guarded.

---

### Task 1: Python — add the `capacity` hospital preset

**Files:**
- Modify: `scripts/phase1_ahp_explore.py:1755-1759` (the `'presets'` dict under `datasets_obj['hospitals']`)

- [ ] **Step 1: Add the preset**

Replace:

```python
        'presets': {
            'balanced':   {'access_gap': 0.30, 'pop_density': 0.30, 'exposed_pop': 0.25, 'bed_gap': 0.15},
            'access':     {'access_gap': 0.50, 'pop_density': 0.20, 'exposed_pop': 0.20, 'bed_gap': 0.10},
            'population': {'access_gap': 0.15, 'pop_density': 0.45, 'exposed_pop': 0.25, 'bed_gap': 0.15},
        },
```

with:

```python
        'presets': {
            'balanced':   {'access_gap': 0.30, 'pop_density': 0.30, 'exposed_pop': 0.25, 'bed_gap': 0.15},
            'access':     {'access_gap': 0.50, 'pop_density': 0.20, 'exposed_pop': 0.20, 'bed_gap': 0.10},
            'population': {'access_gap': 0.15, 'pop_density': 0.45, 'exposed_pop': 0.25, 'bed_gap': 0.15},
            'capacity':   {'access_gap': 0.15, 'pop_density': 0.15, 'exposed_pop': 0.20, 'bed_gap': 0.50},
        },
```

(Only the **hospitals** dict — the `'ems'` presets at lines 1738-1742 stay 3-key, no `bed_gap`.)

- [ ] **Step 2: Syntax check**

Run: `cd "/Users/apple/Desktop/EMS project" && venv/bin/python -c "import ast; ast.parse(open('scripts/phase1_ahp_explore.py').read())" && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/phase1_ahp_explore.py
git commit -m "feat(model): add capacity-focused weight preset for hospitals"
```

---

### Task 2: JS — `_activePreset` state + formula line + expander markup

**Files:**
- Modify: `templates/phase1_ahp_dashboard.js` (top-level state ~line 17; `renderModelTab()` hospital branch ~lines 905-928)

- [ ] **Step 1: Add module state**

After the existing line `let highlightTimeout = null;` (~line 17), add:

```js
let _activePreset = 'balanced';   // active weight preset; null = user-customized
```

- [ ] **Step 2: Reset preset state on tab render**

In `renderModelTab()`, immediately after `const supplyWord = isHosp ? 'hospital' : 'station';`, add:

```js
    _activePreset = 'balanced';   // fresh render always starts at defaults
```

- [ ] **Step 3: Extend the hospital compact card**

In the `if (isHosp) { ... }` branch of `renderModelTab()`, replace the closing of the compact card —

```js
            <div class="model-compact-row" title="Districts below this beds-per-1,000 level are &quot;under-capacity&quot;. Default = national average.">
                <span class="model-compact-label">Capacity Benchmark</span>
                <input type="range" id="model-benchmark" class="filter-slider"
                    min="1" max="6" step="0.1" value="${benchDefault}"
                    oninput="document.getElementById('bench-val').textContent=this.value+' /1k'; renderModelResults()">
                <span class="model-value" id="bench-val">${benchDefault} /1k</span>
            </div>
        </div>`;
```

— with the same two rows plus the formula line and expander:

```js
            <div class="model-compact-row" title="Districts below this beds-per-1,000 level are &quot;under-capacity&quot;. Default = national average.">
                <span class="model-compact-label">Capacity Benchmark</span>
                <input type="range" id="model-benchmark" class="filter-slider"
                    min="1" max="6" step="0.1" value="${benchDefault}"
                    oninput="document.getElementById('bench-val').textContent=this.value+' /1k'; renderModelResults()">
                <span class="model-value" id="bench-val">${benchDefault} /1k</span>
            </div>
            <div class="model-formula-row" title="How the Overall-priority score is weighted. Expand below to change it.">
                <span class="model-formula-text">Priority formula: <span id="hosp-formula-pcts">&mdash;</span></span>
                <span class="model-formula-chip" id="hosp-formula-chip">Balanced</span>
            </div>
            <details class="model-weights-details">
                <summary>Customize weights</summary>
                <div class="preset-btn-group" style="margin-top:8px;">
                    <button class="preset-btn preset-btn-active" id="preset-balanced" onclick="applyPreset('balanced')">Balanced</button>
                    <button class="preset-btn" id="preset-access" onclick="applyPreset('access')">Access</button>
                    <button class="preset-btn" id="preset-population" onclick="applyPreset('population')">Population</button>
                    <button class="preset-btn" id="preset-capacity" onclick="applyPreset('capacity')">Capacity</button>
                </div>
                ${CRITERIA_CONFIG.map(c => `
                <div class="model-compact-row" title="${c.description.replace(/"/g, '&quot;')}">
                    <span class="model-compact-label">${c.label}</span>
                    <input type="range" class="filter-slider" id="weight-${c.id}"
                        min="0" max="1" step="0.05" value="${c.weight}"
                        oninput="onHospWeightInput()">
                    <span class="model-pct" id="pct-${c.id}">&mdash;</span>
                </div>`).join('')}
            </details>
        </div>`;
```

(`recomputeAhpScores()` at the end of `renderModelTab()` populates the `—` placeholders on first render.)

- [ ] **Step 4: Commit**

```bash
git add templates/phase1_ahp_dashboard.js
git commit -m "feat(model): formula line + customize-weights expander markup (hospitals)"
```

---

### Task 3: JS — live formula updates + custom-weight handler

**Files:**
- Modify: `templates/phase1_ahp_dashboard.js` (`_updateWeightDisplay()` ~line 689)

- [ ] **Step 1: Add the handler + formula updater, and hook the display function**

Replace:

```js
/** Updates the percentage labels and stacked bar in the Model tab. */
function _updateWeightDisplay(normW) {
    CRITERIA_CONFIG.forEach((c, i) => {
        const pct   = Math.round((normW[c.id] || 0) * 100);
        const pctEl = document.getElementById('pct-' + c.id);
        if (pctEl) pctEl.textContent = pct + '%';
        const segEl = document.getElementById('wbar-' + c.id);
        if (segEl) { segEl.style.width = pct + '%'; segEl.style.background = _SEG_COLORS[i % _SEG_COLORS.length]; }
    });
}
```

with:

```js
/** Updates the percentage labels and stacked bar in the Model tab. */
function _updateWeightDisplay(normW) {
    CRITERIA_CONFIG.forEach((c, i) => {
        const pct   = Math.round((normW[c.id] || 0) * 100);
        const pctEl = document.getElementById('pct-' + c.id);
        if (pctEl) pctEl.textContent = pct + '%';
        const segEl = document.getElementById('wbar-' + c.id);
        if (segEl) { segEl.style.width = pct + '%'; segEl.style.background = _SEG_COLORS[i % _SEG_COLORS.length]; }
    });
    _updateHospFormulaLine(normW);
}

/** Plain-word names for the formula line. */
const _FORMULA_WORDS = { access_gap: 'travel', pop_density: 'density', exposed_pop: 'exposure', bed_gap: 'beds' };
const _PRESET_LABELS = { balanced: 'Balanced', access: 'Access', population: 'Population', capacity: 'Capacity' };

/** Updates the hospital formula line + preset chip (no-op when not rendered, e.g. EMS). */
function _updateHospFormulaLine(normW) {
    const pctsEl = document.getElementById('hosp-formula-pcts');
    if (!pctsEl) return;
    pctsEl.innerHTML = CRITERIA_CONFIG.map(c =>
        `<b>${Math.round((normW[c.id] || 0) * 100)}% ${_FORMULA_WORDS[c.id] || c.id}</b>`).join(' &middot; ');
    const chipEl = document.getElementById('hosp-formula-chip');
    if (chipEl) chipEl.textContent = _activePreset ? (_PRESET_LABELS[_activePreset] || _activePreset) : 'Custom';
}

/** A weight slider was moved by hand: preset becomes Custom, everything recomputes. */
function onHospWeightInput() {
    _activePreset = null;
    document.querySelectorAll('.preset-btn').forEach(btn => btn.classList.remove('preset-btn-active'));
    recomputeAhpScores();
}
```

(`recomputeAhpScores()` already calls `_updateWeightDisplay(normW)` in step 5, so the formula line tracks every change — slider moves, presets, and resets — with no further wiring.)

- [ ] **Step 2: Commit**

```bash
git add templates/phase1_ahp_dashboard.js
git commit -m "feat(model): live priority-formula line + custom weight handler"
```

---

### Task 4: JS — make `applyPreset()` hospital-aware

**Files:**
- Modify: `templates/phase1_ahp_dashboard.js` (`applyPreset()` ~line 1008)

- [ ] **Step 1: Track the preset and guard the EMS-only block**

In `applyPreset(presetName)`, after `if (!preset) return;`, add:

```js
    _activePreset = presetName;
```

Then wrap the EMS-only section — everything from `// Swap candidates to the preset's pre-computed set` through the end of the `if (notify) { ... }` block — in a dataset guard, so it reads:

```js
    if (ACTIVE_DATASET !== 'hospitals') {
        // Swap candidates to the preset's pre-computed set
        if (typeof CANDIDATES_BY_PRESET !== 'undefined' && CANDIDATES_BY_PRESET[presetName]) {
            CANDIDATES = CANDIDATES_BY_PRESET[presetName];
        }

        // Switching presets clears any explicit tier filter but preserves the
        // "show all" view (the default), so all proposed stations stay visible.
        _modelResultFilter = null;

        // Tally this preset's high-priority stations for the notification
        classifyActiveCandidates();
        const highCount = CANDIDATES.filter(c => c._priority === 'High').length;

        // Show notification
        const notify = document.getElementById('preset-notify');
        if (notify) {
            const labels = { balanced: 'Balanced', access: 'Access Focus', population: 'Population Focus' };
            notify.textContent = labels[presetName] + ' — ' + highCount +
                ' high-priority station' + (highCount !== 1 ? 's' : '');
            notify.classList.remove('preset-notify-fade');
            void notify.offsetWidth; // force reflow
            notify.classList.add('preset-notify-fade');
        }
    }
```

Leave the trailing `recomputeAhpScores(); renderCandidates(); updateCandidateMarkers();` outside the guard (all three are hospital-safe; `renderCandidates`/`updateCandidateMarkers` are no-ops without EMS candidates).

The existing slider-value and pct-label loops above the guard stay as they are — the hospital expander's sliders/pcts now exist, so they get set; the chip-styling loop (`preset-btn-active`) also works for the 4 hospital buttons.

- [ ] **Step 2: Commit**

```bash
git add templates/phase1_ahp_dashboard.js
git commit -m "feat(model): applyPreset skips EMS-only candidate swap/notify for hospitals"
```

---

### Task 5: CSS — formula row, chip, and expander styles

**Files:**
- Modify: `templates/phase1_ahp_dashboard.css` (append to the `COMPACT MODEL SETUP (hospitals)` section, after `.model-compact-reset a:hover`)

- [ ] **Step 1: Add the styles**

After the line `.model-compact-reset a:hover { color: var(--text-2); text-decoration: underline; }`, add:

```css
.model-formula-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 0 4px;
    margin-top: 4px;
    border-top: 1px solid var(--border-1);
    cursor: help;
}

.model-formula-text {
    flex: 1;
    font-size: 11px;
    color: var(--text-dim);
    line-height: 1.5;
}

.model-formula-text b { color: var(--text-2); font-weight: 600; }

.model-formula-chip {
    flex-shrink: 0;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-2);
    background: var(--bg-panel);
    border: 1px solid var(--border-2);
    padding: 2px 8px;
    border-radius: 10px;
}

.model-weights-details summary {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-mute);
    cursor: pointer;
    padding: 4px 0;
    list-style: none;
}

.model-weights-details summary::-webkit-details-marker { display: none; }

.model-weights-details summary::before {
    content: '\25B8';
    display: inline-block;
    margin-right: 6px;
    transition: transform 0.15s;
}

.model-weights-details[open] summary::before { transform: rotate(90deg); }

.model-weights-details summary:hover { color: var(--text-2); }
```

- [ ] **Step 2: Commit**

```bash
git add templates/phase1_ahp_dashboard.css
git commit -m "style(model): formula line, preset chip, and weights-expander styles"
```

---

### Task 6: Rebuild + manual verification (spec §Testing)

**Files:**
- Output: `data/phase1_ahp_dashboard.html` (generated)

- [ ] **Step 1: Rebuild the dashboard (~5 min — loads a 360 MB road graph)**

Run: `cd "/Users/apple/Desktop/EMS project" && venv/bin/python scripts/phase1_ahp_explore.py 2>&1 | tail -3`
Expected: `Dashboard saved to: /Users/apple/Desktop/EMS project/data/phase1_ahp_dashboard.html`

- [ ] **Step 2: Open and verify in the browser**

Run: `open "/Users/apple/Desktop/EMS project/data/phase1_ahp_dashboard.html"`

Checklist (user confirms visually):
1. Hospitals → Model: formula line reads **30% travel · 30% density · 25% exposure · 15% beds** with a `Balanced` chip; "Customize weights" is collapsed; gap cards visible below.
2. Expand → drag a weight slider → percentages and formula update live, chip flips to `Custom`, no preset chip highlighted, map colors + Overall-priority card update, no gap card pops open.
3. Click **Capacity** → sliders jump to 15/15/20/50, chip shows `Capacity`, ranking reshuffles toward low-beds districts (Akkar/Baalbek stay high).
4. "Reset to defaults" → thresholds, weights, chip (`Balanced`), and formula all restore; no "high-priority stations" toast appears.
5. EMS regression: switch Dataset → EMS Stations → Model tab shows the old layout (results first, full Criterion Weights block, 3 presets, station notification on preset click). No formula line.

- [ ] **Step 3: Fix anything the checklist catches, then final commit**

```bash
git add -A data/phase1_ahp_dashboard.html templates/ scripts/
git commit -m "feat(model): merged setup + customizable weights on hospital Model tab"
```
