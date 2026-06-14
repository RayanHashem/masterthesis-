// ============================================================================
// Lebanon EMS Dashboard – Client-side logic
// Data constants (DISTRICTS, STATIONS, GOVERNORATES, MAX_POP, LEBANON_BOUNDS, CANDIDATES)
// are injected by Python above this script block.
// ============================================================================

// ── Phase 2: dataset-backed globals (sourced from the active dataset) ──
let DISTRICTS = DATASETS[ACTIVE_DATASET].districts;
let STATIONS = DATASETS[ACTIVE_DATASET].supply;
let CRITERIA_CONFIG = DATASETS[ACTIVE_DATASET].criteria;
let CANDIDATES_BY_PRESET = DATASETS[ACTIVE_DATASET].candidatesByPreset;
let CANDIDATES = (CANDIDATES_BY_PRESET && CANDIDATES_BY_PRESET.balanced) || [];
let DEFAULT_COVERAGE_THRESHOLD = DATASETS[ACTIVE_DATASET].threshold;

let map = null;
let districtLayersByName = {};
let highlightTimeout = null;
let _activePreset = 'balanced';   // active weight preset; null = user-customized
let _ghostMarker = null;      // indicative demand-center circle (hospitals)
let _haloHospitals = [];      // hospitals currently haloed by an intervention card
let candidateHighlightCircle = null;
let candidatesLayer = null;       // direct ref to the Folium FeatureGroup
let candidatesVisible = true;     // tracks current state
let supplyLayerGroup = null;
let supplyLayerVisible = true;    // Filters-tab toggle for the supply markers (EMS stations / hospitals)
let ahpDistrictFillOn = true;     // Filters-tab toggle: color districts by AHP priority

// Resting fill opacity for a district polygon. When the AHP-fill toggle is off the
// districts show as outlines only (no choropleth color).
function _districtRestOpacity(match) {
    if (!ahpDistrictFillOn) return 0;
    return match ? 0.4 : 0.05;
}

/** Show/hide the AHP priority choropleth fill on the district polygons. */
function setAhpDistrictFill(on) {
    ahpDistrictFillOn = on;
    if (typeof applyFilters === 'function') applyFilters();  // re-applies resting fill opacity
}

