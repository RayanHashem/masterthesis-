// ============================================================================
// Lebanon EMS Dashboard – Client-side logic
// Data constants (DISTRICTS, STATIONS, GOVERNORATES, MAX_POP, LEBANON_BOUNDS, CANDIDATES)
// are injected by Python above this script block.
// ============================================================================

let map = null;
let districtLayersByName = {};
let highlightTimeout = null;
let candidateHighlightCircle = null;
let candidatesLayer = null;       // direct ref to the Folium FeatureGroup
let candidatesVisible = true;     // tracks current state

function formatNum(n) {
    return n.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

// ── TABS ──────────────────────────────────────────────────────────────────────
function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.tab === tabId));
    document.querySelectorAll('.tab-panel').forEach(p =>
        p.classList.toggle('active', p.id === 'tab-' + tabId));
}

// ── SIDEBAR TOGGLE ────────────────────────────────────────────────────────────
function togglePanel() {
    const container = document.querySelector('.container');
    const btn = document.getElementById('panel-toggle-btn');
    const collapsed = container.classList.toggle('panel-collapsed');
    btn.textContent = collapsed ? '\u2039' : '\u203a';
    setTimeout(() => { if (map && map.invalidateSize) map.invalidateSize(); }, 320);
}

// ── FILTERS ───────────────────────────────────────────────────────────────────
function getFilteredDistricts() {
    const govEl  = document.getElementById('filter-governorate');
    const gov    = govEl ? govEl.value : '';
    const searchEl = document.getElementById('district-search');
    const search = searchEl ? searchEl.value.toLowerCase().trim() : '';
    return DISTRICTS.filter(d => {
        if (gov && d.governorate !== gov) return false;
        if (search && !d.district_name.toLowerCase().includes(search)) return false;
        return true;
    });
}

// ── AHP SUMMARY CARDS ─────────────────────────────────────────────────────────
function renderAhpSummary(filtered) {
    const counts = { High: 0, Medium: 0, Low: 0 };
    filtered.forEach(d => { if (counts[d.ahp_priority] !== undefined) counts[d.ahp_priority]++; });
    const cards = [
        { label: 'High Priority',   count: counts.High,   color: '#e74c3c' },
        { label: 'Medium Priority', count: counts.Medium, color: '#f39c12' },
        { label: 'Low Priority',    count: counts.Low,    color: '#27ae60' },
    ];
    document.getElementById('ahp-summary-cards').innerHTML = cards.map(c =>
        `<div class="stat-card" style="border-color:${c.color}">
            <div class="label">${c.label}</div>
            <div class="value" style="color:${c.color}">${c.count}</div>
        </div>`
    ).join('');
}

// ── AHP RANKING TABLE (with score bars) ───────────────────────────────────────
function renderAhpRanking(filtered) {
    const limitEl  = document.getElementById('ahp-ranking-limit');
    const limitVal = limitEl ? limitEl.value : '10';
    const sorted   = [...filtered].sort((a, b) => b.ahp_score - a.ahp_score);
    const rows     = limitVal === 'all' ? sorted : sorted.slice(0, parseInt(limitVal, 10));
    const maxScore = DISTRICTS.reduce((m, d) => Math.max(m, d.ahp_score), 0) || 1;

    if (rows.length === 0) {
        document.getElementById('ahp-ranking-table').innerHTML =
            '<div class="empty-section">No districts match filters</div>';
        return;
    }

    const priorityColor = { High: '#e74c3c', Medium: '#f39c12', Low: '#27ae60' };
    const priorityClass = { High: 'ahp-priority-high', Medium: 'ahp-priority-medium', Low: 'ahp-priority-low' };

    let html = `<table class="ahp-ranking-table"><thead><tr>
        <th>#</th><th>District</th><th>Priority</th><th>Score</th>
    </tr></thead><tbody>`;

    rows.forEach((d, i) => {
        const cls      = priorityClass[d.ahp_priority] || 'ahp-priority-low';
        const barColor = priorityColor[d.ahp_priority] || '#27ae60';
        const pct      = Math.round((d.ahp_score / maxScore) * 100);
        const safeName = d.district_name.replace(/"/g, '&quot;');
        html += `<tr data-district-name="${safeName}">
            <td style="color:#666">${i + 1}</td>
            <td>${d.district_name}</td>
            <td class="${cls}">${d.ahp_priority}</td>
            <td class="score-bar-cell">
                <div class="score-bar-wrap">
                    <div class="score-bar-bg">
                        <div class="score-bar-fill" style="width:${pct}%;background:${barColor}"></div>
                    </div>
                    <span class="score-bar-val">${d.ahp_score.toFixed(3)}</span>
                </div>
            </td>
        </tr>`;
    });
    html += '</tbody></table>';
    document.getElementById('ahp-ranking-table').innerHTML = html;

    document.querySelectorAll('#ahp-ranking-table tr[data-district-name]').forEach(row => {
        row.addEventListener('click', () => onDistrictCardClick(row.dataset.districtName));
    });
}

// ── CANDIDATES ────────────────────────────────────────────────────────────────
function _getCurrentThreshold() {
    const el = document.getElementById('coverage-threshold');
    return el ? parseFloat(el.value) : (typeof DEFAULT_COVERAGE_THRESHOLD !== 'undefined' ? DEFAULT_COVERAGE_THRESHOLD : 10);
}

function isCandidateCovered(c, threshold) {
    return c.mean_travel_time !== null && c.mean_travel_time !== undefined && c.mean_travel_time < threshold;
}

function haversineKm(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const toRad = d => d * Math.PI / 180;
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a = Math.sin(dLat / 2) ** 2 +
        Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function nearestStationToCandidate(c) {
    if (!Array.isArray(STATIONS) || STATIONS.length === 0) return null;
    let best = null;
    STATIONS.forEach(s => {
        const km = haversineKm(c.lat, c.lon, s.lat, s.lon);
        if (!best || km < best.distance_km) best = { ...s, distance_km: km };
    });
    return best;
}

function candidatePlacementAssessment(c) {
    const nearest = nearestStationToCandidate(c);
    const gov = nearest ? nearest.governorate : '';
    const urban = ['Beirut', 'Mount Lebanon', 'MountLebanon'].includes((gov || '').replace(/\s/g, ''));
    const minSpacing = urban ? 1.5 : 5.0;
    const distance = nearest ? nearest.distance_km : null;
    let status = 'spacing-ok';
    let label = 'Spacing OK';
    if (distance !== null && distance < minSpacing * 0.75) {
        status = 'spacing-fail';
        label = 'Too close';
    } else if (distance !== null && distance < minSpacing) {
        status = 'spacing-review';
        label = 'Review spacing';
    }
    return { nearest, urban, minSpacing, distance, status, label };
}

function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text);
        return;
    }
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
}

