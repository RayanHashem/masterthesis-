# Hospital Model Tab — Merged Setup + Criterion Weights

**Date:** 2026-06-12
**Branch:** `phase2-hospitals`
**Scope:** Hospital Model tab only. EMS Model tab is untouched.

## Problem

The hospital Model tab's "Overall priority" gap card says districts are ranked
"by your weights", but the Criterion Weights UI was removed from the hospital
view — weights are fixed at the Python defaults and the user cannot see or
change them. The user should be able to (a) understand at a glance what the
priority score is made of, and (b) optionally do their own setup — thresholds
*and* weights — without the setup section growing tall again (the gap results
must stay above the fold).

## Design (Option A — progressive disclosure)

### 1. Formula line (always visible)

Inside the existing compact setup card, below the two slider rows, separated by
a thin divider:

> Priority formula: **30% travel · 30% density · 25% exposure · 15% beds** — `Balanced`

- Percentages come from the live normalized weights.
- Criterion → plain word mapping: `access_gap` → travel, `pop_density` →
  density, `exposed_pop` → exposure, `bed_gap` → beds.
- The trailing chip shows the active preset name (Balanced / Access /
  Population / Capacity) or `Custom` once the user moves a weight slider.

### 2. "Customize weights" expander

A `<details class="...">` element directly under the formula line (same
expand/collapse interaction as the gap cards), **collapsed by default**:

- **Preset chips:** Balanced · Access · Population · **Capacity** (new).
  Clicking a chip sets the four sliders to the preset, recomputes, and marks
  the chip active.
- **4 editable weight sliders** (one per hospital criterion, labels + live %
  readout). Today's sliders are rendered `disabled`; they become editable.
  Moving any slider renormalizes all weights, recomputes scores / map colors /
  gap cards via the existing `recomputeAhpScores()`, clears the active chip,
  and sets the formula chip to `Custom`.

### 3. New "Capacity" preset (Python)

Added to `datasets_obj['hospitals']['presets']` in `phase1_ahp_explore.py`:

```python
'capacity': {'access_gap': 0.15, 'pop_density': 0.15, 'exposed_pop': 0.20, 'bed_gap': 0.50}
```

EMS presets unchanged (no `capacity` preset for EMS).

### 4. Plumbing changes (JS template)

- `renderModelTab()` (hospital branch): render formula line + expander with
  editable sliders inside the compact setup card.
- `applyPreset()`: when `ACTIVE_DATASET === 'hospitals'`, skip the EMS-only
  candidate swap (`CANDIDATES_BY_PRESET`) and the "N high-priority stations"
  notification; still set sliders, recompute, and update chip/formula state.
- `recomputeAhpScores()`: already reads `weight-<id>` sliders with a default
  fallback — no change to the math.
- `_updateWeightDisplay(normW)`: extended to also update the formula line and
  `Custom`/preset chip (all DOM lookups guarded, so the EMS view — which has
  its own pct/bar elements — is unaffected).
- `resetModelDefaults()`: already resets weights, threshold, and benchmark;
  additionally restores the Balanced chip and formula line. For hospitals it
  must not trigger the EMS notification (covered by the `applyPreset` guard).

### 5. Unchanged

- EMS Model tab (weights UI, presets, notifications, candidate swapping).
- Gap-card math (`computeHospitalGaps`) and the gap-card markup.
- The compact two-row slider layout and the "Reset to defaults" link.
- "by your weights" wording in the priority card — now literally true.

## Error handling / edge cases

- All weight sliders at 0 → existing fallback in `recomputeAhpScores()`
  (treats all weights as 1).
- Dataset switch re-renders the Model tab → expander resets to collapsed,
  Balanced preset restored (existing `setActiveDataset` flow).
- Slider moves re-render only the results section, not the setup card, so the
  expander's open state survives weight adjustments.

## Testing

Manual, after `python scripts/phase1_ahp_explore.py`:

1. Hospitals → Model: formula line shows 30/30/25/15 + `Balanced`; expander
   collapsed.
2. Expand → move a slider → formula updates, chip flips to `Custom`, gap
   cards + map recolor live, no card pops open.
3. Click Capacity preset → bed-heavy ranking (Akkar/Baalbek stay high), chip
   shows `Capacity`.
4. Reset to defaults → Balanced restored everywhere.
5. EMS regression: Model tab renders exactly as before (weights block,
   presets, station notification all intact).