function formatNum(n) {
    return n.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

/** Escapes a string for safe use inside a single-quoted inline onclick handler. */
function escJs(s) {
    return String(s).replace(/'/g, "\\'").replace(/"/g, '&quot;');
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

// ── SUMMARY CARDS (per-dataset, swap on toggle) ───────────────────────────────
function renderAhpSummary() {
    const el = document.getElementById('ahp-summary-cards');
    if (!el) return;
    const ds = DATASETS[ACTIVE_DATASET] || {};
    const cards = ds.summary || [];
    el.innerHTML = cards.map(c =>
        `<div class="stat-card" style="border-color:${c.color}">
            <div class="label">${c.label}</div>
            <div class="value" style="color:${c.color}">${c.value}</div>
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

    const isHosp = ACTIVE_DATASET === 'hospitals';
    let html;

    if (isHosp) {
        // ── 3-lens equity diagnostic: Capacity · Access · Affordability ──
        const cap = d => {
            const c = { NEED: ['NEED', '#e74c3c'], ADEQUATE: ['Adequate', '#7f8c8d'], OVERSUPPLIED: ['No need', '#27ae60'] }[d.need_class || 'ADEQUATE'];
            return `<span class="need-badge" style="background:${c[1]}">${c[0]}</span>`;
        };
        const acc = d => {
            const c = { Good: ['Good', '#27ae60'], Fair: ['Fair', '#f39c12'], Poor: ['Poor', '#e74c3c'] }[d.access_class || 'Good'];
            return `<span class="need-badge" style="background:${c[1]}" title="${d.min_travel_time_min != null ? d.min_travel_time_min + ' min to nearest hospital' : ''}">${c[0]}</span>`;
        };
        const aff = d => (d.afford_class === 'none')
            ? `<span class="need-badge" style="background:#e74c3c">No public</span>`
            : `<span class="need-badge" style="background:#27ae60">Public ✓</span>`;
        // Worst-served first: 1 point per failing lens.
        const score = d => (d.need_class === 'NEED' ? 2 : 0)
            + (d.access_class === 'Poor' ? 2 : d.access_class === 'Fair' ? 1 : 0)
            + (d.afford_class === 'none' ? 2 : 0);
        const hrows = [...filtered].sort((a, b) => score(b) - score(a) || a.beds_per_1000 - b.beds_per_1000);
        const shown = limitVal === 'all' ? hrows : hrows.slice(0, parseInt(limitVal, 10));
        html = `<div class="filter-desc-note">Each district graded on three lenses — worst-served first. Click a row for its full profile.</div>
            <table class="ahp-ranking-table"><thead><tr>
            <th>#</th><th>District</th><th>Capacity</th><th>Access</th><th>Affordability</th>
        </tr></thead><tbody>`;
        shown.forEach((d, i) => {
            const safeName = d.district_name.replace(/"/g, '&quot;');
            html += `<tr data-district-name="${safeName}">
                <td style="color:#666">${i + 1}</td>
                <td>${d.district_name}</td>
                <td>${cap(d)}</td><td>${acc(d)}</td><td>${aff(d)}</td>
            </tr>`;
        });
        html += '</tbody></table>';
    } else {
        const priorityColor = { High: '#e74c3c', Medium: '#f39c12', Low: '#27ae60' };
        const priorityClass = { High: 'ahp-priority-high', Medium: 'ahp-priority-medium', Low: 'ahp-priority-low' };
        html = `<table class="ahp-ranking-table"><thead><tr>
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
    }
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
    classifyActiveCandidates();
    const candidates = (typeof CANDIDATES !== 'undefined' && Array.isArray(CANDIDATES)) ? CANDIDATES : [];
    const shown      = _visibleProposed();   // all tiers when "Show all" is on, else active tier
    const limitEl    = document.getElementById('candidates-limit');
    const limitVal   = limitEl ? limitEl.value : '10';
    const n          = limitVal === 'all' ? shown.length : Math.min(shown.length, parseInt(limitVal, 10) || 10);
    const topN       = shown.slice(0, n);
    const threshold  = _getCurrentThreshold();

    const listEl = document.getElementById('candidates-list');
    if (!listEl) return;

    if (candidates.length === 0) {
        listEl.innerHTML = '<div class="empty-section">No candidate stations computed</div>';
        return;
    }

    const tierLabel = _activeDisplayTier().toLowerCase();
    const scopeText = _showAllProposed
        ? `all <b>${candidates.length}</b> proposed stations`
        : `the <b>${tierLabel}-priority</b> proposals for the selected scenario (${shown.length} of ${candidates.length})`;
    const standardsHtml = `
        <div class="decision-standards-card">
            <b>Placement rule:</b> a station is proposed only where a high-density area (≥ 2000 residents/km²) cannot be reached by any existing station within 10 minutes by road. AHP weights only rank these proposals — they do not decide where stations appear.
            The map and list show ${scopeText}.
            Spacing uses transparent demo thresholds: 1.5 km urban, 5 km rural. Lebanese public rules do not codify EMS base spacing; licensing remains under MoPH Decision 473/2021.
            <div style="margin-top:8px;">
                <button class="mini-action-btn" type="button" id="assess-custom-location">Assess custom location</button>
            </div>
        </div>`;

    const emptyNote = topN.length === 0
        ? `<div style="color:#666;font-size:12px;padding:8px 2px">No ${tierLabel}-priority stations under this scenario.</div>`
        : '';

    listEl.innerHTML = standardsHtml + emptyNote + topN.map(c => {
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

/** Single source of truth for which proposed stations are "needed" and how they
 *  are tiered. Tags every active-preset candidate with c._priority (High/Medium/
 *  Low, or null if now covered) using the same AHP-score quantiles as the
 *  district model. Returns the list of still-needed candidates. Because the AHP
 *  scores differ per weight preset, the High tier differs per scenario — which is
 *  what makes each preset surface a different shortlist of stations. */
function classifyActiveCandidates() {
    const threshold = _getCurrentThreshold();
    const cands = (typeof CANDIDATES !== 'undefined' && Array.isArray(CANDIDATES)) ? CANDIDATES : [];
    const needed = cands.filter(c => !isCandidateCovered(c, threshold));

    const highPctEl = document.getElementById('threshold-high');
    const medPctEl  = document.getElementById('threshold-medium');
    const highPct   = highPctEl ? parseInt(highPctEl.value) / 100 : 0.20;
    const medPct    = medPctEl  ? parseInt(medPctEl.value)  / 100 : 0.50;
    const scores = needed.map(s => s.mean_score || 0).sort((a, b) => a - b);
    const m = scores.length;
    const qHigh = m ? scores[Math.max(0, Math.floor(m * (1 - highPct)))] : Infinity;
    const qMed  = m ? scores[Math.max(0, Math.floor(m * (1 - medPct)))]  : Infinity;

    cands.forEach(c => {
        if (isCandidateCovered(c, threshold)) { c._priority = null; return; }
        const sc = c.mean_score || 0;
        c._priority = sc >= qHigh ? 'High' : (sc >= qMed ? 'Medium' : 'Low');
    });
    return needed;
}

/** Which priority tier is shown on the map / candidate list. Defaults to High,
 *  but follows the Model-tab chip filter when the user clicks Medium/Low. */
function _activeDisplayTier() {
    return _modelResultFilter || 'High';
}

/** The proposed stations currently shown on the map + list: every still-needed
 *  station when "Show all" is on, otherwise just the active tier. */
function _visibleProposed() {
    const cands = (typeof CANDIDATES !== 'undefined' && Array.isArray(CANDIDATES)) ? CANDIDATES : [];
    if (_showAllProposed) return cands.filter(c => c._priority);   // all still-needed tiers
    const tier = _activeDisplayTier();
    return cands.filter(c => c._priority === tier);
}

/** Shows the active selection of proposed stations on the map (High tier by
 *  default, the chosen tier when a chip is active, or all when "Show all" is on),
 *  hiding the rest. */
function updateCandidateMarkers() {
    if (!candidatesLayer) return;
    classifyActiveCandidates();           // tag c._priority on the active CANDIDATES
    const showCoords = new Set(
        _visibleProposed().map(c => c.lat.toFixed(5) + ',' + c.lon.toFixed(5))
    );
    candidatesLayer.eachLayer(layer => {
        const c = layer._candidateData;
        if (!c) return;
        const show = showCoords.has(c.lat.toFixed(5) + ',' + c.lon.toFixed(5));
        if (layer.setOpacity) {
            layer.setOpacity(show ? 1 : 0);
        } else if (layer.setStyle) {
            layer.setStyle({
                opacity:     show ? 0.8 : 0,
                fillOpacity: show ? 0.07 : 0,
                dashArray:   '6 4',
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

// Hospital ownership filter: 'all' | 'public' | 'private'
let hospitalTypeFilter = 'all';
const HOSP_COLOR = { public: '#2980b9', private: '#c0392b', unknown: '#7f8c8d' };

function _hospVisible(s) {
    if (hospitalTypeFilter === 'all') return true;
    if (hospitalTypeFilter === 'public') return s.htype === 'public';
    // 'private' includes the untagged/unknown (Lebanon is ~88% private)
    return s.htype !== 'public';
}

function refreshSupplyLayer() {
    if (!map) return;
    if (supplyLayerGroup) { map.removeLayer(supplyLayerGroup); supplyLayerGroup = null; }
    // Dedicated high-z pane so hospital markers sit ABOVE the heatmap & choropleth.
    if (!map.getPane('supplyPane')) {
        map.createPane('supplyPane');
        map.getPane('supplyPane').style.zIndex = 650;
    }
    const isHosp = ACTIVE_DATASET === 'hospitals';
    const list = isHosp ? (STATIONS || []).filter(_hospVisible) : (STATIONS || []);
    const markers = list.map(s => {
        let m;
        if (isHosp) {
            // "H" badge marker, coloured by ownership (public larger/bolder).
            const isPub = s.htype === 'public';
            const sz = isPub ? 22 : 18;
            m = L.marker([s.lat, s.lon], {
                pane: 'supplyPane',
                icon: L.divIcon({
                    className: '',
                    html: `<div class="hosp-marker ${s.htype || 'unknown'}">H</div>`,
                    iconSize: [sz, sz],
                    iconAnchor: [sz / 2, sz / 2],
                }),
            });
            m.on('click', () => showHospitalDetail(s));
            s._mRef = m;
        } else {
            // Red "+" badge to match the map legend (Existing EMS).
            const sz = 18;
            m = L.marker([s.lat, s.lon], {
                pane: 'supplyPane',
                icon: L.divIcon({
                    className: '',
                    html: `<div class="ems-marker">+</div>`,
                    iconSize: [sz, sz],
                    iconAnchor: [sz / 2, sz / 2],
                }),
            });
            m.bindPopup(`<b>EMS Station</b>` + (s.district_name ? `<br>${escapeHtml(s.district_name)}` : ''));
        }
        return m;
    });
    supplyLayerGroup = L.layerGroup(markers);
    if (supplyLayerVisible) supplyLayerGroup.addTo(map);
}

/** Show/hide the supply-marker layer (existing EMS stations / hospitals). */
function setSupplyLayerVisible(show) {
    supplyLayerVisible = show;
    if (!map || !supplyLayerGroup) return;
    if (show && !map.hasLayer(supplyLayerGroup)) map.addLayer(supplyLayerGroup);
    else if (!show && map.hasLayer(supplyLayerGroup)) map.removeLayer(supplyLayerGroup);
}

// ── Hospital click-detail card (bottom-left) ──────────────────────────────────
function showHospitalDetail(s) {
    const card = document.getElementById('hospital-detail-card');
    if (!card) return;
    const typeText = s.htype === 'public' ? 'Public'
        : (s.osrc === 'inferred' ? 'Private (inferred)' : 'Private');
    const badge = `<span class="hdc-badge" style="background:${HOSP_COLOR[s.htype] || '#c0392b'}">${typeText}</span>`;
    const beds = s.beds_estimated ? `${s.beds} <em>(estimated)</em>` : `${s.beds}`;
    const rows = [
        ['Status', badge],
        ['Bed count', beds],
        ['Location', `${s.lat.toFixed(4)}, ${s.lon.toFixed(4)}`],
    ];
    if (s.operator) rows.push(['Operator', escapeHtml(s.operator)]);
    card.innerHTML =
        `<button class="hdc-close" onclick="hideHospitalDetail()" title="Close">&times;</button>`
        + `<div class="hdc-title">${escapeHtml(s.name || 'Unnamed hospital')}</div>`
        + rows.map(([k, v]) => `<div class="hdc-row"><span class="hdc-label">${k}</span><span class="hdc-val">${v}</span></div>`).join('');
    card.style.display = 'block';
}

function hideHospitalDetail() {
    const card = document.getElementById('hospital-detail-card');
    if (card) card.style.display = 'none';
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

    let body;
    if (ACTIVE_DATASET === 'hospitals') {
        // Hospital equity profile: capacity \u00b7 access \u00b7 affordability
        const capC = { NEED: ['NEED', '#e74c3c'], ADEQUATE: ['Adequate', '#7f8c8d'], OVERSUPPLIED: ['No need', '#27ae60'] }[d.need_class || 'ADEQUATE'];
        const accC = { Good: ['Good', '#27ae60'], Fair: ['Fair', '#f39c12'], Poor: ['Poor', '#e74c3c'] }[d.access_class || 'Good'];
        const affOk = d.afford_class !== 'none';
        const tt = d.min_travel_time_min != null ? d.min_travel_time_min + ' min' : '\u2014';
        const priv = (d.total_hospitals || 0) - (d.public_hospitals || 0);
        body = `
        <div class="sdc-grid">
            <div><div class="sdc-label">Capacity</div><div class="sdc-val" style="color:${capC[1]}">${capC[0]}</div></div>
            <div><div class="sdc-label">Access</div><div class="sdc-val" style="color:${accC[1]}">${accC[0]}</div></div>
            <div><div class="sdc-label">Affordability</div><div class="sdc-val" style="color:${affOk ? '#27ae60' : '#e74c3c'}">${affOk ? 'Has public' : 'No public'}</div></div>
            <div><div class="sdc-label">Beds / 1,000</div><div class="sdc-val">${(d.beds_per_1000 || 0).toFixed(1)}</div></div>
            <div><div class="sdc-label">Nearest hospital</div><div class="sdc-val">${tt}</div></div>
            <div><div class="sdc-label">Population</div><div class="sdc-val">${formatNum(Math.round(d.population))}</div></div>
            <div><div class="sdc-label">Public hosp.</div><div class="sdc-val">${d.public_hospitals || 0}</div></div>
            <div><div class="sdc-label">Private hosp.</div><div class="sdc-val">${priv}</div></div>
        </div>`;
    } else {
        const priorityColor = { High: '#e74c3c', Medium: '#f39c12', Low: '#27ae60' };
        const col = priorityColor[d.ahp_priority] || '#27ae60';
        body = `
        <div class="sdc-grid">
            <div><div class="sdc-label">AHP Score</div><div class="sdc-val" style="color:${col}">${d.ahp_score.toFixed(3)}</div></div>
            <div><div class="sdc-label">Priority</div><div class="sdc-val" style="color:${col}">${d.ahp_priority}</div></div>
            <div><div class="sdc-label">Population</div><div class="sdc-val">${formatNum(Math.round(d.population))}</div></div>
            <div><div class="sdc-label">EMS Stations</div><div class="sdc-val">${d.stations}</div></div>
            <div><div class="sdc-label">Area km\u00b2</div><div class="sdc-val">${d.area_km2.toFixed(0)}</div></div>
            <div><div class="sdc-label">Density /km\u00b2</div><div class="sdc-val">${d.pop_density.toFixed(0)}</div></div>
        </div>`;
    }

    card.innerHTML = `
        <div class="sdc-title">
            <span>${d.district_name} <small style="color:#aaa;font-weight:400">${d.governorate}</small></span>
            <span class="sdc-close" onclick="hideSelectedDistrictCard()">&times;</span>
        </div>${body}`;
    card.style.display = 'block';
}

function hideSelectedDistrictCard() {
    const card = document.getElementById('selected-district-card');
    if (card) card.style.display = 'none';
}

// ── LIVE MODEL ────────────────────────────────────────────────────────────────

const _PRIORITY_FILL   = { High: '#e74c3c', Medium: '#f39c12', Low: '#27ae60' };
let _modelResultFilter = null; // null = show top 5 all; 'High'/'Medium'/'Low' = filter
let _showAllProposed   = true;  // default: show every proposed station regardless of tier

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

/** Updates the percentage labels and the formula line in the Model tab. */
function _updateWeightDisplay(normW) {
    CRITERIA_CONFIG.forEach(c => {
        const pctEl = document.getElementById('pct-' + c.id);
        if (pctEl) pctEl.textContent = Math.round((normW[c.id] || 0) * 100) + '%';
    });
    _updateFormulaLine(normW);
}

/** Plain-word names for the formula line. */
const _FORMULA_WORDS = { access_gap: 'travel', pop_density: 'density', exposed_pop: 'exposure', bed_gap: 'beds' };
const _PRESET_LABELS = { balanced: 'Balanced', access: 'Access', population: 'Population', capacity: 'Capacity' };

/** Updates the formula line + preset chip in the Model tab's setup card. */
function _updateFormulaLine(normW) {
    const pctsEl = document.getElementById('model-formula-pcts');
    if (!pctsEl) return;
    pctsEl.innerHTML = CRITERIA_CONFIG.map(c =>
        `<b>${Math.round((normW[c.id] || 0) * 100)}% ${_FORMULA_WORDS[c.id] || c.id}</b>`).join(' &middot; ');
    const chipEl = document.getElementById('model-formula-chip');
    if (chipEl) chipEl.textContent = _activePreset ? (_PRESET_LABELS[_activePreset] || _activePreset) : 'Custom';
}

/** A weight slider was moved by hand: preset becomes Custom, everything recomputes. */
function onWeightInput() {
    _activePreset = null;
    document.querySelectorAll('.preset-btn').forEach(btn => btn.classList.remove('preset-btn-active'));
    recomputeAhpScores();
}

/** Computes the hospital "gap in four terms" from DISTRICTS + current settings.
 *  Pure read of embedded per-district fields; no Python re-run needed. */
function computeHospitalGaps() {
    const bench = _getBenchmark();
    const thr   = _getThreshold();
    let totalPop = 0, bedShort = 0, exposedPop = 0, noPublicPop = 0;
    const underCap = [], poorAccess = [], noPublic = [];
    DISTRICTS.forEach(d => {
        const pop = d.population || 0;
        totalPop += pop;
        const bpk = d.beds_per_1000 || 0;
        if (bpk < bench) { bedShort += (bench - bpk) * pop / 1000; underCap.push(d); }
        const tt = d.min_travel_time_min;
        if (tt !== null && tt !== undefined && tt > thr) { exposedPop += pop; poorAccess.push(d); }
        if ((d.public_hospitals || 0) === 0) { noPublic.push(d); noPublicPop += pop; }
    });
    const counts = { High: 0, Medium: 0, Low: 0 };
    DISTRICTS.forEach(d => { if (counts[d.ahp_priority] !== undefined) counts[d.ahp_priority]++; });
    return {
        bench, thr, totalPop,
        capacity: { beds: Math.round(bedShort), districts: underCap.sort((a, b) => a.beds_per_1000 - b.beds_per_1000) },
        access:   { people: Math.round(exposedPop), pct: totalPop ? Math.round(exposedPop / totalPop * 100) : 0,
                    districts: poorAccess.sort((a, b) => (b.min_travel_time_min || 0) - (a.min_travel_time_min || 0)) },
        afford:   { people: Math.round(noPublicPop), districts: noPublic.sort((a, b) => (b.population || 0) - (a.population || 0)) },
        priority: { counts, districts: [...DISTRICTS].sort((a, b) => (b.ahp_score || 0) - (a.ahp_score || 0)) },
    };
}

/** Renders the four hospital "gap" cards (Capacity · Access · Affordability · Priority). */
function renderHospitalGapResults(el) {
    const g   = computeHospitalGaps();
    const fmt = n => Math.round(n).toLocaleString('en-US');
    const list = (districts, metricFn, n = 5) =>
        districts.slice(0, n).map(d =>
            `<div class="gap-dist-row" onclick="onDistrictCardClick('${escJs(d.district_name)}')">
                <span class="gap-dist-name">${d.district_name}</span>
                <span class="gap-dist-metric">${metricFn(d)}</span>
            </div>`).join('') || '<div class="gap-dist-empty">None — no gap on this lens.</div>';

    const capOk = g.capacity.beds <= 0;
    const accOk = g.access.people <= 0;
    const affOk = g.afford.districts.length === 0;

    // Priority card: show every High district; Medium & Low collapse behind clickable toggles.
    const priRow = d =>
        `<div class="gap-dist-row" onclick="onDistrictCardClick('${escJs(d.district_name)}')">
            <span class="gap-dist-name">${d.district_name}</span>
            <span class="gap-dist-metric"><span class="gap-pri ${(d.ahp_priority || 'Low').toLowerCase()}">${d.ahp_priority || 'Low'}</span> ${(d.ahp_score || 0).toFixed(3)}</span>
        </div>`;
    const priTierRows = tier =>
        g.priority.districts.filter(d => (d.ahp_priority || 'Low') === tier).map(priRow).join('')
        || '<div class="gap-dist-empty">None.</div>';
    const priTierBlock = tier => {
        const n = g.priority.counts[tier] || 0;
        return `<details class="gap-tier ${tier.toLowerCase()}">
            <summary class="gap-tier-summary">
                <span class="gap-pri ${tier.toLowerCase()}">${tier}</span>
                <span class="gap-tier-count">${n} district${n === 1 ? '' : 's'}</span>
                <span class="gap-tier-caret">&#9662;</span>
            </summary>
            <div class="gap-dist-list">${priTierRows(tier)}</div>
        </details>`;
    };
    const priorityBody =
        `<div class="gap-dist-list">${priTierRows('High')}</div>`
        + priTierBlock('Medium') + priTierBlock('Low');

    const cards = [
        { cls: 'capacity', icon: '&#127973;', title: 'Capacity', ok: capOk,
          head: capOk ? '&#10003; At benchmark' : `${fmt(g.capacity.beds)} beds short`,
          sub: capOk
            ? `Every district is at or above the ${g.bench.toFixed(1)} beds/1,000 benchmark.`
            : `${g.capacity.districts.length} districts below the ${g.bench.toFixed(1)} beds/1,000 benchmark.`,
          body: list(g.capacity.districts, d => `${(d.beds_per_1000 || 0).toFixed(2)}/1k`) },
        { cls: 'access', icon: '&#128657;', title: 'Access', ok: accOk,
          head: accOk ? '&#10003; No access gap' : `${fmt(g.access.people)} people · ${g.access.pct}%`,
          sub: accOk
            ? `No district is beyond ${g.thr} min from a hospital — <em>access</em> is broadly adequate; the gap is distribution &amp; affordability.`
            : `live &gt;${g.thr} min from a hospital, across ${g.access.districts.length} districts.`,
          body: list(g.access.districts, d => d.min_travel_time_min != null ? `${Math.round(d.min_travel_time_min)} min` : '—') },
        { cls: 'afford', icon: '&#128176;', title: 'Affordability', ok: affOk,
          head: affOk ? '&#10003; All covered' : `${g.afford.districts.length} districts`,
          sub: affOk
            ? `Every district has at least one public hospital.`
            : `${fmt(g.afford.people)} people have no public hospital (affordable-care gap).`,
          body: list(g.afford.districts, d => `${fmt(d.population)} ppl`) },
        { cls: 'priority', icon: '&#127919;', title: 'Overall priority', ok: false,
          head: `${g.priority.counts.High} high-priority`,
          sub: `most under-served districts by your weights — ${g.priority.counts.High} high / ${g.priority.counts.Medium} med / ${g.priority.counts.Low} low.`,
          body: priorityBody, wrap: false },
    ];

    // Cards start closed; re-renders (slider moves) keep whatever the user opened.
    const openCards = new Set(
        Array.from(el.querySelectorAll('details.gap-card[open]'))
             .map(d => Array.from(d.classList).find(c => ['capacity','access','afford','priority'].includes(c)))
             .filter(Boolean));

    el.innerHTML = `<div class="model-results-title">The gap — in four terms</div>
        <div class="gap-cards">
            ${cards.map(c => `
                <details class="gap-card ${c.cls}${c.ok ? ' is-ok' : ''}"${openCards.has(c.cls) ? ' open' : ''}>
                    <summary class="gap-card-summary">
                        <span class="gap-card-icon">${c.icon}</span>
                        <span class="gap-card-text">
                            <span class="gap-card-title">${c.title}</span>
                            <span class="gap-card-head">${c.head}</span>
                        </span>
                        <span class="gap-card-caret">&#9662;</span>
                    </summary>
                    <div class="gap-card-sub">${c.sub}</div>
                    ${c.wrap === false ? c.body : `<div class="gap-dist-list">${c.body}</div>`}
                </details>`).join('')}
        </div>`;
}

/** Updates the Results section inside the Model tab after any recompute. */
function renderModelResults() {
    const el = document.getElementById('model-results-section');
    if (!el) return;
    if (ACTIVE_DATASET === 'hospitals') { renderHospitalGapResults(el); renderInterventions(); return; }

    const candidates = (typeof CANDIDATES !== 'undefined' && Array.isArray(CANDIDATES)) ? CANDIDATES : [];

    // This panel is about PROPOSED STATIONS. classifyActiveCandidates() tags each
    // still-needed station with _priority by AHP-score quantiles, so the
    // High/Medium/Low chips always sum to the total.
    const neededStations = classifyActiveCandidates();
    const neededCount  = neededStations.length;

    const counts = { High: 0, Medium: 0, Low: 0 };
    neededStations.forEach(s => { if (counts[s._priority] !== undefined) counts[s._priority]++; });

    const sortedStations = [...neededStations].sort((a, b) => (b.mean_score || 0) - (a.mean_score || 0));
    const listStations = _modelResultFilter
        ? sortedStations.filter(s => s._priority === _modelResultFilter)
        : sortedStations.slice(0, 5);

    const chips = [
        { key: 'High',   label: 'High',   count: counts.High },
        { key: 'Medium', label: 'Medium', count: counts.Medium },
        { key: 'Low',    label: 'Low',    count: counts.Low },
    ];

    el.innerHTML = `
        <div class="model-results-title">Live Results</div>
        <div class="model-results-chips">
            ${chips.map(c => `
                <div class="model-chip ${c.key.toLowerCase()}${(!_showAllProposed && _modelResultFilter === c.key) ? ' active' : ''}"
                     onclick="_toggleModelFilter('${c.key}')">
                    <div class="model-chip-dot ${c.key.toLowerCase()}"></div>
                    ${c.count} ${c.label}
                </div>`).join('')}
            <div class="model-chip showall${_showAllProposed ? ' active' : ''}"
                 onclick="_toggleShowAllProposed()" title="Show every proposed station on the map regardless of priority">
                ${_showAllProposed ? 'Showing all' : 'Show all'} (${neededCount})
            </div>
        </div>
        <div class="model-results-list">
            ${listStations.length === 0
                ? `<div style="color:#666;font-size:12px;padding:6px 0">No stations in this tier</div>`
                : listStations.map((s, i) => {
                    const cls = (s._priority || 'Low').toLowerCase();
                    const label = (s.district_name && s.district_name.length)
                        ? s.district_name : ('Proposed Station #' + s.rank);
                    const safeName = label.replace(/"/g, '&quot;');
                    return `<div class="model-result-row" onclick="onCandidateCardClick(${s.lat}, ${s.lon})">
                        <span class="model-result-rank">${i + 1}</span>
                        <span class="model-result-name">${safeName}</span>
                        <span class="model-result-priority ${cls}">${s._priority}</span>
                        <span class="model-result-score">${(s.mean_score || 0).toFixed(3)}</span>
                    </div>`;
                }).join('')}
        </div>`;
}

function _toggleModelFilter(priority) {
    _showAllProposed = false;   // picking a tier exits "show all" mode
    _modelResultFilter = (_modelResultFilter === priority) ? null : priority;
    renderModelResults();
    // Keep the map pins and Analysis list in sync with the selected tier.
    updateCandidateMarkers();
    renderActionsSection();
}

/** Toggles showing every proposed station on the map/list, regardless of tier. */
function _toggleShowAllProposed() {
    _showAllProposed = !_showAllProposed;
    if (_showAllProposed) _modelResultFilter = null;   // "all" overrides any tier filter
    renderModelResults();
    updateCandidateMarkers();
    renderActionsSection();
}

/** Renders the full Model tab content from CRITERIA_CONFIG. */
/** National population-weighted beds/1,000 (the default capacity benchmark). */
function _natAvgBeds() {
    let beds = 0, pop = 0;
    DISTRICTS.forEach(d => { beds += (d.beds_per_1000 || 0) * (d.population || 0); pop += (d.population || 0); });
    return pop > 0 ? beds / pop : 0;
}
/** Current capacity benchmark (beds/1,000) from the slider, else the national default. */
function _getBenchmark() {
    const el = document.getElementById('model-benchmark');
    return el ? parseFloat(el.value) : Math.round(_natAvgBeds() * 10) / 10;
}
/** Current coverage threshold (min) from the slider, else the dataset default. */
function _getThreshold() {
    const el = document.getElementById('coverage-threshold');
    return el ? parseFloat(el.value)
              : (typeof DEFAULT_COVERAGE_THRESHOLD !== 'undefined' ? DEFAULT_COVERAGE_THRESHOLD : 30);
}

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
        return `<div class="candidate-card iv-card" onclick="onInterventionClick('${escJs(dn)}')">
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

function renderModelTab() {
    const panel = document.getElementById('tab-model');
    if (!panel) return;
    const isHosp     = ACTIVE_DATASET === 'hospitals';
    const hasTT      = DISTRICTS.length > 0 && DISTRICTS[0].min_travel_time_min !== null && DISTRICTS[0].min_travel_time_min !== undefined;
    const defaultThr = typeof DEFAULT_COVERAGE_THRESHOLD !== 'undefined' ? DEFAULT_COVERAGE_THRESHOLD : 10;
    const supplyWord = isHosp ? 'hospital' : 'station';
    _activePreset = 'balanced';   // fresh render always starts at defaults

    const resultsBlock = `<div class="model-results-section" id="model-results-section"></div>`;

    // Compact "settings → results" card, shared by both datasets: one row per
    // control, formula line, collapsed weights expander, results below.
    const dsPresets  = (DATASETS[ACTIVE_DATASET] && DATASETS[ACTIVE_DATASET].presets) || WEIGHT_PRESETS;
    const presetBtns = Object.keys(dsPresets).map(p =>
        `<button class="preset-btn${p === 'balanced' ? ' preset-btn-active' : ''}" id="preset-${p}" onclick="applyPreset('${p}')">${_PRESET_LABELS[p] || p}</button>`
    ).join('');

    let setup = `<div class="model-setup-label">&#9881; Setup</div>
        <div class="model-compact-controls ${hasTT ? '' : 'model-disabled'}">
            ${!hasTT ? '<div class="model-note">&#9888; Re-run the Python script to enable live threshold control.</div>' : ''}
            <div class="model-compact-row" title="Districts are &quot;exposed&quot; if travel time to nearest ${supplyWord} exceeds this value.">
                <span class="model-compact-label">Coverage Threshold</span>
                <input type="range" id="coverage-threshold" class="filter-slider"
                    min="5" max="60" step="5" value="${defaultThr}"
                    oninput="document.getElementById('cov-thr-val').textContent=this.value+' min'; recomputeAhpScores()">
                <span class="model-value" id="cov-thr-val">${defaultThr} min</span>
            </div>`;

    if (isHosp) {
        const benchDefault = Math.round(_natAvgBeds() * 10) / 10;
        setup += `
            <div class="model-compact-row" title="Districts below this beds-per-1,000 level are &quot;under-capacity&quot;. Default = national average.">
                <span class="model-compact-label">Capacity Benchmark</span>
                <input type="range" id="model-benchmark" class="filter-slider"
                    min="1" max="6" step="0.1" value="${benchDefault}"
                    oninput="document.getElementById('bench-val').textContent=this.value+' /1k'; renderModelResults()">
                <span class="model-value" id="bench-val">${benchDefault} /1k</span>
            </div>`;
    }

    setup += `
            <div class="model-formula-row" title="How the Overall-priority score is weighted. Expand below to change it.">
                <span class="model-formula-text">Priority formula: <span id="model-formula-pcts">&mdash;</span></span>
                <span class="model-formula-chip" id="model-formula-chip">Balanced</span>
            </div>
            <details class="model-weights-details">
                <summary>Customize weights</summary>
                <div class="preset-btn-group" style="margin-top:8px;">
                    ${presetBtns}
                </div>
                ${isHosp ? '' : '<div class="preset-notify" id="preset-notify"></div>'}
                ${CRITERIA_CONFIG.map(c => `
                <div class="model-compact-row" title="${c.description.replace(/"/g, '&quot;')}">
                    <span class="model-compact-label">${c.label}</span>
                    <input type="range" class="filter-slider" id="weight-${c.id}"
                        min="0" max="1" step="0.05" value="${c.weight}"
                        oninput="onWeightInput()">
                    <span class="model-pct" id="pct-${c.id}">&mdash;</span>
                </div>`).join('')}
            </details>
        </div>
        <div class="model-compact-reset">
            <a href="#" onclick="resetModelDefaults(); return false;">&#8635; Reset to defaults</a>
        </div>`;

    if (!isHosp) {
        setup += `
        <div class="model-footer-note">
            <strong>Updates live:</strong> sidebar ranking, score bars, priority counts, district colors on map.
        </div>`;
    }

    panel.innerHTML = setup + resultsBlock;

    recomputeAhpScores();
}

/** Preset scenarios for criterion weights. */
const WEIGHT_PRESETS = {
    balanced:   { access_gap: 0.50, pop_density: 0.30, exposed_pop: 0.20 },
    access:     { access_gap: 0.70, pop_density: 0.15, exposed_pop: 0.15 },
    population: { access_gap: 0.20, pop_density: 0.50, exposed_pop: 0.30 },
};

function applyPreset(presetName) {
    // Presets are per-dataset (the hospital model has a 4th 'bed_gap' criterion),
    // so read them from the active dataset; fall back to the EMS defaults.
    const dsPresets = (DATASETS[ACTIVE_DATASET] && DATASETS[ACTIVE_DATASET].presets) || WEIGHT_PRESETS;
    const preset = dsPresets[presetName];
    if (!preset) return;

    _activePreset = presetName;

    // Update hidden slider values so recomputeAhpScores reads them
    CRITERIA_CONFIG.forEach(c => {
        const el = document.getElementById('weight-' + c.id);
        if (el) el.value = preset[c.id];
    });

    // Update percentage labels
    const total = Object.values(preset).reduce((s, v) => s + v, 0);
    CRITERIA_CONFIG.forEach(c => {
        const pctEl = document.getElementById('pct-' + c.id);
        if (pctEl) pctEl.textContent = Math.round((preset[c.id] / total) * 100) + '%';
    });

    // Update active button styling
    document.querySelectorAll('.preset-btn').forEach(btn => btn.classList.remove('preset-btn-active'));
    const activeBtn = document.getElementById('preset-' + presetName);
    if (activeBtn) activeBtn.classList.add('preset-btn-active');

    if (ACTIVE_DATASET === 'ems') {
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

    recomputeAhpScores();
    renderActionsSection();
    updateCandidateMarkers();
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
    const bEl = document.getElementById('model-benchmark'), bVal = document.getElementById('bench-val');
    if (bEl) { const bd = Math.round(_natAvgBeds() * 10) / 10; bEl.value = bd; if (bVal) bVal.textContent = bd + ' /1k'; }
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

    // Reset preset to balanced
    applyPreset('balanced');

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

    renderAhpSummary();
    renderAhpRanking(filtered);
    renderActionsSection();

    if (map && districtLayersByName) {
        Object.entries(districtLayersByName).forEach(([name, layer]) => {
            const match = filteredNames.has(name);
            if (layer.setStyle)
                layer.setStyle({ fillOpacity: _districtRestOpacity(match), opacity: match ? 0.8 : 0.15 });
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
    layer.setStyle({ fillOpacity: 0.6, opacity: 1, weight: 4, color: '#ffffff' });
    if (layer._path) layer._path.style.filter = 'drop-shadow(0 0 6px #fff) drop-shadow(0 0 12px rgba(255,255,255,0.6))';
    layer.bringToFront();
    if (layer.openPopup) layer.openPopup();
    showSelectedDistrictCard(districtName);

    highlightTimeout = setTimeout(() => {
        const filteredNames2 = new Set(getFilteredDistricts().map(d => d.district_name));
        const match = filteredNames2.has(districtName);
        layer.setStyle({ fillOpacity: _districtRestOpacity(match), opacity: match ? 0.8 : 0.15, weight: 2, color: '#4a9eff' });
        if (layer._path) layer._path.style.filter = '';
        highlightTimeout = null;
    }, 1200);
}

// ── RESET MAP VIEW ────────────────────────────────────────────────────────────
function resetMapView() {
    if (highlightTimeout) { clearTimeout(highlightTimeout); highlightTimeout = null; }
    hideSelectedDistrictCard();
    clearInterventionMapArtifacts();
    if (map) {
        map.fitBounds(LEBANON_BOUNDS);
        const filteredNames = new Set(getFilteredDistricts().map(d => d.district_name));
        Object.entries(districtLayersByName).forEach(([name, layer]) => {
            const match = filteredNames.has(name);
            if (layer.setStyle)
                layer.setStyle({ fillOpacity: _districtRestOpacity(match), opacity: match ? 0.8 : 0.15, weight: 2, color: '#4a9eff' });
            if (layer._path) {
                layer._path.style.pointerEvents = match ? 'auto' : 'none';
                layer._path.style.filter = '';
            }
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

// Folium overlays baked from EMS data — hide them (list + map) for hospitals.
const EMS_ONLY_LAYERS = new Set([
    '10-Min Coverage (Road Time)',
    'Grid AHP Priority (High+Medium)',
    'Grid AHP Priority (Low)',
    'Suggested New EMS Stations',
]);
// 'AHP Priority (District Level)' is now a client-side fill toggle (setAhpDistrictFill),
// not a baked Folium overlay — handled as a virtual row in renderFiltersTab.
let _layerDefaults = null;  // captured once: layer name -> on-by-default?

/** Hide EMS-only Folium layers when the hospital dataset is active. */
function applyDatasetLayerVisibility() {
    const overlays = _getFoliumOverlays();
    if (!overlays || !map) return;
    if (_layerDefaults === null) {
        _layerDefaults = {};
        Object.entries(overlays).forEach(([n, l]) => { _layerDefaults[n] = map.hasLayer(l); });
    }
    const isHosp = ACTIVE_DATASET === 'hospitals';
    Object.entries(overlays).forEach(([n, l]) => {
        if (!EMS_ONLY_LAYERS.has(n)) return;
        const show = !isHosp && _layerDefaults[n];
        if (show && !map.hasLayer(l)) map.addLayer(l);
        else if (!show && map.hasLayer(l)) map.removeLayer(l);
    });
}

function renderFiltersTab() {
    const panel = document.getElementById('tab-filters');
    if (!panel || !map) return;

    const overlays = _getFoliumOverlays();
    if (!overlays) {
        panel.innerHTML = '<div class="empty-section">Map layers not yet loaded — try switching to this tab after the map loads.</div>';
        return;
    }

    // Hide EMS-specific layers from the list when viewing hospitals.
    const entries = Object.entries(overlays).filter(
        ([name]) => ACTIVE_DATASET !== 'hospitals' || !EMS_ONLY_LAYERS.has(name));

    // Hospital dataset: ownership filter (public / private / both)
    const ownershipHtml = ACTIVE_DATASET === 'hospitals' ? `
        <div class="section-header">Hospital Ownership</div>
        <div class="filter-desc-note">Show hospitals by who runs them. Public = government / affordable.</div>
        <div class="ownership-filter">
            <button class="ownership-btn${hospitalTypeFilter === 'all' ? ' active' : ''}" onclick="setHospitalFilter('all')">Both</button>
            <button class="ownership-btn${hospitalTypeFilter === 'public' ? ' active' : ''}" onclick="setHospitalFilter('public')">Public only</button>
            <button class="ownership-btn${hospitalTypeFilter === 'private' ? ' active' : ''}" onclick="setHospitalFilter('private')">Private only</button>
        </div>` : '';

    // EMS dataset: a toggle for the existing-station markers (drawn outside Folium,
    // so it isn't in the overlays list — wired to supplyLayerGroup directly).
    const supplyRowHtml = ACTIVE_DATASET === 'ems' ? `
        <label class="filter-layer-row" for="flayer-existing-ems">
            <input type="checkbox" class="filter-layer-cb" id="flayer-existing-ems"
                ${supplyLayerVisible ? 'checked' : ''} data-supply-toggle="1">
            <span class="filter-layer-indicator" style="background:#e74c3c"></span>
            <div class="filter-layer-info">
                <div class="filter-layer-name">Existing EMS Stations</div>
                <div class="filter-layer-desc">Current EMS station locations</div>
            </div>
        </label>` : '';

    // AHP choropleth fill is painted on the District Boundaries polygons, not a baked
    // overlay — a virtual row toggles it so districts can be shown as outlines only.
    const ahpFillRowHtml = `
        <label class="filter-layer-row" for="flayer-ahp-fill">
            <input type="checkbox" class="filter-layer-cb" id="flayer-ahp-fill"
                ${ahpDistrictFillOn ? 'checked' : ''} data-ahp-fill-toggle="1">
            <span class="filter-layer-indicator" style="background:#9b59b6"></span>
            <div class="filter-layer-info">
                <div class="filter-layer-name">AHP Priority (District Level)</div>
                <div class="filter-layer-desc">District fill colored by AHP priority</div>
            </div>
        </label>`;

    panel.innerHTML = ownershipHtml + `
        <div class="section-header">Map Layers</div>
        <div class="filter-desc-note">Toggle layers on or off. Changes are visible on the map immediately.</div>
        <div class="filter-layers-list">
            ${supplyRowHtml}
            ${ahpFillRowHtml}
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
            if (cb.dataset.supplyToggle) { setSupplyLayerVisible(cb.checked); return; }
            if (cb.dataset.ahpFillToggle) { setAhpDistrictFill(cb.checked); return; }
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
                    if (name) {
                        districtLayersByName[name] = subl;
                        // Folium's highlight_function resets to the baked (colored) style on
                        // mouseout; re-apply our toggle-aware resting fill so "AHP fill off"
                        // (and the active filter) survives a hover.
                        subl.on('mouseout', () => {
                            if (highlightTimeout) return;  // don't fight an active click-highlight
                            const match = getFilteredDistricts().some(d => d.district_name === name);
                            subl.setStyle({ fillOpacity: _districtRestOpacity(match), opacity: match ? 0.8 : 0.15 });
                        });
                    }
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

// ── DATASET SWITCH ────────────────────────────────────────────────────────────
function setHospitalFilter(t) {
    hospitalTypeFilter = t;
    refreshSupplyLayer();
    if (typeof renderFiltersTab === 'function') renderFiltersTab();  // refresh active button
}

// Swap the dataset-specific rows of the map legend (priority swatches are shared).
function updateMapLegend() {
    const el = document.getElementById('legend-dynamic');
    if (!el) return;
    el.innerHTML = ACTIVE_DATASET === 'hospitals'
        ? '<div><span class="legend-symbol hosp-public">H</span>Public hospital</div>'
          + '<div><span class="legend-symbol hosp-private">H</span>Private hospital</div>'
        : '<div><span class="legend-symbol ems">+</span>Existing EMS</div>'
          + '<div><span class="legend-symbol proposed">+</span>Proposed site</div>';
}

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

    // Reset per-dataset UI state on every switch.
    supplyLayerVisible = true;   // each dataset starts with its supply markers shown
    ahpDistrictFillOn = true;    // and with the AHP choropleth fill shown
    hospitalTypeFilter = 'all';
    _modelResultFilter = null;   // tier filter is EMS-specific; don't leak across datasets
    if (typeof hideHospitalDetail === 'function') hideHospitalDetail();
    if (typeof clearInterventionMapArtifacts === 'function') clearInterventionMapArtifacts();

    // Re-render map + panels for the newly active dataset.
    if (typeof refreshSupplyLayer === 'function') refreshSupplyLayer(); // defined in a later task
    if (typeof applyDatasetLayerVisibility === 'function') applyDatasetLayerVisibility();
    if (typeof updateMapLegend === 'function') updateMapLegend();
    if (typeof initCandidatesLayer === 'function') initCandidatesLayer();
    if (typeof initModelNormScores === 'function') initModelNormScores();
    if (typeof recomputeAhpScores === 'function') recomputeAhpScores();
    if (typeof updateMapDistrictColors === 'function') updateMapDistrictColors();
    if (typeof renderModelTab === 'function') renderModelTab();
    if (typeof renderFiltersTab === 'function') renderFiltersTab();
    if (typeof applyFilters === 'function') applyFilters();
    if (typeof renderAhpSummary === 'function' && typeof getFilteredDistricts === 'function') {
        const f = getFilteredDistricts();
        renderAhpSummary(f);
        if (typeof renderAhpRanking === 'function') renderAhpRanking(f);
    }
    if (typeof renderActionsSection === 'function') renderActionsSection();
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
    if (candidatesLimit) candidatesLimit.addEventListener('change', renderActionsSection);

    // Floating candidates toggle button
    const toggleBtn2 = document.getElementById('candidates-map-toggle');
    if (toggleBtn2) toggleBtn2.addEventListener('click', toggleCandidatesLayer);

    // Reset map
    const resetBtn = document.getElementById('reset-map-view');
    if (resetBtn) resetBtn.addEventListener('click', resetMapView);

    // Panel toggle
    const toggleBtn = document.getElementById('panel-toggle-btn');
    if (toggleBtn) toggleBtn.addEventListener('click', togglePanel);

    // Dataset selector
    const dsSel = document.getElementById('dataset-select');
    if (dsSel) dsSel.addEventListener('change', e => setActiveDataset(e.target.value));

    initMapRefs();
    refreshSupplyLayer();
    applyDatasetLayerVisibility();
    updateMapLegend();
    initModelNormScores();
    renderModelTab();
    renderFiltersTab();
    applyFilters();
    renderActionsSection();

    // Browsers restore <select> state across reloads, but ACTIVE_DATASET resets
    // to 'ems' and no change event fires — leaving the dropdown showing one
    // dataset while the panels render another. Honor the dropdown's actual value.
    if (dsSel && dsSel.value && dsSel.value !== ACTIVE_DATASET) setActiveDataset(dsSel.value);
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