function copyCandidateCoords(rank, lat, lon) {
    copyText(`${lat.toFixed(5)}, ${lon.toFixed(5)}`);
    const btn = document.querySelector(`[data-copy-rank="${rank}"]`);
    if (!btn) return;
    const old = btn.textContent;
    btn.textContent = 'Copied';
    setTimeout(() => { btn.textContent = old; }, 1200);
}

function askCopilotAboutCandidate(rank, lat, lon) {
    openCopilotWith(`Assess placement in ${lat.toFixed(5)}, ${lon.toFixed(5)} for proposed EMS station #${rank}.`, true);
}

function renderCandidates() {
    const candidates = (typeof CANDIDATES !== 'undefined' && Array.isArray(CANDIDATES)) ? CANDIDATES : [];
    const limitEl    = document.getElementById('candidates-limit');
    const limitVal   = limitEl ? limitEl.value : '10';
    const n          = limitVal === 'all' ? candidates.length : Math.min(candidates.length, parseInt(limitVal, 10) || 10);
    const topN       = candidates.slice(0, n);
    const threshold  = _getCurrentThreshold();

    const listEl = document.getElementById('candidates-list');
    if (!listEl) return;

    if (candidates.length === 0) {
        listEl.innerHTML = '<div class="empty-section">No candidate stations computed</div>';
        return;
    }

    const standardsHtml = `
        <div class="decision-standards-card">
            <b>Placement screen:</b> candidates are ranked by hotspot population and AHP score.
            Spacing uses transparent demo thresholds: 1.5 km urban, 5 km rural. Lebanese public rules do not codify EMS base spacing; licensing remains under MoPH Decision 473/2021.
            <div style="margin-top:8px;">
                <button class="mini-action-btn" type="button" id="assess-custom-location">Assess custom location</button>
            </div>
        </div>`;

    listEl.innerHTML = standardsHtml + topN.map(c => {
        const covered = isCandidateCovered(c, threshold);
        const tt = c.mean_travel_time != null ? c.mean_travel_time.toFixed(1) : 'N/A';
        const assessment = candidatePlacementAssessment(c);
        const nearestText = assessment.nearest
            ? `${assessment.distance.toFixed(2)} km to nearest EMS`
            : 'Nearest EMS unavailable';
        const spacingText = `${assessment.minSpacing.toFixed(1)} km ${assessment.urban ? 'urban' : 'rural'} spacing`;
        return `<div class="candidate-card${covered ? ' candidate-covered' : ''}" data-lat="${c.lat}" data-lon="${c.lon}">
            <div class="candidate-card-top">
                <span class="candidate-rank-badge">#${c.rank}</span>
                ${covered
                    ? `<span class="candidate-status covered">✓ Now covered at ${threshold} min</span>`
                    : `<span class="candidate-status needed">Still needed</span>`}
                <span class="candidate-status ${assessment.status}">${assessment.label}</span>
            </div>
            <div class="candidate-card-meta">
                <span class="candidate-metric">Avg travel: <b>${tt} min</b></span>
                <span class="candidate-metric">Uncovered pop: <b>${formatNum(c.uncovered_population || 0)}</b></span>
                <span class="candidate-metric">Score: ${(c.mean_score || 0).toFixed(3)}</span>
            </div>
            <div class="candidate-decision">
                <span>Spacing</span><b>${spacingText}</b>
                <span>Nearest</span><b>${nearestText}</b>
                <span>Coords</span><b>${c.lat.toFixed(5)}, ${c.lon.toFixed(5)}</b>
            </div>
            <div class="candidate-actions">
                <button class="candidate-action-btn" type="button"
                    onclick="event.stopPropagation(); onCandidateCardClick(${c.lat}, ${c.lon})">Zoom</button>
                <button class="candidate-action-btn" type="button" data-copy-rank="${c.rank}"
                    onclick="event.stopPropagation(); copyCandidateCoords(${c.rank}, ${c.lat}, ${c.lon})">Copy coords</button>
                <button class="candidate-action-btn" type="button"
                    onclick="event.stopPropagation(); askCopilotAboutCandidate(${c.rank}, ${c.lat}, ${c.lon})">Ask Copilot</button>
            </div>
        </div>`;
    }).join('');

    listEl.querySelectorAll('.candidate-card').forEach(card => {
        card.addEventListener('click', () =>
            onCandidateCardClick(parseFloat(card.dataset.lat), parseFloat(card.dataset.lon)));
    });
    const customBtn = document.getElementById('assess-custom-location');
    if (customBtn) customBtn.addEventListener('click', () => openCopilotWith('Assess placement in ', false));
}

/** Dims candidate markers on the map when their cluster is now covered by the threshold. */
function updateCandidateMarkers() {
    if (!candidatesLayer) return;
    const threshold = _getCurrentThreshold();
    candidatesLayer.eachLayer(layer => {
        const c = layer._candidateData;
        if (!c) return;
        const covered = isCandidateCovered(c, threshold);
        if (layer.setOpacity) {
            // Marker
            layer.setOpacity(covered ? 0.25 : 1);
        } else if (layer.setStyle) {
            // Circle ring
            layer.setStyle({
                opacity:     covered ? 0.15 : 0.8,
                fillOpacity: covered ? 0.02 : 0.07,
                dashArray:   covered ? '4 4' : '6 4',
            });
        }
    });
}

// ── CANDIDATE CLICK ───────────────────────────────────────────────────────────
function onCandidateCardClick(lat, lon) {
    if (!map) return;
    if (highlightTimeout) clearTimeout(highlightTimeout);
    if (candidateHighlightCircle) {
        map.removeLayer(candidateHighlightCircle);
        candidateHighlightCircle = null;
    }
    map.setView([lat, lon], 13);
    candidateHighlightCircle = L.circle([lat, lon], {
        radius: 800, color: '#00cec9', fillColor: '#00cec9', fillOpacity: 0.2, weight: 2
    });
    candidateHighlightCircle.addTo(map);
    highlightTimeout = setTimeout(() => {
        if (candidateHighlightCircle && map.hasLayer(candidateHighlightCircle))
            map.removeLayer(candidateHighlightCircle);
        candidateHighlightCircle = null;
        highlightTimeout = null;
    }, 2500);
}

// ── CANDIDATES LAYER TOGGLE ───────────────────────────────────────────────────
function setCandidatesLayerVisible(show) {
    if (!map || !candidatesLayer) return;
    if (show && !map.hasLayer(candidatesLayer))  map.addLayer(candidatesLayer);
    if (!show && map.hasLayer(candidatesLayer))  map.removeLayer(candidatesLayer);
    candidatesVisible = show;
    const btn = document.getElementById('candidates-map-toggle');
    if (btn) btn.classList.toggle('active', show);
    _syncCandidatesFilterCheckbox(show);
}

function toggleCandidatesLayer() {
    setCandidatesLayerVisible(!candidatesVisible);
}

function initCandidatesLayer() {
    if (!map || typeof CANDIDATES === 'undefined' || !CANDIDATES.length) return;

    // Folium doesn't set options.name on FeatureGroups — find candidates layer
    // by checking if any sub-layer matches a known candidate coordinate.
    const ref = CANDIDATES[0];
    map.eachLayer(l => {
        if (candidatesLayer) return;
        if (typeof l.eachLayer !== 'function') return;
        l.eachLayer(subl => {
            if (candidatesLayer) return;
            const ll = subl.getLatLng ? subl.getLatLng() : null;
            if (ll && Math.abs(ll.lat - ref.lat) < 0.001 && Math.abs(ll.lng - ref.lon) < 0.001)
                candidatesLayer = l;
        });
    });

    // Attach candidate data to each individual sub-layer for threshold logic
    if (candidatesLayer) {
        candidatesLayer.eachLayer(layer => {
            const ll = layer.getLatLng ? layer.getLatLng() : null;
            if (!ll) return;
            const match = CANDIDATES.find(c =>
                Math.abs(c.lat - ll.lat) < 0.001 && Math.abs(c.lon - ll.lng) < 0.001
            );
            if (match) layer._candidateData = match;
        });
    }

    const isOn = candidatesLayer ? map.hasLayer(candidatesLayer) : false;
    candidatesVisible = isOn;
    const btn = document.getElementById('candidates-map-toggle');
    if (btn) btn.classList.toggle('active', isOn);
    updateCandidateMarkers();
}

// ── SELECTED DISTRICT CARD ────────────────────────────────────────────────────
function showSelectedDistrictCard(districtName) {
    const d    = DISTRICTS.find(x => x.district_name === districtName);
    const card = document.getElementById('selected-district-card');
    if (!d || !card) return;

    const priorityColor = { High: '#e74c3c', Medium: '#f39c12', Low: '#27ae60' };
    const col = priorityColor[d.ahp_priority] || '#27ae60';

    card.innerHTML = `
        <div class="sdc-title">
            <span>${d.district_name} <small style="color:#aaa;font-weight:400">${d.governorate}</small></span>
            <span class="sdc-close" onclick="hideSelectedDistrictCard()">&times;</span>
        </div>
        <div class="sdc-grid">
            <div><div class="sdc-label">AHP Score</div><div class="sdc-val" style="color:${col}">${d.ahp_score.toFixed(3)}</div></div>
            <div><div class="sdc-label">Priority</div><div class="sdc-val" style="color:${col}">${d.ahp_priority}</div></div>
            <div><div class="sdc-label">Population</div><div class="sdc-val">${formatNum(Math.round(d.population))}</div></div>
            <div><div class="sdc-label">EMS Stations</div><div class="sdc-val">${d.stations}</div></div>
            <div><div class="sdc-label">Area km\u00b2</div><div class="sdc-val">${d.area_km2.toFixed(0)}</div></div>
            <div><div class="sdc-label">Density /km\u00b2</div><div class="sdc-val">${d.pop_density.toFixed(0)}</div></div>
        </div>`;
    card.style.display = 'block';
}

function hideSelectedDistrictCard() {
    const card = document.getElementById('selected-district-card');
    if (card) card.style.display = 'none';
}

// ── LIVE MODEL ────────────────────────────────────────────────────────────────

const _SEG_COLORS = ['#ffffff', '#b5b5b5', '#6e6e6e', '#d8d8d8', '#8a8a8a'];
const _PRIORITY_FILL   = { High: '#e74c3c', Medium: '#f39c12', Low: '#27ae60' };
let _modelResultFilter = null; // null = show top 5 all; 'High'/'Medium'/'Low' = filter

/** Called once at init — derives/stores per-district normalised scores. */
function initModelNormScores() {
    // Use Python-shipped values when available; otherwise compute from raw data.
    const popDensities = DISTRICTS.map(d => d.pop_density);
    const exposedPops  = DISTRICTS.map(d => d.exposed_population);
    const minPD = Math.min(...popDensities), maxPD = Math.max(...popDensities);
    const minEP = Math.min(...exposedPops),  maxEP = Math.max(...exposedPops);

    const defaultW = {};
    CRITERIA_CONFIG.forEach(c => { defaultW[c.id] = c.weight; });
    const wTotal = Object.values(defaultW).reduce((a, b) => a + b, 0) || 1;

    DISTRICTS.forEach(d => {
        if (d.norm_pop_density === undefined)
            d.norm_pop_density = maxPD > minPD ? (d.pop_density - minPD) / (maxPD - minPD) : 0;
        if (d.norm_exposed_pop === undefined)
            d.norm_exposed_pop = maxEP > minEP ? (d.exposed_population - minEP) / (maxEP - minEP) : 0;

        // Derive norm_access_gap algebraically from the default-weight score if Python didn't ship it
        if (d.norm_access_gap === undefined) {
            const w1 = defaultW['access_gap'] / wTotal;
            const w2 = defaultW['pop_density'] / wTotal;
            const w3 = defaultW['exposed_pop'] / wTotal;
            d.norm_access_gap = w1 > 0
                ? Math.max(0, Math.min(1, (d.ahp_score - w2 * d.norm_pop_density - w3 * d.norm_exposed_pop) / w1))
                : 0;
        }

        // Store originals so Reset always works
        d._orig_ahp_score      = d.ahp_score;
        d._orig_ahp_priority   = d.ahp_priority;
        d._orig_norm_exposed   = d.norm_exposed_pop;
    });
}

/** Reads sliders → renormalises weights → recomputes scores + priorities → re-renders. */
function recomputeAhpScores() {
    // --- 1. Read weights from sliders ---
    let rawWeights = {};
    let rawTotal = 0;
    CRITERIA_CONFIG.forEach(c => {
        const el = document.getElementById('weight-' + c.id);
        const v  = el ? Math.max(0, parseFloat(el.value) || 0) : c.weight;
        rawWeights[c.id] = v;
        rawTotal += v;
    });
    if (rawTotal === 0) { CRITERIA_CONFIG.forEach(c => { rawWeights[c.id] = 1; rawTotal++; }); }
    const normW = {};
    CRITERIA_CONFIG.forEach(c => { normW[c.id] = rawWeights[c.id] / rawTotal; });

    // --- 2. Coverage threshold → recompute exposed_pop norm if travel times available ---
    const threshEl = document.getElementById('coverage-threshold');
    const threshold = threshEl ? parseFloat(threshEl.value) : (typeof DEFAULT_COVERAGE_THRESHOLD !== 'undefined' ? DEFAULT_COVERAGE_THRESHOLD : 10);
    const hasTT = DISTRICTS.length > 0 && DISTRICTS[0].min_travel_time_min !== undefined && DISTRICTS[0].min_travel_time_min !== null;
    if (hasTT) {
        const raws = DISTRICTS.map(d => (d.min_travel_time_min !== null && d.min_travel_time_min > threshold) ? d.population : 0);
        const minR = Math.min(...raws), maxR = Math.max(...raws);
        DISTRICTS.forEach((d, i) => {
            d.norm_exposed_pop = maxR > minR ? (raws[i] - minR) / (maxR - minR) : 0;
        });
    }

    // --- 3. Compute new AHP score per district ---
    DISTRICTS.forEach(d => {
        d.ahp_score = 0;
        CRITERIA_CONFIG.forEach(c => {
            d.ahp_score += normW[c.id] * (d['norm_' + c.id] || 0);
        });
        d.ahp_score = Math.round(d.ahp_score * 1000) / 1000;
    });

    // --- 4. Quantile-based priority classification ---
    const highPctEl = document.getElementById('threshold-high');
    const medPctEl  = document.getElementById('threshold-medium');
    const highPct   = highPctEl ? parseInt(highPctEl.value) / 100 : 0.20;
    const medPct    = medPctEl  ? parseInt(medPctEl.value)  / 100 : 0.50;
    const sorted    = [...DISTRICTS].map(d => d.ahp_score).sort((a, b) => a - b);
    const qHigh     = sorted[Math.max(0, Math.floor(sorted.length * (1 - highPct)))];
    const qMed      = sorted[Math.max(0, Math.floor(sorted.length * (1 - medPct)))];
    DISTRICTS.forEach(d => {
        if      (d.ahp_score >= qHigh) d.ahp_priority = 'High';
        else if (d.ahp_score >= qMed)  d.ahp_priority = 'Medium';
        else                           d.ahp_priority = 'Low';
    });

    // --- 5. Update everything ---
    applyFilters();
    updateMapDistrictColors();
    _updateWeightDisplay(normW);
    updateCandidateMarkers();
    renderModelResults();
}

/** Updates Leaflet district polygon fill colors to match recomputed priorities. */
function updateMapDistrictColors() {
    if (!map || !districtLayersByName) return;
    DISTRICTS.forEach(d => {
        const layer = districtLayersByName[d.district_name];
        if (!layer || !layer.setStyle) return;
        layer.setStyle({ fillColor: _PRIORITY_FILL[d.ahp_priority] || '#27ae60' });
    });
}

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

/** Updates the Results section inside the Model tab after any recompute. */
function renderModelResults() {
    const el = document.getElementById('model-results-section');
    if (!el) return;

    const counts = { High: 0, Medium: 0, Low: 0 };
    DISTRICTS.forEach(d => { if (counts[d.ahp_priority] !== undefined) counts[d.ahp_priority]++; });
    const hasChanges = DISTRICTS.some(d => d.ahp_priority !== d._orig_ahp_priority || Math.abs(d.ahp_score - d._orig_ahp_score) > 0.001);

    const threshold = _getCurrentThreshold();
    const candidates = (typeof CANDIDATES !== 'undefined' && Array.isArray(CANDIDATES)) ? CANDIDATES : [];
    const neededCount  = candidates.filter(c => !isCandidateCovered(c, threshold)).length;
    const coveredCount = candidates.length - neededCount;

    const sorted = [...DISTRICTS].sort((a, b) => b.ahp_score - a.ahp_score);
    const listDistricts = _modelResultFilter
        ? sorted.filter(d => d.ahp_priority === _modelResultFilter)
        : sorted.slice(0, 5);

    const chips = [
        { key: 'High',   label: 'High',   count: counts.High },
        { key: 'Medium', label: 'Medium', count: counts.Medium },
        { key: 'Low',    label: 'Low',    count: counts.Low },
    ];

    el.innerHTML = `
        <div class="model-results-title">Live Results</div>
        ${candidates.length > 0 ? `
        <div class="model-stations-summary">
            <span class="mss-needed">${neededCount} station${neededCount !== 1 ? 's' : ''} still needed</span>
            ${coveredCount > 0 ? `<span class="mss-covered">${coveredCount} now covered</span>` : ''}
        </div>` : ''}
        <div class="model-results-chips">
            ${chips.map(c => `
                <div class="model-chip ${c.key.toLowerCase()}${_modelResultFilter === c.key ? ' active' : ''}"
                     onclick="_toggleModelFilter('${c.key}')">
                    <div class="model-chip-dot ${c.key.toLowerCase()}"></div>
                    ${c.count} ${c.label}
                </div>`).join('')}
            ${hasChanges ? '<span class="model-changed-badge">&#9679; Modified</span>' : ''}
        </div>
        <div class="model-results-list">
            ${listDistricts.length === 0
                ? `<div style="color:#666;font-size:12px;padding:6px 0">No districts in this tier</div>`
                : listDistricts.map((d, i) => {
                    const cls = d.ahp_priority.toLowerCase();
                    const safeName = d.district_name.replace(/"/g, '&quot;');
                    return `<div class="model-result-row" onclick="onDistrictCardClick('${safeName}')">
                        <span class="model-result-rank">${i + 1}</span>
                        <span class="model-result-name">${d.district_name}</span>
                        <span class="model-result-priority ${cls}">${d.ahp_priority}</span>
                        <span class="model-result-score">${d.ahp_score.toFixed(3)}</span>
                    </div>`;
                }).join('')}
        </div>`;
}

function _toggleModelFilter(priority) {
    _modelResultFilter = (_modelResultFilter === priority) ? null : priority;
    renderModelResults();
}

/** Renders the full Model tab content from CRITERIA_CONFIG. */
function renderModelTab() {
    const panel = document.getElementById('tab-model');
    if (!panel) return;
    const hasTT      = DISTRICTS.length > 0 && DISTRICTS[0].min_travel_time_min !== null && DISTRICTS[0].min_travel_time_min !== undefined;
    const defaultThr = typeof DEFAULT_COVERAGE_THRESHOLD !== 'undefined' ? DEFAULT_COVERAGE_THRESHOLD : 10;

    // ── Results section (populated by renderModelResults after recompute) ──
    let html = `<div class="model-results-section" id="model-results-section"></div>
        <div class="model-setup-label">&#9881; Setup</div>

        <div class="section-header" style="margin-top:10px;">Coverage Threshold</div>
        <div class="${hasTT ? '' : 'model-disabled'}">
            <div class="model-desc">Districts are "exposed" if travel time to nearest station exceeds this value.</div>
            ${!hasTT ? '<div class="model-note">&#9888; Re-run the Python script to enable live threshold control.</div>' : ''}
            <div class="model-slider-row">
                <input type="range" id="coverage-threshold" class="filter-slider"
                    min="5" max="60" step="5" value="${defaultThr}"
                    oninput="document.getElementById('cov-thr-val').textContent=this.value+' min'; recomputeAhpScores()">
                <span class="model-value" id="cov-thr-val">${defaultThr} min</span>
            </div>
        </div>`;

    // ── Criterion weights ──
    html += `
        <div class="section-header" style="margin-top:18px;">Criterion Weights</div>
        <div class="model-note">Set any positive values — automatically normalised to 100%.</div>
        <div class="model-weights-block">`;

    CRITERIA_CONFIG.forEach((c, i) => {
        const defVal = c.weight;
        html += `
            <div class="model-weight-row">
                <div class="model-weight-label-row">
                    <span class="filter-label" style="margin-bottom:0">${c.label}</span>
                    <span class="model-pct" id="pct-${c.id}">—</span>
                </div>
                <div class="model-desc">${c.description}</div>
                <div class="model-slider-row">
                    <input type="range" class="filter-slider" id="weight-${c.id}"
                        min="0" max="1" step="0.05" value="${defVal}"
                        oninput="recomputeAhpScores()">
                </div>
            </div>`;
    });

    html += `
            <div class="model-total-row">
                <span>Effective share</span>
                <span id="model-total-label" class="model-total-ok">100%</span>
            </div>
            <div class="weight-bar-container">`;
    CRITERIA_CONFIG.forEach((c, i) => {
        html += `<div class="weight-bar-seg" id="wbar-${c.id}" title="${c.label}" style="background:${_SEG_COLORS[i % _SEG_COLORS.length]}"></div>`;
    });
    html += `</div></div>`;

    // ── Priority thresholds ──
    html += `
        <div class="section-header" style="margin-top:18px;">Priority Thresholds</div>
        <div class="model-desc">Controls what share of districts fall into each priority tier.</div>
        <div class="filter-group" style="margin-top:10px;">
            <div class="model-weight-label-row">
                <span class="filter-label" style="margin-bottom:0">High priority — top</span>
                <span class="model-value" id="threshold-high-val">20%</span>
            </div>
            <div class="model-slider-row">
                <input type="range" id="threshold-high" class="filter-slider"
                    min="5" max="50" step="5" value="20"
                    oninput="document.getElementById('threshold-high-val').textContent=this.value+'%'; recomputeAhpScores()">
            </div>
        </div>
        <div class="filter-group">
            <div class="model-weight-label-row">
                <span class="filter-label" style="margin-bottom:0">Medium priority — top</span>
                <span class="model-value" id="threshold-medium-val">50%</span>
            </div>
            <div class="model-slider-row">
                <input type="range" id="threshold-medium" class="filter-slider"
                    min="10" max="80" step="5" value="50"
                    oninput="document.getElementById('threshold-medium-val').textContent=this.value+'%'; recomputeAhpScores()">
            </div>
        </div>`;

    // ── Reset + footer ──
    html += `
        <div class="filter-group" style="margin-top:18px;">
            <button onclick="resetModelDefaults()" class="filter-reset-btn">&#8635; Reset to Defaults</button>
        </div>
        <div class="model-footer-note">
            <strong>Updates live:</strong> sidebar ranking, score bars, priority counts, district colors on map.<br>
            <strong>Requires re-run:</strong> grid heatmap layers &amp; coverage polygon.<br>
            Refreshing the page resets all values to defaults.
        </div>`;

    panel.innerHTML = html;
    recomputeAhpScores();
}

/** Resets all model controls and district data to Python-computed defaults. */
function resetModelDefaults() {
    CRITERIA_CONFIG.forEach(c => {
        const el = document.getElementById('weight-' + c.id);
        if (el) el.value = c.weight;
    });
    const defThr = typeof DEFAULT_COVERAGE_THRESHOLD !== 'undefined' ? DEFAULT_COVERAGE_THRESHOLD : 10;
    const thrEl  = document.getElementById('coverage-threshold');
    const thrVal = document.getElementById('cov-thr-val');
    if (thrEl) { thrEl.value = defThr; if (thrVal) thrVal.textContent = defThr + ' min'; }
    const hEl = document.getElementById('threshold-high'),   hVal = document.getElementById('threshold-high-val');
    const mEl = document.getElementById('threshold-medium'), mVal = document.getElementById('threshold-medium-val');
    if (hEl) { hEl.value = 20; if (hVal) hVal.textContent = '20%'; }
    if (mEl) { mEl.value = 50; if (mVal) mVal.textContent = '50%'; }

    // Restore Python-computed originals
    DISTRICTS.forEach(d => {
        d.ahp_score      = d._orig_ahp_score;
        d.ahp_priority   = d._orig_ahp_priority;
        d.norm_exposed_pop = d._orig_norm_exposed;
    });

    applyFilters();
    updateMapDistrictColors();
    const defNormW = {};
    const tot = CRITERIA_CONFIG.reduce((s, c) => s + c.weight, 0) || 1;
    CRITERIA_CONFIG.forEach(c => { defNormW[c.id] = c.weight / tot; });
    _updateWeightDisplay(defNormW);
    renderModelResults();
}

// ── APPLY FILTERS ─────────────────────────────────────────────────────────────
function applyFilters() {
    const filtered      = getFilteredDistricts();
    const filteredNames = new Set(filtered.map(d => d.district_name));

    renderAhpRanking(filtered);
    renderCandidates();

    if (map && districtLayersByName) {
        Object.entries(districtLayersByName).forEach(([name, layer]) => {
            const match = filteredNames.has(name);
            if (layer.setStyle)
                layer.setStyle(match ? { fillOpacity: 0.4, opacity: 0.8 } : { fillOpacity: 0.05, opacity: 0.15 });
            if (layer._path)
                layer._path.style.pointerEvents = match ? 'auto' : 'none';
        });
        STATIONS.forEach(s => {
            if (s.markerRef && s.markerRef._icon) {
                const visible = filteredNames.has(s.district_name);
                s.markerRef._icon.style.opacity = visible ? 1 : 0;
                s.markerRef._icon.style.pointerEvents = visible ? 'auto' : 'none';
            }
        });
    }

    document.getElementById('filtered-out-msg').style.display = 'none';
}

// ── DISTRICT CLICK ────────────────────────────────────────────────────────────
function onDistrictCardClick(districtName) {
    const filtered      = getFilteredDistricts();
    const filteredNames = new Set(filtered.map(d => d.district_name));

    if (!filteredNames.has(districtName)) {
        const msg = document.getElementById('filtered-out-msg');
        msg.textContent = 'This district is currently filtered out.';
        msg.style.display = 'block';
        setTimeout(() => { msg.style.display = 'none'; }, 3000);
        return;
    }

    const layer = districtLayersByName[districtName];
    if (!layer || !map) return;
    if (highlightTimeout) clearTimeout(highlightTimeout);

    const bounds = layer.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 12 });
    layer.setStyle({ fillOpacity: 0.6, opacity: 1, weight: 3 });
    layer.bringToFront();
    if (layer.openPopup) layer.openPopup();
    showSelectedDistrictCard(districtName);

    highlightTimeout = setTimeout(() => {
        const filteredNames2 = new Set(getFilteredDistricts().map(d => d.district_name));
        const match = filteredNames2.has(districtName);
        layer.setStyle(match ? { fillOpacity: 0.4, opacity: 0.8 } : { fillOpacity: 0.05, opacity: 0.15 });
        highlightTimeout = null;
    }, 1200);
}

// ── RESET MAP VIEW ────────────────────────────────────────────────────────────
function resetMapView() {
    if (highlightTimeout) { clearTimeout(highlightTimeout); highlightTimeout = null; }
    hideSelectedDistrictCard();
    if (map) {
        map.fitBounds(LEBANON_BOUNDS);
        const filteredNames = new Set(getFilteredDistricts().map(d => d.district_name));
        Object.entries(districtLayersByName).forEach(([name, layer]) => {
            const match = filteredNames.has(name);
            if (layer.setStyle)
                layer.setStyle(match ? { fillOpacity: 0.4, opacity: 0.8 } : { fillOpacity: 0.05, opacity: 0.15 });
            if (layer._path)
                layer._path.style.pointerEvents = match ? 'auto' : 'none';
        });
    }
    document.getElementById('filtered-out-msg').style.display = 'none';
}

// ── BIND MAP DISTRICT CLICKS ──────────────────────────────────────────────────
function bindMapDistrictClick() {
    if (!map) return;
    map.eachLayer(l => {
        if (l.eachLayer) {
            l.eachLayer(subl => {
                if (subl.feature && subl.feature.properties && subl.feature.properties.NAME_2) {
                    subl.on('click', () => showSelectedDistrictCard(subl.feature.properties.NAME_2));
                }
            });
        }
    });
}

// ── MAP LAYER FILTERS ─────────────────────────────────────────────────────────

/** Finds Folium's layer_control_*_layers overlays object regardless of hash. */
function _getFoliumOverlays() {
    for (const key of Object.keys(window)) {
        if (key.startsWith('layer_control_') && key.endsWith('_layers')) {
            const obj = window[key];
            if (obj && obj.overlays) return obj.overlays;
        }
    }
    return null;
}

const _LAYER_META = {
    'District Boundaries':           { color: '#4a9eff', desc: 'District polygon outlines' },
    'Existing EMS':                  { color: '#e74c3c', desc: 'Current EMS station locations' },
    'Population Heatmap':            { color: '#f39c12', desc: 'Population density heat map' },
    '10-Min Coverage (Road Time)':   { color: '#e74c3c', desc: 'Areas within 10-min drive of a station' },
    'AHP Priority (District Level)': { color: '#9b59b6', desc: 'District fill colored by AHP priority' },
    'Grid AHP Priority (High+Medium)': { color: '#e67e22', desc: 'High & medium priority 1km grid cells' },
    'Grid AHP Priority (Low)':       { color: '#27ae60', desc: 'Low priority 1km grid cells' },
    'Suggested New EMS Stations':    { color: '#00cec9', desc: 'Proposed new station locations' },
};

function renderFiltersTab() {
    const panel = document.getElementById('tab-filters');
    if (!panel || !map) return;

    const overlays = _getFoliumOverlays();
    if (!overlays) {
        panel.innerHTML = '<div class="empty-section">Map layers not yet loaded — try switching to this tab after the map loads.</div>';
        return;
    }

    const entries = Object.entries(overlays);

    panel.innerHTML = `
        <div class="section-header">Map Layers</div>
        <div class="filter-desc-note">Toggle layers on or off. Changes are visible on the map immediately.</div>
        <div class="filter-layers-list">
            ${entries.map(([name, layer]) => {
                const meta  = _LAYER_META[name] || { color: '#aaa', desc: '' };
                const id    = 'flayer-' + name.replace(/[^a-z0-9]/gi, '-').toLowerCase();
                const isOn  = map.hasLayer(layer);
                return `
                <label class="filter-layer-row" for="${id}">
                    <input type="checkbox" class="filter-layer-cb" id="${id}"
                        ${isOn ? 'checked' : ''}
                        data-layer-name="${name.replace(/"/g, '&quot;')}">
                    <span class="filter-layer-indicator" style="background:${meta.color}"></span>
                    <div class="filter-layer-info">
                        <div class="filter-layer-name">${name}</div>
                        ${meta.desc ? `<div class="filter-layer-desc">${meta.desc}</div>` : ''}
                    </div>
                </label>`;
            }).join('')}
        </div>`;

    panel.querySelectorAll('.filter-layer-cb').forEach(cb => {
        cb.addEventListener('change', () => {
            const layer = overlays[cb.dataset.layerName];
            if (!layer) return;
            if (cb.checked) map.addLayer(layer);
            else            map.removeLayer(layer);
            // Keep floating toggle in sync for candidates
            if (cb.dataset.layerName.includes('Suggested New EMS')) {
                candidatesLayer  = layer;
                candidatesVisible = cb.checked;
                const btn = document.getElementById('candidates-map-toggle');
                if (btn) btn.classList.toggle('active', cb.checked);
            }
        });
    });
}

/** Syncs the Filters tab checkbox when the floating button toggles candidates. */
function _syncCandidatesFilterCheckbox(isOn) {
    const cb = document.querySelector('.filter-layer-cb[data-layer-name="Suggested New EMS Stations"]');
    if (cb) cb.checked = isOn;
}

// ── INIT MAP REFS ─────────────────────────────────────────────────────────────
function initMapRefs() {
    const mapDiv = document.querySelector('.map-container .folium-map');
    if (!mapDiv || !mapDiv.id) return;
    map = window[mapDiv.id];
    if (!map) {
        for (const k in window) { if (window[k] instanceof L.Map) { map = window[k]; break; } }
    }
    if (!map) return;

    map.eachLayer(l => {
        if (l.eachLayer) {
            l.eachLayer(subl => {
                if (subl.feature && subl.feature.properties) {
                    const name = subl.feature.properties.NAME_2;
                    if (name) districtLayersByName[name] = subl;
                }
            });
        }
    });

    const tol = 1e-5;
    STATIONS.forEach(s => {
        if (s.markerRef) return;
        map.eachLayer(l => {
            if (l.getLatLng && l._icon) {
                const ll = l.getLatLng();
                if (ll && Math.abs(ll.lat - s.lat) < tol && Math.abs(ll.lng - s.lon) < tol) s.markerRef = l;
            }
        });
    });

    bindMapDistrictClick();
    initCandidatesLayer();
}

// ── INIT ──────────────────────────────────────────────────────────────────────
function initFilters() {
    // Governorate dropdown
    const govSelect = document.getElementById('filter-governorate');
    if (govSelect && Array.isArray(GOVERNORATES)) {
        GOVERNORATES.forEach(g => {
            const opt = document.createElement('option');
            opt.value = g;
            opt.textContent = g;
            govSelect.appendChild(opt);
        });
        govSelect.addEventListener('change', applyFilters);
    }

    // District search
    const searchInput = document.getElementById('district-search');
    if (searchInput) searchInput.addEventListener('input', applyFilters);

    // Ranking limit
    const rankingLimit = document.getElementById('ahp-ranking-limit');
    if (rankingLimit) rankingLimit.addEventListener('change', () => renderAhpRanking(getFilteredDistricts()));

    // Candidates limit
    const candidatesLimit = document.getElementById('candidates-limit');
    if (candidatesLimit) candidatesLimit.addEventListener('change', renderCandidates);

    // Floating candidates toggle button
    const toggleBtn2 = document.getElementById('candidates-map-toggle');
    if (toggleBtn2) toggleBtn2.addEventListener('click', toggleCandidatesLayer);

    // Reset map
    const resetBtn = document.getElementById('reset-map-view');
    if (resetBtn) resetBtn.addEventListener('click', resetMapView);

    // Panel toggle
    const toggleBtn = document.getElementById('panel-toggle-btn');
    if (toggleBtn) toggleBtn.addEventListener('click', togglePanel);

    initMapRefs();
    initModelNormScores();
    renderModelTab();
    renderFiltersTab();
    applyFilters();
    renderCandidates();
}

document.addEventListener('DOMContentLoaded', initFilters);

// =============================================================================
// EMS COPILOT — local-only chat client
// =============================================================================
// Talks to the FastAPI backend at COPILOT_URL. If the backend is offline the
// panel still opens, the indicator turns red, and friendly help text is shown.

const COPILOT_URL = 'http://127.0.0.1:8000';

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function copilotFormat(text) {
    // Minimal, safe markdown: **bold**, `code`, line breaks.
    let out = escapeHtml(text);
    out = out.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
    out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
    out = out.replace(/\n/g, '<br>');
    return out;
}

function appendCopilotMsg(role, html) {
    const body = document.getElementById('copilot-body');
    const wrap = document.createElement('div');
    wrap.className = 'copilot-msg' + (role === 'user' ? ' user' : '');
    wrap.innerHTML =
        (role === 'user'
            ? `<div class="bubble">${html}</div><div class="avatar">YOU</div>`
            : `<div class="avatar">AI</div><div class="bubble">${html}</div>`);
    body.appendChild(wrap);
    body.scrollTop = body.scrollHeight;
    return wrap;
}

async function copilotHealthCheck() {
    const el = document.getElementById('copilot-status');
    if (!el) return;
    const label = el.querySelector('.copilot-status-label');
    try {
        const r = await fetch(COPILOT_URL + '/health', { method: 'GET' });
        if (!r.ok) throw new Error('bad status');
        const j = await r.json();
        el.classList.remove('offline');
        el.classList.add('online');
        if (label) {
            label.textContent = j.ollama
                ? (j.model_pulled ? 'online · LLM ready' : 'online · model missing')
                : 'online · deterministic';
        }
    } catch (e) {
        el.classList.remove('online');
        el.classList.add('offline');
        if (label) label.textContent = 'offline';
    }
}

async function sendCopilotMessage(text) {
    if (!text || !text.trim()) return;
    text = text.trim();
    const input = document.getElementById('copilot-input');
    const send  = document.getElementById('copilot-send');
    appendCopilotMsg('user', escapeHtml(text));
    input.value = '';
    input.disabled = true;
    send.disabled = true;

    const thinking = appendCopilotMsg('ai', '<i style="color:#888">Thinking…</i>');

    try {
        const r = await fetch(COPILOT_URL + '/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, use_llm: true }),
        });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const j = await r.json();
        thinking.querySelector('.bubble').innerHTML = copilotFormat(j.answer || '(no answer)');
    } catch (e) {
        thinking.querySelector('.bubble').innerHTML =
            '<b>Copilot offline.</b><br>Start the backend with <code>run_dashboard.bat</code>, ' +
            'or run <code>uvicorn --app-dir scripts copilot_server:app</code>.<br>' +
            '<span style="color:#777;font-size:11px;">' + escapeHtml(String(e)) + '</span>';
    } finally {
        input.disabled = false;
        send.disabled = false;
        input.focus();
        copilotHealthCheck();
    }
}

function openCopilotWith(text, autoSend) {
    const fab = document.getElementById('copilot-fab');
    const panel = document.getElementById('copilot-panel');
    const input = document.getElementById('copilot-input');
    if (!panel || !input) return;
    panel.classList.add('open');
    if (fab) fab.setAttribute('aria-expanded', 'true');
    copilotHealthCheck();
    input.value = text || '';
    setTimeout(() => {
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
    }, 50);
    if (autoSend) sendCopilotMessage(input.value);
}

function initCopilot() {
    const fab = document.getElementById('copilot-fab');
    const panel = document.getElementById('copilot-panel');
    const closeBtn = document.getElementById('copilot-close');
    const input = document.getElementById('copilot-input');
    const send  = document.getElementById('copilot-send');
    if (!fab || !panel) return;

    fab.addEventListener('click', () => {
        panel.classList.toggle('open');
        fab.setAttribute('aria-expanded', panel.classList.contains('open') ? 'true' : 'false');
        if (panel.classList.contains('open')) {
            copilotHealthCheck();
            setTimeout(() => input.focus(), 50);
        }
    });
    closeBtn.addEventListener('click', () => {
        panel.classList.remove('open');
        fab.setAttribute('aria-expanded', 'false');
    });

    document.querySelectorAll('.copilot-suggestion').forEach(s =>
        s.addEventListener('click', () => sendCopilotMessage(s.textContent)));

    send.addEventListener('click', () => sendCopilotMessage(input.value));
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendCopilotMessage(input.value);
        }
    });

    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            panel.classList.remove('open');
            fab.setAttribute('aria-expanded', 'false');
        }
    });

    copilotHealthCheck();
    // Light periodic re-check while the panel is open.
    setInterval(() => {
        if (panel.classList.contains('open')) copilotHealthCheck();
    }, 15000);
}

document.addEventListener('DOMContentLoaded', initCopilot);
