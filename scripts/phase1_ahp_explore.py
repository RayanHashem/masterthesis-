"""
Phase 1: Data Exploration and Visualization with Analytics Dashboard
Load and explore district boundaries, EMS stations, and population data.
Create an interactive dashboard with map and analytics panel.
"""

import os
import sys
import json

# Check for required packages
try:
    import geopandas as gpd
    from shapely.geometry import Point, box as shapely_box
    from shapely.ops import unary_union
except ImportError:
    print("ERROR: geopandas is not installed. Install with: pip install geopandas")
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas is not installed. Install with: pip install pandas")
    sys.exit(1)

try:
    import folium
    from folium import plugins
    from folium import DivIcon
except ImportError:
    print("ERROR: folium is not installed. Install with: pip install folium")
    sys.exit(1)

try:
    import rasterio
    from rasterio.transform import xy
except ImportError:
    print("ERROR: rasterio is not installed. Install with: pip install rasterio")
    sys.exit(1)

try:
    import osmnx as ox
    import networkx as nx
except ImportError:
    print("ERROR: osmnx or networkx is not installed.")
    print("  Install with: pip install osmnx networkx")
    print("  Note: osmnx requires networkx as a dependency.")
    sys.exit(1)

try:
    import sklearn  # required by osmnx nearest_nodes for unprojected graphs
except ImportError:
    print("ERROR: scikit-learn is not installed (required for nearest node search).")
    print("  Install with: pip install scikit-learn")
    sys.exit(1)

import numpy as np
import re

# ============================================================================
# SETUP: Define paths relative to project root (lebanon-ems)
# ============================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, 'templates')

# Data file paths
DISTRICTS_FILE = os.path.join(DATA_DIR, 'gadm41_LBN_2.json')
EMS_STATIONS_FILE = os.path.join(DATA_DIR, 'EMS_Station_Locations.xlsx')
POPULATION_RASTER_FILE = os.path.join(DATA_DIR, 'lbn_pop_2025_CN_1km_R2025A_UA_v1.tif')
OUTPUT_DASHBOARD_FILE = os.path.join(DATA_DIR, 'phase1_ahp_dashboard.html')

print("=" * 80)
print("PHASE 1: DATA EXPLORATION WITH ANALYTICS DASHBOARD")
print("=" * 80)
print(f"Project root: {PROJECT_ROOT}")
print(f"Data directory: {DATA_DIR}")
print()

# ============================================================================
# 1. LOAD DISTRICT BOUNDARIES
# ============================================================================
print("1. LOADING DISTRICT BOUNDARIES")
print("-" * 80)
try:
    districts_gdf = gpd.read_file(DISTRICTS_FILE)
    print(f"✓ Loaded district boundaries: {len(districts_gdf)} districts")
    print(f"  CRS: {districts_gdf.crs}")
except Exception as e:
    print(f"✗ Error loading district boundaries: {e}")
    sys.exit(1)

# ============================================================================
# 2. LOAD EMS STATION DATA
# ============================================================================
print("2. LOADING EMS STATION DATA")
print("-" * 80)
try:
    ems_df = pd.read_excel(EMS_STATIONS_FILE, engine='openpyxl')
    print(f"✓ Loaded EMS stations: {len(ems_df)} stations")
    
    # Find coordinate columns
    lat_col = None
    lon_col = None
    for col in ems_df.columns:
        col_lower = str(col).lower()
        if 'lat' in col_lower or ('y' == col_lower and lat_col is None):
            lat_col = col
        if 'lon' in col_lower or ('long' in col_lower) or ('x' == col_lower and lon_col is None):
            lon_col = col
    
    if lat_col is None or lon_col is None:
        print(f"✗ Could not find coordinate columns")
        sys.exit(1)
    
    print(f"  Using coordinates: {lat_col}, {lon_col}")
    
    # Create GeoDataFrame for EMS stations
    ems_valid = ems_df.dropna(subset=[lat_col, lon_col]).copy()
    ems_gdf = gpd.GeoDataFrame(
        ems_valid,
        geometry=[Point(xy) for xy in zip(ems_valid[lon_col], ems_valid[lat_col])],
        crs='EPSG:4326'
    )
    
except Exception as e:
    print(f"✗ Error loading EMS stations: {e}")
    sys.exit(1)

# ---- Phase 2: load hospitals dataset ----
HOSPITALS_FILE = os.path.join(DATA_DIR, 'lebanon_hospitals.csv')
hospitals_df = pd.read_csv(HOSPITALS_FILE)
hospitals_gdf = gpd.GeoDataFrame(
    hospitals_df,
    geometry=gpd.points_from_xy(hospitals_df['lon'], hospitals_df['lat']),
    crs='EPSG:4326')
print(f"  ✓ Loaded {len(hospitals_gdf)} hospitals")

# ============================================================================
# 3. LOAD POPULATION RASTER AND CALCULATE DISTRICT POPULATIONS
# ============================================================================
print("3. LOADING POPULATION RASTER AND CALCULATING DISTRICT POPULATIONS")
print("-" * 80)
try:
    with rasterio.open(POPULATION_RASTER_FILE) as src:
        raster_data = src.read(1)
        raster_transform = src.transform
        raster_nodata = src.nodata
        raster_width = src.width
        raster_height = src.height
        
        print(f"✓ Loaded raster: {raster_width}x{raster_height}")
        
        # Sample raster to create point GeoDataFrame
        # Use smaller step for more accurate population calculation
        print("  Sampling raster pixels...")
        sample_step = max(1, min(5, raster_width // 100, raster_height // 100))
        
        raster_points = []
        for y in range(0, raster_height, sample_step):
            for x in range(0, raster_width, sample_step):
                pixel_value = raster_data[y, x]
                if raster_nodata is not None and pixel_value == raster_nodata:
                    continue
                if np.isnan(pixel_value) or pixel_value <= 0:
                    continue
                
                lon, lat = xy(raster_transform, y, x)
                raster_points.append({
                    'geometry': Point(lon, lat),
                    'population': float(pixel_value)
                })
        
        raster_gdf = gpd.GeoDataFrame(raster_points, crs='EPSG:4326')
        print(f"  Created {len(raster_gdf)} population sample points")
        
        # Spatially join raster points to districts
        print("  Joining population data to districts...")
        districts_with_pop = gpd.sjoin(
            districts_gdf,
            raster_gdf,
            how='left',
            predicate='contains'
        )
        
        # Aggregate population by district
        district_pop = districts_with_pop.groupby(districts_with_pop.index).agg({
            'population': 'sum'
        }).fillna(0)
        
        districts_gdf['population'] = district_pop['population']
        print(f"✓ Calculated population for {len(districts_gdf)} districts")
        
        total_population = districts_gdf['population'].sum()
        print(f"  Total population: {total_population:,.0f}")
        
except Exception as e:
    print(f"✗ Error processing population raster: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# 4. COUNT EMS STATIONS PER DISTRICT
# ============================================================================
print("4. COUNTING EMS STATIONS PER DISTRICT")
print("-" * 80)
try:
    # Ensure both GeoDataFrames are in same CRS
    if districts_gdf.crs != ems_gdf.crs:
        ems_gdf = ems_gdf.to_crs(districts_gdf.crs)
    
    # Spatially join EMS stations to districts
    ems_in_districts = gpd.sjoin(
        ems_gdf,
        districts_gdf,
        how='left',
        predicate='within'
    )
    
    # Count stations per district
    station_counts = ems_in_districts.groupby(ems_in_districts.index_right).size()
    
    districts_gdf['ems_stations'] = districts_gdf.index.map(station_counts).fillna(0).astype(int)
    print(f"✓ Counted EMS stations for {len(districts_gdf)} districts")
    
except Exception as e:
    print(f"✗ Error counting EMS stations: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# 5b. AGGREGATE DUPLICATE DISTRICTS BY NAME
# ============================================================================
# GADM data has duplicate district names (e.g. two "Batroun", two "Nabatiyeh").
# Merge them into one row per district name: union geometry, sum population, sum stations.
print("5b. AGGREGATING DUPLICATE DISTRICTS BY NAME")
print("-" * 80)

districts_agg = districts_gdf.dissolve(
    by='NAME_2',
    aggfunc={'population': 'sum', 'ems_stations': 'sum', 'NAME_1': 'first'}
).reset_index()

print(f"✓ Aggregated to {len(districts_agg)} unique districts (from {len(districts_gdf)} polygons)")

# ============================================================================
# 5c. STEP 1A — ROAD NETWORK + TRAVEL TIME MODEL
# ============================================================================
print("5c. ROAD NETWORK + TRAVEL TIME MODEL (STEP 1A)")
print("-" * 80)

# Default speeds (km/h) by highway type when maxspeed is missing
HIGHWAY_SPEED_DEFAULTS = {
    'motorway': 100,
    'motorway_link': 80,
    'trunk': 80,
    'trunk_link': 60,
    'primary': 60,
    'primary_link': 50,
    'secondary': 50,
    'secondary_link': 40,
    'tertiary': 40,
    'tertiary_link': 30,
    'residential': 30,
    'living_street': 20,
    'service': 20,
    'unclassified': 40,
    'road': 40,
}

def parse_maxspeed(val):
    """Parse maxspeed string to km/h. Handles '50', '50 km/h', '50 mph', etc."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    s = str(val).strip().lower()
    if not s:
        return None
    # Extract number
    m = re.search(r'[\d.]+', s)
    if not m:
        return None
    num = float(m.group())
    if 'mph' in s or 'mp/h' in s:
        num *= 1.60934  # mph to km/h
    return num

def get_edge_speed_kmh(edge_data):
    """Get speed in km/h for an edge: maxspeed if present, else default by highway type."""
    maxspeed = edge_data.get('maxspeed')
    if maxspeed is not None:
        if isinstance(maxspeed, (list, tuple)):
            maxspeed = maxspeed[0] if maxspeed else None
        parsed = parse_maxspeed(maxspeed)
        if parsed is not None and parsed > 0:
            return parsed
    highway = edge_data.get('highway')
    if highway is None:
        return 40  # fallback
    if isinstance(highway, (list, tuple)):
        highway = highway[0] if highway else 'road'
    return HIGHWAY_SPEED_DEFAULTS.get(highway, 40)

GRAPH_CACHE_FILE = os.path.join(DATA_DIR, 'road_graph_lebanon.graphml')
SKIP_OSM_DOWNLOAD = os.environ.get('LEBANON_EMS_SKIP_OSM', '').lower() in ('1', 'true', 'yes')

try:
    # Get bounding box from districts + buffer
    # total_bounds: minx, miny, maxx, maxy (lon, lat for EPSG:4326)
    bounds = districts_gdf.total_bounds
    buffer = 0.02  # degrees (small buffer to keep download manageable)
    left = bounds[0] - buffer
    bottom = bounds[1] - buffer
    right = bounds[2] + buffer
    top = bounds[3] + buffer
    bbox = (left, bottom, right, top)  # (west, south, east, north) for osmnx 2.x

    print(f"  Bounding box: (left={left:.4f}, bottom={bottom:.4f}, right={right:.4f}, top={top:.4f})")

    if os.path.exists(GRAPH_CACHE_FILE):
        # Load pre-built graph — fast (seconds)
        print(f"  Loading cached road graph from {os.path.basename(GRAPH_CACHE_FILE)}...")
        G = ox.load_graphml(GRAPH_CACHE_FILE)
        print(f"  ✓ Loaded graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges (from cache)")
    elif SKIP_OSM_DOWNLOAD:
        print("  Skipping OpenStreetMap download because LEBANON_EMS_SKIP_OSM=1")
        G = None
    else:
        # Download drivable road network from OpenStreetMap — slow (~3 min)
        print("  Downloading road network from OpenStreetMap (first run only)...")
        ox.settings.requests_timeout = 45
        G = ox.graph_from_bbox(bbox, network_type='drive')
        print(f"  ✓ Loaded graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

        # Assign travel time (seconds) to each edge before saving
        for u, v, k, data in G.edges(keys=True, data=True):
            length_m = data.get('length', 0)
            if length_m <= 0:
                data['travel_time'] = 0
                continue
            speed_kmh = get_edge_speed_kmh(data)
            speed_mps = speed_kmh * 1000 / 3600
            data['travel_time'] = length_m / speed_mps

        print(f"  ✓ Travel time (seconds) assigned to all edges")

        # Save graph so future runs skip the download
        ox.save_graphml(G, GRAPH_CACHE_FILE)
        print(f"  ✓ Graph cached to {os.path.basename(GRAPH_CACHE_FILE)}")

    if G is not None:
        # Ensure travel_time is set on all edges (handles cache loaded without it)
        for u, v, k, data in G.edges(keys=True, data=True):
            if 'travel_time' not in data:
                length_m = data.get('length', 0)
                if length_m <= 0:
                    data['travel_time'] = 0
                else:
                    speed_kmh = get_edge_speed_kmh(data)
                    speed_mps = speed_kmh * 1000 / 3600
                    data['travel_time'] = length_m / speed_mps

        print(f"  ✓ Road network ready for 10-minute coverage analysis")

except Exception as e:
    print(f"  ✗ Error building road network: {e}")
    import traceback
    traceback.print_exc()
    G = None

# ----------------------------------------------------------------------------
# Shared definitions for supply analysis (used by run_supply_analysis below)
# ----------------------------------------------------------------------------

def minmax_normalize(series):
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series([0.0] * len(series), index=series.index)
    return (series - mn) / (mx - mn)

# AHP weights
W_C1, W_C2, W_C3 = 0.5, 0.3, 0.2

# Default coverage threshold (minutes) — used by live model controls
DEFAULT_COVERAGE_THRESHOLD_MIN = 10

# Criteria config — drives live Model tab in dashboard.
# To add a new criterion: append an entry here, compute its normalised column above,
# and add the raw value to districts_data below.
CRITERIA_CONFIG = [
    {
        'id':          'access_gap',
        'label':       'Travel Time Gap',
        'description': 'Min. road travel time to nearest EMS station (higher = worse coverage)',
        'weight':      W_C1,
        'norm_key':    'norm_access_gap',
    },
    {
        'id':          'pop_density',
        'label':       'Population Density',
        'description': 'Population per km² in the district',
        'weight':      W_C2,
        'norm_key':    'norm_pop_density',
    },
    {
        'id':          'exposed_pop',
        'label':       'Exposed Population',
        'description': 'Population outside the coverage threshold (recalculated live)',
        'weight':      W_C3,
        'norm_key':    'norm_exposed_pop',
        'dynamic':     True,
    },
]


def run_supply_analysis(districts, G, supply_lons, supply_lats,
                        threshold_min, weights, label='supply', supply_beds=None):
    """Run travel-time coverage + AHP scoring for one supply layer.

    Returns {'districts': <copy with min_travel_time_min, covered, norm_* ,
    ahp_score, ahp_priority>, 'coverage_gdf': ..., 'best_time_s': ...}.
    weights is (w_c1, w_c2, w_c3). label names the supply layer for logging.
    """
    d = districts.copy()

    # ========================================================================
    # STEP 1B — COMPUTE COVERAGE + PER-DISTRICT TRAVEL TIME
    # ========================================================================
    coverage_gdf = None  # Will hold coverage polygon for map (Step 1C)
    best_time_s = None  # Will hold multi-source Dijkstra results (used by grid sections)

    if G is not None:
        try:
            # Snap each supply point to nearest graph node
            station_lons = supply_lons
            station_lats = supply_lats
            station_nodes = ox.nearest_nodes(G, station_lons, station_lats)
            station_nodes_unique = set(station_nodes)
            print(f"  ✓ Snapped {len(station_nodes)} stations to {len(station_nodes_unique)} unique graph nodes")

            # Multi-source Dijkstra: min travel time from ANY station to ALL nodes
            best_time_s = nx.multi_source_dijkstra_path_length(G, station_nodes_unique, weight='travel_time')
            print(f"  ✓ Computed shortest travel times to {len(best_time_s)} reachable nodes")

            # For each district: centroid/representative_point -> nearest node -> min_travel_time_min
            min_travel_times = []
            covered_list = []
            for idx, row in d.iterrows():
                geom = row.geometry
                pt = geom.representative_point()
                lon_pt, lat_pt = pt.x, pt.y
                nearest_node = ox.nearest_nodes(G, [lon_pt], [lat_pt])[0]
                best_s = best_time_s.get(nearest_node, float('inf'))
                min_travel_time_min = round(best_s / 60.0, 1) if best_s != float('inf') else float('inf')
                covered = min_travel_time_min <= threshold_min if min_travel_time_min != float('inf') else False
                min_travel_times.append(min_travel_time_min if min_travel_time_min != float('inf') else np.nan)
                covered_list.append(covered)

            d['min_travel_time_min'] = min_travel_times
            d['covered'] = covered_list

            n_covered = sum(covered_list)
            print(f"  ✓ Added min_travel_time_min and covered to {len(d)} districts")
            print(f"  ✓ Districts within {threshold_min} min of {label}: {n_covered} / {len(d)}")

            # Build coverage polygon for map (Step 1C): nodes reachable within threshold
            nodes_covered = [n for n, t in best_time_s.items() if t <= threshold_min * 60]
            if nodes_covered:
                points = []
                for n in nodes_covered:
                    nd = G.nodes[n]
                    lon, lat = nd.get('x'), nd.get('y')
                    if lon is not None and lat is not None:
                        points.append(Point(lon, lat))
                if points:
                    pts_gdf = gpd.GeoDataFrame(geometry=points, crs='EPSG:4326')
                    pts_proj = pts_gdf.to_crs('EPSG:32636')  # UTM 36N for Lebanon
                    buffered = pts_proj.geometry.buffer(200)  # 200m buffer
                    coverage_geom = unary_union(buffered.tolist())
                    coverage_gdf = gpd.GeoDataFrame(
                        [{'geometry': coverage_geom}],
                        crs='EPSG:32636'
                    ).to_crs('EPSG:4326')
                    print(f"  ✓ Built coverage polygon from {len(points)} nodes")

        except Exception as e:
            print(f"  ✗ Error computing coverage: {e}")
            import traceback
            traceback.print_exc()
            d['min_travel_time_min'] = np.nan
            d['covered'] = False
    else:
        print("  ⚠ Skipped (no road network)")
        d['min_travel_time_min'] = np.nan
        d['covered'] = False

    # ========================================================================
    # AHP SCORING (PHASE 3.1) — computed before map so layers can use fields
    # ========================================================================
    print("   COMPUTING AHP SCORES")
    print("-" * 80)

    # --- Area in km² (project to metric CRS first) ---
    districts_metric = d.to_crs(epsg=3857)
    d['area_km2'] = (districts_metric.geometry.area / 1e6).values

    # --- C1: Accessibility Gap (COST — higher travel time = worse) ---
    # Missing travel time treated as max (worst case)
    _max_travel = d['min_travel_time_min'].max()
    if pd.isna(_max_travel):
        _max_travel = 0
    d['_c1_raw'] = d['min_travel_time_min'].fillna(_max_travel)

    # --- C2: Population Density (BENEFIT) ---
    d['pop_density'] = d.apply(
        lambda r: r['population'] / r['area_km2'] if r['area_km2'] > 0 else 0, axis=1
    )

    # --- C3: Exposed Population (BENEFIT — population not covered) ---
    d['exposed_population'] = d.apply(
        lambda r: r['population'] if r['covered'] == False else 0, axis=1
    )

    # Normalize each criterion
    d['norm_access_gap']  = minmax_normalize(d['_c1_raw'])
    d['norm_pop_density'] = minmax_normalize(d['pop_density'])
    d['norm_exposed_pop'] = minmax_normalize(d['exposed_population'])

    if supply_beds is not None and len(weights) == 4:
        from shapely.geometry import Point as _P
        supply_pts = gpd.GeoDataFrame(
            {'beds': list(supply_beds)},
            geometry=[_P(lo, la) for lo, la in zip(supply_lons, supply_lats)],
            crs='EPSG:4326')
        if supply_pts.crs != d.crs:
            supply_pts = supply_pts.to_crs(d.crs)
        d_reset = d.reset_index(drop=True).reset_index()  # 'index' col = positional district index
        joined = gpd.sjoin(supply_pts, d_reset, how='left', predicate='within')
        # The positional district index travels through the join in the 'index' column
        # (geopandas may name the right index 'index_right' or 'index_right0' depending
        # on version/collisions, so we key off the explicit 'index' column instead).
        beds_by_dist = joined.dropna(subset=['index']).groupby('index')['beds'].sum()
        d['_beds_total'] = [float(beds_by_dist.get(i, 0.0)) for i in range(len(d))]
        d['beds_per_1000'] = d.apply(
            lambda r: (r['_beds_total'] / (r['population'] / 1000.0)) if r['population'] > 0 else 0.0,
            axis=1)
        # Cost criterion: fewer beds per capita => higher priority => invert the benefit normalization
        d['norm_bed_gap'] = 1.0 - minmax_normalize(d['beds_per_1000'])
        raw = (weights[0] * d['norm_access_gap'] + weights[1] * d['norm_pop_density']
               + weights[2] * d['norm_exposed_pop'] + weights[3] * d['norm_bed_gap'])
    else:
        raw = (weights[0] * d['norm_access_gap'] + weights[1] * d['norm_pop_density']
               + weights[2] * d['norm_exposed_pop'])
    d['ahp_score'] = raw.round(3)

    # Quantile-based priority: top 20% = High, next 30% = Medium, bottom 50% = Low
    # Avoids fixed-threshold issue where no district reaches 0.66 in Lebanon's context
    _d_q80 = raw.quantile(0.80)
    _d_q50 = raw.quantile(0.50)

    def ahp_priority_label(score):
        if score >= _d_q80:
            return 'High'
        elif score >= _d_q50:
            return 'Medium'
        return 'Low'

    d['ahp_priority'] = raw.apply(ahp_priority_label)

    # Drop only the internal raw column; keep norm_* columns so they can be shipped to JS
    d.drop(columns=['_c1_raw'], inplace=True)

    _high_count   = (d['ahp_priority'] == 'High').sum()
    _medium_count = (d['ahp_priority'] == 'Medium').sum()
    _low_count    = (d['ahp_priority'] == 'Low').sum()
    print(f"  ✓ AHP scores computed for {len(d)} districts")
    print(f"  High priority:   {_high_count}")
    print(f"  Medium priority: {_medium_count}")
    print(f"  Low priority:    {_low_count}")

    return {'districts': d, 'coverage_gdf': coverage_gdf, 'best_time_s': best_time_s}


# ============================================================================
# 5d/5e. SUPPLY ANALYSIS — TRAVEL-TIME COVERAGE + AHP SCORING (EMS)
# ============================================================================
print("5d/5e. EMS SUPPLY ANALYSIS (COVERAGE + AHP)")
print("-" * 80)

EMS_WEIGHTS = (0.5, 0.3, 0.2)
EMS_THRESHOLD_MIN = 10
ems_result = run_supply_analysis(
    districts_agg, G,
    ems_valid[lon_col].values, ems_valid[lat_col].values,
    EMS_THRESHOLD_MIN, EMS_WEIGHTS, label='EMS',
)
districts_agg = ems_result['districts']
coverage_gdf = ems_result['coverage_gdf']
best_time_s = ems_result['best_time_s']

# ---- Phase 2: hospital supply analysis (coverage + AHP) ----
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
     'description': 'Inverse of hospital beds per 1,000 population (fewer beds = higher need). NOTE: most bed counts are estimated.',
     'weight': 0.15, 'norm_key': 'norm_bed_gap'},
]
hosp_result = run_supply_analysis(
    districts_agg, G,
    hospitals_gdf['lon'].values, hospitals_gdf['lat'].values,
    HOSPITAL_THRESHOLD_MIN, HOSPITAL_WEIGHTS, label='Hospital',
    supply_beds=hospitals_gdf['beds'].values,
)
hosp_districts = hosp_result['districts']

# ── Phase 2.5: NEED / ADEQUATE / OVERSUPPLIED classification ──────────────────
# Compares each district's beds-per-1,000 against Lebanon's own national average
# (computed from the data), plus an access clause for districts far from any
# hospital. Gives an *absolute* need verdict, not just a relative ranking.
# CAVEAT: 166/203 hospital bed counts are still median-estimated, so this is
# directional — rural districts with few hospitals can be distorted.
_tot_beds = float(hosp_districts['_beds_total'].sum()) if '_beds_total' in hosp_districts.columns else 0.0
_tot_pop  = float(hosp_districts['population'].sum())
BED_BENCHMARK = round((_tot_beds / _tot_pop * 1000.0), 2) if _tot_pop > 0 else 0.0
ACCESS_NEED_MIN = 25  # min travel time to nearest hospital that signals an access gap

def _need_class(row):
    bpk = float(row.get('beds_per_1000', 0) or 0)
    tt  = row.get('min_travel_time_min', None)
    far = (tt is not None and not pd.isna(tt) and tt >= ACCESS_NEED_MIN)
    if bpk < 0.75 * BED_BENCHMARK or far:
        return 'NEED'
    if bpk > 1.50 * BED_BENCHMARK:
        return 'OVERSUPPLIED'
    return 'ADEQUATE'

hosp_districts['need_class'] = hosp_districts.apply(_need_class, axis=1)
_need_counts = hosp_districts['need_class'].value_counts().to_dict()
print(f"  ✓ Bed benchmark (national avg): {BED_BENCHMARK} beds/1,000")
print(f"  ✓ NEED/ADEQUATE/OVERSUPPLIED: {_need_counts}")

# ============================================================================
# 5f. PHASE 4.1 — CREATE 1KM ANALYSIS GRID FROM POPULATION RASTER
# ============================================================================
print("5f. CREATING 1KM ANALYSIS GRID (PHASE 4.1)")
print("-" * 80)

try:
    with rasterio.open(POPULATION_RASTER_FILE) as _src:
        _transform = _src.transform
        _nodata = _src.nodata

    _px_width  = abs(_transform.a)
    _px_height = abs(_transform.e)

    grid_cells = []
    cell_id = 0

    for _row in range(raster_height):
        for _col in range(raster_width):
            _pixel_value = raster_data[_row, _col]
            if _nodata is not None and _pixel_value == _nodata:
                continue
            if np.isnan(float(_pixel_value)) or _pixel_value <= 0:
                continue

            _lon, _lat = xy(raster_transform, _row, _col)
            _west  = _lon - _px_width  / 2
            _east  = _lon + _px_width  / 2
            _south = _lat - _px_height / 2
            _north = _lat + _px_height / 2

            grid_cells.append({
                'cell_id':    cell_id,
                'population': float(_pixel_value),
                'geometry':   shapely_box(_west, _south, _east, _north),
            })
            cell_id += 1

    grid_cells_gdf = gpd.GeoDataFrame(grid_cells, crs='EPSG:4326')
    print(f"  Total raster cells:     {raster_width * raster_height:,}")
    print(f"  Populated grid cells:   {len(grid_cells_gdf):,}")
    print(f"  Total grid population:  {grid_cells_gdf['population'].sum():,.0f}")

except Exception as e:
    print(f"  ✗ Error creating grid: {e}")
    import traceback
    traceback.print_exc()
    grid_cells_gdf = gpd.GeoDataFrame(columns=['cell_id', 'population', 'geometry'])

# ============================================================================
# 5g. PHASE 4.2 — GRID TRAVEL TIME TO NEAREST EMS STATION
# ============================================================================
print("5g. COMPUTING GRID TRAVEL TIMES (PHASE 4.2)")
print("-" * 80)

if best_time_s is not None and len(grid_cells_gdf) > 0:
    try:
        _grid_proj = grid_cells_gdf.to_crs(epsg=32636)
        _centroids_proj = _grid_proj.geometry.centroid
        _centroids_wgs = gpd.GeoSeries(_centroids_proj, crs='EPSG:32636').to_crs('EPSG:4326')
        cell_lons = _centroids_wgs.x.values
        cell_lats = _centroids_wgs.y.values

        print(f"  Snapping {len(grid_cells_gdf):,} grid centroids to road network nodes...")
        nearest_nodes = ox.nearest_nodes(G, cell_lons, cell_lats)

        _INF = float('inf')
        travel_times_s = [best_time_s.get(n, _INF) for n in nearest_nodes]

        grid_min_travel_min = [
            round(t / 60.0, 1) if t != _INF else np.nan
            for t in travel_times_s
        ]
        grid_covered = [
            (t <= 10) if not np.isnan(t) else False
            for t in grid_min_travel_min
        ]

        grid_cells_gdf['min_travel_time_min'] = grid_min_travel_min
        grid_cells_gdf['covered_10min'] = grid_covered

        total_cells   = len(grid_cells_gdf)
        covered_cells = int(sum(grid_covered))
        uncovered_cells = total_cells - covered_cells
        uncovered_pop   = float(grid_cells_gdf.loc[~grid_cells_gdf['covered_10min'], 'population'].sum())
        total_grid_pop  = float(grid_cells_gdf['population'].sum())
        uncovered_pop_pct = (uncovered_pop / total_grid_pop * 100) if total_grid_pop > 0 else 0.0

        print(f"  ✓ Travel times assigned to all {total_cells:,} populated grid cells")
        print(f"  Covered cells (≤10 min):   {covered_cells:,}")
        print(f"  Uncovered cells (>10 min): {uncovered_cells:,}")
        print(f"  Uncovered population:      {uncovered_pop:,.0f}")
        print(f"  % population uncovered:    {uncovered_pop_pct:.1f}%")

    except Exception as e:
        print(f"  ✗ Error computing grid travel times: {e}")
        import traceback
        traceback.print_exc()
        grid_cells_gdf['min_travel_time_min'] = np.nan
        grid_cells_gdf['covered_10min'] = False
else:
    print("  ⚠ Skipped (no road network or empty grid)")
    if len(grid_cells_gdf) > 0:
        grid_cells_gdf['min_travel_time_min'] = np.nan
        grid_cells_gdf['covered_10min'] = False

# ============================================================================
# 5h. PHASE 4.3/4.6 — GRID-LEVEL AHP SCORING (REFINED)
# Phase 4.6: travel time capped at 30 min; density_factor 1.2× for pop>=2000/km²
# ============================================================================
print("5h. COMPUTING GRID AHP SCORES (PHASE 4.6 REFINED)")
print("-" * 80)

if len(grid_cells_gdf) > 0 and 'min_travel_time_min' in grid_cells_gdf.columns:
    try:
        grid_cells_gdf['pop_density'] = grid_cells_gdf['population']  # 1km² cells

        grid_cells_gdf['density_high']   = grid_cells_gdf['pop_density'] >= 2000
        grid_cells_gdf['density_factor'] = grid_cells_gdf['density_high'].map({True: 1.2, False: 1.0})

        grid_cells_gdf['exposed_population'] = grid_cells_gdf.apply(
            lambda r: r['population'] if r['covered_10min'] == False else 0.0, axis=1
        )

        grid_cells_gdf['pop_density_effective']        = grid_cells_gdf['pop_density']       * grid_cells_gdf['density_factor']
        grid_cells_gdf['exposed_population_effective'] = grid_cells_gdf['exposed_population'] * grid_cells_gdf['density_factor']

        _RAW_MAX_TRAVEL = grid_cells_gdf['min_travel_time_min'].max()
        _CAP_MINUTES = 30.0
        grid_cells_gdf['travel_time_capped'] = grid_cells_gdf['min_travel_time_min'].clip(upper=_CAP_MINUTES)
        grid_cells_gdf['travel_time_capped'] = grid_cells_gdf['travel_time_capped'].fillna(_CAP_MINUTES)

        print(f"  Travel time before cap — max: {_RAW_MAX_TRAVEL:.1f} min")
        print(f"  Travel time after cap  — max: {grid_cells_gdf['travel_time_capped'].max():.1f} min (cap={_CAP_MINUTES:.0f} min)")

        def _minmax(series):
            mn, mx = series.min(), series.max()
            if mx == mn:
                return pd.Series(0.0, index=series.index)
            return (series - mn) / (mx - mn)

        grid_cells_gdf['norm_access_gap']  = _minmax(grid_cells_gdf['travel_time_capped'])
        grid_cells_gdf['norm_pop_density'] = _minmax(grid_cells_gdf['pop_density_effective'])
        grid_cells_gdf['norm_exposed_pop'] = _minmax(grid_cells_gdf['exposed_population_effective'])

        # --- Compute district-level AHP per preset + one station per high-priority district ---
        _PRESETS = {
            'balanced':   (0.50, 0.30, 0.20),
            'access':     (0.70, 0.15, 0.15),
            'population': (0.20, 0.50, 0.30),
        }

        # --- Official station-proposal rule ---------------------------------
        # Propose a station wherever a HIGH-DENSITY area (>= MIN_DENSITY_PER_KM2
        # residents/km²) CANNOT be reached by any existing station within
        # COVERAGE_MINUTES minutes (realistic road-network travel time).
        # The rule alone decides WHERE a station is proposed; the AHP score only
        # RANKS the resulting proposals — it never affects which cells qualify.
        MIN_DENSITY_PER_KM2 = 2000   # "high-density area" gate (residents/km²)
        COVERAGE_MINUTES    = 10     # must be reachable within this (covered_10min)
        CLUSTER_EPS_M       = 3000   # group qualifying cells within 3 km → 1 station

        def _find_candidates_by_rule(gdf, districts):
            """Official rule: a station is proposed wherever a high-density grid
            cell (>= MIN_DENSITY_PER_KM2 residents/km²) is NOT reachable by an
            existing station within COVERAGE_MINUTES minutes. Qualifying cells
            are clustered (one station per cluster) and the station is placed at
            the population-weighted centroid. The AHP score on each grid cell
            (already computed for the active preset) is attached only to RANK the
            proposals — it never decides which cells qualify."""
            from sklearn.cluster import DBSCAN

            # 1) Rule gate — weight-independent: dense AND not reachable in 10 min
            _qual = gdf[(gdf['pop_density'] >= MIN_DENSITY_PER_KM2) &
                        (gdf['covered_10min'] == False)].copy()
            if len(_qual) == 0:
                return []

            # Project full grid once → centroids + population for served-pop lookup
            _all_proj = gdf.to_crs(epsg=32636)
            _all_c    = _all_proj.geometry.centroid
            _all_cx   = _all_c.x.values
            _all_cy   = _all_c.y.values
            _all_pop  = gdf['population'].values.astype(float)

            # Projected centroids of the qualifying cells
            _qual_proj = _qual.to_crs(epsg=32636)
            _qc        = _qual_proj.geometry.centroid
            _qx        = _qc.x.values
            _qy        = _qc.y.values

            # 2) Cluster qualifying cells into service areas (one station each)
            _labels = DBSCAN(eps=CLUSTER_EPS_M, min_samples=1).fit_predict(
                np.column_stack([_qx, _qy]))
            _qual = _qual.assign(_cluster=_labels, _qx=_qx, _qy=_qy)

            candidates = []
            for _clbl, _grp in _qual.groupby('_cluster'):
                _pops = _grp['population'].values.astype(float)
                _gx   = _grp['_qx'].values
                _gy   = _grp['_qy'].values
                _ptot = _pops.sum()
                if _ptot > 0:
                    _cx = float(np.average(_gx, weights=_pops))
                    _cy = float(np.average(_gy, weights=_pops))
                else:
                    _cx = float(_gx.mean()); _cy = float(_gy.mean())

                _pt = gpd.GeoDataFrame([{'geometry': Point(_cx, _cy)}],
                                       crs='EPSG:32636').to_crs('EPSG:4326')
                _clon = float(_pt.geometry.x.iloc[0])
                _clat = float(_pt.geometry.y.iloc[0])

                # Coverage radius from the spread of the cluster's cells
                _spread = np.sqrt((_gx - _cx) ** 2 + (_gy - _cy) ** 2)
                _radius_m = int(max(1500, min(6000, float(_spread.max()) * 0.6))) \
                    if len(_spread) > 0 else 1500

                # SERVED = everyone within the station's radius;
                # UNCOVERED = the qualifying (dense + currently unreachable) people
                _within = ((_all_cx - _cx) ** 2 + (_all_cy - _cy) ** 2) <= _radius_m ** 2
                _served_pop    = float(_all_pop[_within].sum())
                _uncovered_pop = float(_grp['population'].sum())

                _mean_tt = float(_grp['min_travel_time_min'].dropna().mean()) \
                    if _grp['min_travel_time_min'].notna().any() else np.nan
                _mean_score = float(_grp['ahp_score'].mean()) \
                    if 'ahp_score' in _grp.columns else 0.0

                # District label = the district polygon containing the station
                _dname = ''
                try:
                    _hit = districts[districts.geometry.contains(Point(_clon, _clat))]
                    if len(_hit) > 0:
                        _dname = str(_hit.iloc[0]['NAME_2'])
                except Exception:
                    pass

                candidates.append({
                    'cluster_id': int(_clbl),
                    'cluster_cells_count': int(len(_grp)),
                    'cluster_population_sum': max(_served_pop, _uncovered_pop),
                    'cluster_uncovered_pop_sum': _uncovered_pop,
                    'cluster_mean_score': round(_mean_score, 3),
                    'cluster_mean_travel_time': round(_mean_tt, 1) if not np.isnan(_mean_tt) else np.nan,
                    'cluster_radius_m': _radius_m,
                    'district_name': _dname,
                    'lat': round(_clat, 5), 'lon': round(_clon, 5),
                    'geometry': Point(_clon, _clat),
                })

            if not candidates:
                return []
            # 3) Rank by AHP score (weights rank, not select); uncovered pop tiebreak
            _cand_df = pd.DataFrame(candidates).sort_values(
                ['cluster_mean_score', 'cluster_uncovered_pop_sum'],
                ascending=False
            ).reset_index(drop=True)
            _cand_df['candidate_id'] = _cand_df.index + 1
            return _cand_df.to_dict('records')

        candidates_by_preset = {}
        candidates_gdf = None  # default preset for map layer

        for _preset_name, (_W1, _W2, _W3) in _PRESETS.items():
            # Grid-level scores (for map layers)
            _raw_score = (
                _W1 * grid_cells_gdf['norm_access_gap'] +
                _W2 * grid_cells_gdf['norm_pop_density'] +
                _W3 * grid_cells_gdf['norm_exposed_pop']
            )
            grid_cells_gdf['ahp_score'] = _raw_score.round(3)
            _q80 = _raw_score.quantile(0.80)
            _q50 = _raw_score.quantile(0.50)
            grid_cells_gdf['ahp_priority'] = _raw_score.apply(
                lambda s: 'High' if s >= _q80 else ('Medium' if s >= _q50 else 'Low')
            )

            # Official rule: dense (≥2000/km²) AND unreachable-in-10-min cells → stations
            # (Locations are identical across presets — the rule is weight-independent;
            #  only the AHP ranking differs. Weights rank the proposals, not select them.)
            _cands = _find_candidates_by_rule(grid_cells_gdf, districts_agg)
            candidates_by_preset[_preset_name] = _cands
            print(f"  [{_preset_name}] W=({_W1},{_W2},{_W3}) → {len(_cands)} proposed stations "
                  f"(rule: ≥{MIN_DENSITY_PER_KM2}/km² AND >{COVERAGE_MINUTES} min from any station)")

            # Keep balanced as the default for map layers + display
            if _preset_name == 'balanced':
                candidates_gdf = gpd.GeoDataFrame(_cands, crs='EPSG:4326') if _cands else None

        # Recompute balanced as final state for grid_cells_gdf (used by map layers)
        _W1, _W2, _W3 = _PRESETS['balanced']
        _raw_score = (
            _W1 * grid_cells_gdf['norm_access_gap'] +
            _W2 * grid_cells_gdf['norm_pop_density'] +
            _W3 * grid_cells_gdf['norm_exposed_pop']
        )
        grid_cells_gdf['ahp_score'] = _raw_score.round(3)
        _q80 = _raw_score.quantile(0.80)
        _q50 = _raw_score.quantile(0.50)
        grid_cells_gdf['ahp_priority'] = _raw_score.apply(
            lambda s: 'High' if s >= _q80 else ('Medium' if s >= _q50 else 'Low')
        )

        _high_cells   = (grid_cells_gdf['ahp_priority'] == 'High').sum()
        _medium_cells = (grid_cells_gdf['ahp_priority'] == 'Medium').sum()
        _low_cells    = (grid_cells_gdf['ahp_priority'] == 'Low').sum()
        _high_pop   = grid_cells_gdf.loc[grid_cells_gdf['ahp_priority'] == 'High',   'population'].sum()
        _medium_pop = grid_cells_gdf.loc[grid_cells_gdf['ahp_priority'] == 'Medium', 'population'].sum()
        _low_pop    = grid_cells_gdf.loc[grid_cells_gdf['ahp_priority'] == 'Low',    'population'].sum()

        print(f"  ✓ Refined AHP scores computed for {len(grid_cells_gdf):,} grid cells")
        print(f"  Thresholds: q80={_q80:.3f}, q50={_q50:.3f}")
        print(f"  High   cells: {_high_cells:5,}  — population: {_high_pop:,.0f}")
        print(f"  Medium cells: {_medium_cells:5,}  — population: {_medium_pop:,.0f}")
        print(f"  Low    cells: {_low_cells:5,}  — population: {_low_pop:,.0f}")

    except Exception as e:
        print(f"  ✗ Error computing grid AHP scores: {e}")
        import traceback
        traceback.print_exc()
        candidates_by_preset = {'balanced': [], 'access': [], 'population': []}
else:
    print("  ⚠ Skipped (grid not available or travel times missing)")
    candidates_by_preset = {'balanced': [], 'access': [], 'population': []}

# ============================================================================
# 6. CREATE FOLIUM MAP WITH COLOR-CODED DISTRICTS
# ============================================================================
print("6. CREATING INTERACTIVE MAP")
print("-" * 80)

LEBANON_CENTER = [33.8547, 35.8623]
ZOOM_LEVEL = 8

m = folium.Map(
    location=LEBANON_CENTER,
    zoom_start=ZOOM_LEVEL,
    tiles='CartoDB dark_matter'
)

# Neutral style for district boundaries context layer
def style_district_neutral(feature):
    props = feature['properties']
    covered_10min = props.get('covered', True)
    priority = props.get('ahp_priority', 'Low')
    ahp_colors = {
        'High':   '#e74c3c',
        'Medium': '#f39c12',
        'Low':    '#27ae60',
    }
    return {
        'fillColor': ahp_colors.get(priority, '#27ae60'),
        'color': '#ff4444',
        'weight': 2,
        'fillOpacity': 0.45,
    }

def highlight_district(feature):
    props = feature['properties']
    priority = props.get('ahp_priority', 'Low')
    ahp_colors = {
        'High':   '#e74c3c',
        'Medium': '#f39c12',
        'Low':    '#27ae60',
    }
    return {
        'fillColor': ahp_colors.get(priority, '#27ae60'),
        'color': '#ffffff',
        'weight': 3,
        'fillOpacity': 0.55,
    }

# Prepare district data with all needed fields (use aggregated districts to avoid duplicates)
districts_for_map = districts_agg.copy()

# Create popup HTML field for each district
def make_popup_html(row):
    district_name = row.get('NAME_2', 'Unknown')
    governorate = row.get('NAME_1', 'Unknown')
    population = row.get('population', 0)
    stations = int(row.get('ems_stations', 0))
    min_travel = row.get('min_travel_time_min', np.nan)
    covered_10 = row.get('covered', False)
    ahp_score = row.get('ahp_score', 0)
    ahp_priority = row.get('ahp_priority', 'Low')

    min_travel_str = f"{min_travel:.1f} min" if pd.notna(min_travel) else "—"
    covered_str = "Yes" if covered_10 else "No"

    ahp_colors = {'High': '#e74c3c', 'Medium': '#f39c12', 'Low': '#27ae60'}
    ahp_color = ahp_colors.get(ahp_priority, '#27ae60')

    popup_html = f"""
    <div style="font-family: Arial, sans-serif; min-width: 200px;">
        <h3 style="margin: 0 0 10px 0; color: #333;">{district_name}</h3>
        <p style="margin: 5px 0;"><b>Governorate:</b> {governorate}</p>
        <p style="margin: 5px 0;"><b>Population:</b> {population:,.0f}</p>
        <p style="margin: 5px 0;"><b>EMS Stations:</b> {stations}</p>
        <p style="margin: 5px 0;"><b>Min Travel Time:</b> {min_travel_str}</p>
        <p style="margin: 5px 0;"><b>10-Min Covered:</b> {covered_str}</p>
        <p style="margin: 5px 0;"><b>AHP Score:</b> {ahp_score:.3f}</p>
        <p style="margin: 5px 0;">
            <span style="background-color: {ahp_color}; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px; font-weight: bold;">
                AHP: {ahp_priority.upper()}
            </span>
        </p>
    </div>
    """
    return popup_html

districts_for_map['popup_html'] = districts_for_map.apply(make_popup_html, axis=1)

# Add tooltip access gap message for uncovered districts
districts_for_map['tooltip_access_gap'] = districts_for_map.apply(
    lambda r: 'Access Gap: Outside 10-min coverage' if r.get('covered') == False else '',
    axis=1
)

# Add neutral district boundaries layer with AHP-aware popups
def make_popup(feature):
    return folium.Popup(feature['properties']['popup_html'], max_width=300)

folium.GeoJson(
    districts_for_map.to_json(),
    style_function=style_district_neutral,
    highlight_function=highlight_district,
    popup=make_popup,
    name='District Boundaries'
).add_to(m)

print(f"  ✓ Added {len(districts_agg)} district boundaries")

# Add population heatmap
print("  Adding population heatmap...")
sample_step = max(1, min(50, raster_width // 100, raster_height // 100))
heatmap_data = []

for y in range(0, raster_height, sample_step):
    for x in range(0, raster_width, sample_step):
        pixel_value = raster_data[y, x]
        if raster_nodata is not None and pixel_value == raster_nodata:
            continue
        if np.isnan(pixel_value) or pixel_value <= 0:
            continue
        
        lon, lat = xy(raster_transform, y, x)
        heatmap_data.append([lat, lon, float(pixel_value)])

if heatmap_data:
    plugins.HeatMap(
        heatmap_data,
        min_opacity=0.2,
        max_zoom=18,
        radius=15,
        blur=15,
        gradient={0.2: 'blue', 0.4: 'cyan', 0.6: 'lime', 0.8: 'yellow', 1.0: 'red'},
        name='Population Heatmap'
    ).add_to(m)
    print(f"  ✓ Added population heatmap ({len(heatmap_data)} points)")

# Add 10-min coverage layer (Step 1C)
if coverage_gdf is not None and len(coverage_gdf) > 0:
    folium.GeoJson(
        coverage_gdf.to_json(),
        style_function=lambda x: {
            'fillColor': '#4a9eff',
            'color': '#2e86de',
            'weight': 1,
            'fillOpacity': 0.35,
        },
        name='10-Min Coverage (Road Time)'
    ).add_to(m)
    print(f"  ✓ Added 10-Min Coverage (Road Time) layer")

# Add AHP Priority layer (Phase 3.2)
def style_ahp(feature):
    props = feature['properties']
    priority = props.get('ahp_priority', 'Low')
    covered_10min = props.get('covered', True)
    ahp_colors = {
        'High':   '#e74c3c',
        'Medium': '#f39c12',
        'Low':    '#27ae60',
    }
    # Preserve access-gap border emphasis
    if covered_10min == False:
        border_color = '#ff4444'
        border_weight = 2.5
    else:
        border_color = 'white'
        border_weight = 1
    return {
        'fillColor': ahp_colors.get(priority, '#27ae60'),
        'color': border_color,
        'weight': border_weight,
        'fillOpacity': 0.45,
    }

ahp_layer = folium.FeatureGroup(name='AHP Priority (District Level)', show=False)
folium.GeoJson(
    districts_for_map.to_json(),
    style_function=style_ahp,
    highlight_function=highlight_district,
    popup=make_popup,
).add_to(ahp_layer)
ahp_layer.add_to(m)
print(f"  ✓ Added AHP Priority layer")

# Grid AHP Priority layers (Phase 4.4)
if len(grid_cells_gdf) > 0 and 'ahp_priority' in grid_cells_gdf.columns:
    try:
        _AHP_COLORS = {'High': '#e74c3c', 'Medium': '#f39c12', 'Low': '#27ae60'}

        def _style_grid_cell(feature):
            priority = feature['properties'].get('ahp_priority', 'Low')
            return {
                'fillColor': _AHP_COLORS.get(priority, '#27ae60'),
                'color':     _AHP_COLORS.get(priority, '#27ae60'),
                'weight':    0.4,
                'fillOpacity': 0.35,
            }

        for _priority_set, _layer_name in [
            (['High', 'Medium'], 'Grid AHP Priority (High+Medium)'),
            (['Low'],            'Grid AHP Priority (Low)'),
        ]:
            _subset = grid_cells_gdf[grid_cells_gdf['ahp_priority'].isin(_priority_set)].copy()
            _subset_proj = _subset.to_crs(epsg=32636)
            _subset_proj['geometry'] = _subset_proj.geometry.simplify(tolerance=50, preserve_topology=True)
            _subset = _subset_proj.to_crs('EPSG:4326')
            _slim = _subset[['cell_id', 'population', 'min_travel_time_min', 'ahp_score', 'ahp_priority', 'geometry']].copy()
            _slim['ahp_score']          = _slim['ahp_score'].round(3)
            _slim['min_travel_time_min'] = _slim['min_travel_time_min'].round(1)

            _layer = folium.FeatureGroup(name=_layer_name, show=False)
            folium.GeoJson(
                _slim.to_json(),
                style_function=_style_grid_cell,
                tooltip=folium.GeoJsonTooltip(
                    fields=['ahp_priority', 'ahp_score', 'population', 'min_travel_time_min'],
                    aliases=['Priority', 'AHP Score', 'Population', 'Travel Time (min)'],
                    localize=True,
                ),
            ).add_to(_layer)
            _layer.add_to(m)
            print(f"  ✓ Added {_layer_name} layer — {len(_slim):,} cells")

    except Exception as e:
        print(f"  ✗ Error adding grid AHP layer: {e}")
        import traceback
        traceback.print_exc()

# Candidate EMS station layer (Phase 4.5/4.7)
# Build union of all preset candidates for map markers (JS will show/hide per preset)
_all_candidates_map = {}
for _pname, _precs in candidates_by_preset.items():
    for _c in _precs:
        _key = (round(float(_c['lat']), 5), round(float(_c['lon']), 5))
        if _key not in _all_candidates_map:
            _all_candidates_map[_key] = _c
all_candidates_for_map = list(_all_candidates_map.values())

_CANDIDATE_COLOR = '#00cec9'  # Teal — distinct from red stations and priority colors
if len(all_candidates_for_map) > 0:
    try:
        _candidates_layer = folium.FeatureGroup(name='Suggested New EMS Stations', show=True)
        for _cand in all_candidates_for_map:
            _cid      = int(_cand['candidate_id'])
            _upop     = int(_cand['cluster_uncovered_pop_sum'])
            _score    = float(_cand['cluster_mean_score'])
            _lat      = float(_cand['lat'])
            _lon      = float(_cand['lon'])
            _radius_m = int(_cand.get('cluster_radius_m', 1500))
            _tt_val   = _cand['cluster_mean_travel_time']
            _tt_str   = f"{_tt_val:.1f} min" if (_tt_val is not None and not (isinstance(_tt_val, float) and np.isnan(_tt_val))) else 'N/A'

            _popup_html = f"""<div style="font-family:Arial,sans-serif;min-width:200px;">
                <div style="background:{_CANDIDATE_COLOR};color:#fff;padding:6px 10px;margin:-10px -10px 8px;font-weight:bold;border-radius:3px 3px 0 0;">
                    Proposed Station #{_cid}
                </div>
                <b>Population served:</b> {int(round(_cand['cluster_population_sum'])):,}<br>
                <b>Currently uncovered:</b> {_upop:,}<br>
                <b>Avg travel time:</b> {_tt_str}<br>
                <b>Coverage radius:</b> {_radius_m:,} m<br>
                <b>AHP score:</b> {_score:.3f}
            </div>"""

            # Pin marker: circle with + icon and triangular pointer
            _icon_html = f"""
                <div style="display:flex;flex-direction:column;align-items:center;">
                    <div style="width:24px;height:24px;background:{_CANDIDATE_COLOR};border:2px solid #fff;
                        border-radius:50%;display:flex;align-items:center;justify-content:center;
                        font-size:15px;font-weight:900;color:#fff;
                        box-shadow:0 2px 6px rgba(0,0,0,0.5);line-height:1;">+</div>
                    <div style="width:0;height:0;
                        border-left:6px solid transparent;
                        border-right:6px solid transparent;
                        border-top:9px solid {_CANDIDATE_COLOR};
                        margin-top:-1px;"></div>
                </div>"""

            folium.Marker(
                location=[_lat, _lon],
                icon=DivIcon(html=_icon_html, icon_size=(24, 34), icon_anchor=(12, 34)),
                popup=folium.Popup(_popup_html, max_width=240),
            ).add_to(_candidates_layer)

            # Coverage ring sized to actual cluster spread
            folium.Circle(
                location=[_lat, _lon],
                radius=_radius_m,
                color=_CANDIDATE_COLOR,
                weight=1.5,
                dash_array='6 4',
                fill=True,
                fill_color=_CANDIDATE_COLOR,
                fill_opacity=0.07,
            ).add_to(_candidates_layer)

        _candidates_layer.add_to(m)
        print(f"  ✓ Added Suggested New EMS Stations layer — {len(all_candidates_for_map)} candidates across all presets (teal, visible by default)")
    except Exception as e:
        print(f"  ✗ Error adding candidate layer: {e}")
        import traceback
        traceback.print_exc()

folium.LayerControl().add_to(m)

# Save map temporarily to extract HTML
temp_map_file = os.path.join(DATA_DIR, 'temp_map.html')
m.save(temp_map_file)

# Read the map HTML
with open(temp_map_file, 'r', encoding='utf-8') as f:
    map_html = f.read()

# Clean up temp file
os.remove(temp_map_file)

print("  ✓ Map generated")

# ============================================================================
# 7. CALCULATE ANALYTICS FOR DASHBOARD
# ============================================================================
print("7. CALCULATING ANALYTICS")
print("-" * 80)

# National summary (use aggregated districts)
total_stations = len(ems_valid)
total_pop = districts_agg['population'].sum()
total_districts = len(districts_agg)
avg_stations_per_100k = (total_stations / total_pop * 100000) if total_pop > 0 else 0

# Coverage KPIs (10-min travel time)
uncovered_mask = districts_agg['covered'] == False
uncovered_districts_count = int(uncovered_mask.sum())
total_districts_count = len(districts_agg)
uncovered_population = float(districts_agg.loc[uncovered_mask, 'population'].sum())
total_population = float(districts_agg['population'].sum())
uncovered_population_percent = (uncovered_population / total_population * 100) if total_population > 0 else 0.0

print("  ✓ Analytics calculated")

# ============================================================================
# 8. CREATE DASHBOARD HTML
# ============================================================================
print("8. CREATING DASHBOARD HTML")
print("-" * 80)

# Extract map div and scripts from Folium HTML
# Folium HTML structure: scripts are in <head> and inline in <body>
# We need to extract:
# 1. All <head> content (for CSS and external scripts)
# 2. Map div from <body>
# 3. All <script> tags (both in head and body)

import re

# Extract head content
head_start = map_html.find('<head>')
head_end = map_html.find('</head>')
if head_start != -1 and head_end != -1:
    folium_head = map_html[head_start + 6:head_end]
else:
    folium_head = ''

# Extract body content
body_start = map_html.find('<body>')
body_end = map_html.find('</body>')
if body_start == -1 or body_end == -1:
    print("  ✗ Error: Could not find body tags in Folium HTML")
    sys.exit(1)
    
body_content = map_html[body_start + 6:body_end]  # +6 to skip '<body>'

# Extract map div (the folium-map div)
map_div_match = re.search(r'<div[^>]*class=["\']folium-map["\'][^>]*>.*?</div>', body_content, re.DOTALL)
if map_div_match:
    map_div = map_div_match.group()
else:
    # Fallback: get everything in body that's not a script
    map_div = re.sub(r'<script.*?</script>', '', body_content, flags=re.DOTALL).strip()

# Extract all script tags from entire HTML (both head and body)
all_scripts = re.findall(r'<script[^>]*>.*?</script>', map_html, re.DOTALL)
scripts = '\n'.join(all_scripts)

if not scripts:
    print("  ⚠ Warning: No scripts found in Folium HTML")
else:
    print(f"  ✓ Extracted {len(all_scripts)} script tags")

# Also extract head content for any styles/links Folium might need
head_start = map_html.find('<head>')
head_end = map_html.find('</head>')
if head_start != -1 and head_end != -1:
    folium_head = map_html[head_start + 6:head_end]
else:
    folium_head = ''

# Build DISTRICTS JSON array for client-side filtering
districts_data = []
for idx, row in districts_agg.iterrows():
    _raw_tt = row.get('min_travel_time_min', None)
    districts_data.append({
        'district_name':      str(row.get('NAME_2', 'Unknown')),
        'governorate':        str(row.get('NAME_1', 'Unknown')),
        'population':         float(row.get('population', 0)),
        'stations':           int(row.get('ems_stations', 0)),
        'area_km2':           round(float(row.get('area_km2', 0)), 2),
        'pop_density':        round(float(row.get('pop_density', 0)), 2),
        'exposed_population': float(row.get('exposed_population', 0)),
        'ahp_score':          float(row.get('ahp_score', 0)),
        'ahp_priority':       str(row.get('ahp_priority', 'Low')),
        # Live model fields — used by the Model tab in the dashboard
        'min_travel_time_min': round(float(_raw_tt), 2) if _raw_tt is not None and not pd.isna(_raw_tt) else None,
        'norm_access_gap':    round(float(row.get('norm_access_gap', 0)), 4),
        'norm_pop_density':   round(float(row.get('norm_pop_density', 0)), 4),
        'norm_exposed_pop':   round(float(row.get('norm_exposed_pop', 0)), 4),
    })

districts_json = json.dumps(districts_data)

# Write a small sidecar JSON with district scores so the EMS Copilot backend
# (scripts/copilot_server.py) can answer AHP-aware questions without
# re-running the full pipeline.
AHP_SIDECAR_FILE = os.path.join(DATA_DIR, 'phase1_ahp_districts.json')
try:
    with open(AHP_SIDECAR_FILE, 'w', encoding='utf-8') as _f:
        json.dump(districts_data, _f, indent=2)
    print(f"  ✓ AHP sidecar saved to: {AHP_SIDECAR_FILE}")
except Exception as _e:
    print(f"  ⚠ Could not write AHP sidecar: {_e}")
max_population = int(districts_agg['population'].max()) if len(districts_agg) > 0 else 0
governorates_list = sorted(districts_agg['NAME_1'].unique().tolist())

# Build STATIONS array with district_name for map filtering (Phase 1.3)
stations_data = []
for idx in ems_valid.index:
    row = ems_valid.loc[idx]
    lat_val = float(row[lat_col])
    lon_val = float(row[lon_col])
    if idx in ems_in_districts.index and pd.notna(ems_in_districts.loc[idx].get('index_right')):
        idx_right = int(ems_in_districts.loc[idx, 'index_right'])
        district_name = str(districts_gdf.loc[idx_right, 'NAME_2'])
        governorate = str(districts_gdf.loc[idx_right, 'NAME_1'])
    else:
        district_name = 'Unknown'
        governorate = 'Unknown'
    stations_data.append({
        'lat': lat_val,
        'lon': lon_val,
        'district_name': district_name,
        'governorate': governorate
    })
stations_json = json.dumps(stations_data)

# ---- Phase 2: hospital districts-data + hospital supply array ----
def build_hospital_districts_data(d):
    out = []
    for _, row in d.iterrows():
        tt = row.get('min_travel_time_min', None)
        out.append({
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
            'norm_bed_gap': round(float(row.get('norm_bed_gap', 0)), 4),
            'beds_per_1000': round(float(row.get('beds_per_1000', 0)), 2),
            'need_class': str(row.get('need_class', 'ADEQUATE')),
        })
    return out

hospital_districts_data = build_hospital_districts_data(hosp_districts)

def _clean_str(val):
    # Blank CSV cells arrive as NaN; str(NaN) == 'nan' (truthy), so coerce to ''.
    if val is None or pd.isna(val):
        return ''
    return str(val).strip()

hospitals_supply = []
for _, r in hospitals_df.iterrows():
    nm = _clean_str(r['name'])
    hospitals_supply.append({
        'lat': float(r['lat']), 'lon': float(r['lon']),
        'name': nm if nm else 'Unnamed hospital',
        'beds': int(r['beds']), 'beds_estimated': bool(r['beds_estimated']),
        'operator': _clean_str(r.get('operator', '')),
    })

# Hospital proposals are deferred to a follow-up task (the grid/clustering
# logic is EMS-specific); ship empty presets for now.
hospital_candidates_by_preset = {'balanced': [], 'access': [], 'population': []}

# Lebanon bounds for Reset Map View
LEBANON_BOUNDS = [[33.05, 35.09], [34.69, 36.62]]

# ============================================================================
# Build dashboard HTML from templates
# ============================================================================

# Load template files
with open(os.path.join(TEMPLATES_DIR, 'phase1_ahp_dashboard.html'), 'r', encoding='utf-8') as f:
    html_template = f.read()
with open(os.path.join(TEMPLATES_DIR, 'phase1_ahp_dashboard.css'), 'r', encoding='utf-8') as f:
    css_content = f.read()
with open(os.path.join(TEMPLATES_DIR, 'phase1_ahp_dashboard.js'), 'r', encoding='utf-8') as f:
    js_logic = f.read()

# Build the panel HTML (contains Python-computed values)
panel_html = f"""            <div class="panel-header">
                <h1>Lebanon EMS – AHP Coverage Analysis</h1>
                <p>Population-Weighted Gap Assessment (Experimental)</p>
                <div class="dataset-selector">
                    <label for="dataset-select">Dataset</label>
                    <select id="dataset-select">
                        <option value="ems" selected>EMS Stations</option>
                        <option value="hospitals">Hospitals</option>
                    </select>
                </div>
            </div>
            <div class="tab-bar">
                <button class="tab-btn active" data-tab="model" onclick="switchTab('model')">Model</button>
                <button class="tab-btn" data-tab="analysis" onclick="switchTab('analysis')">Analysis</button>
                <button class="tab-btn" data-tab="filters" onclick="switchTab('filters')">Filters</button>
            </div>
            <div class="tab-panels">

                <!-- ── ANALYSIS TAB ── -->
                <div class="tab-panel" id="tab-analysis">

                    <div class="summary-grid" style="margin-bottom:14px;">
                        <div class="stat-card">
                            <div class="label">EMS Stations</div>
                            <div class="value">{total_stations}</div>
                        </div>
                        <div class="stat-card">
                            <div class="label">Population</div>
                            <div class="value">{total_pop:,.0f}</div>
                        </div>
                        <div class="stat-card">
                            <div class="label">Uncovered Districts</div>
                            <div class="value" style="color:#e74c3c">{uncovered_districts_count} / {total_districts_count}</div>
                        </div>
                        <div class="stat-card">
                            <div class="label">Pop. Outside 10-Min</div>
                            <div class="value" style="color:#f39c12">{uncovered_population_percent:.1f}%</div>
                        </div>
                    </div>

                    <div class="analysis-controls">
                        <input type="text" id="district-search" class="district-search" placeholder="Search district…" style="flex:1;margin-bottom:0;">
                        <select id="filter-governorate" class="filter-select" style="flex:1;">
                            <option value="">All Governorates</option>
                        </select>
                        <button id="reset-map-view" class="filter-reset-btn" style="white-space:nowrap;">Reset Map</button>
                    </div>
                    <div id="filtered-out-msg" class="filtered-out-msg" style="display:none;"></div>

                    <div class="section-header" style="margin-top:14px;">District Ranking</div>
                    <div class="ahp-ranking-controls">
                        <span class="filter-label">Show</span>
                        <select id="ahp-ranking-limit" class="filter-select" style="width:auto;padding:4px 8px;">
                            <option value="10">Top 10</option>
                            <option value="20">Top 20</option>
                            <option value="all">All</option>
                        </select>
                    </div>
                    <div id="ahp-ranking-table"></div>

                    <div style="display:flex;align-items:center;justify-content:space-between;margin-top:18px;margin-bottom:6px;">
                        <div class="section-header" style="margin:0;">Recommended New Stations</div>
                        <select id="candidates-limit" class="filter-select" style="width:auto;padding:4px 8px;">
                            <option value="5">Top 5</option>
                            <option value="10" selected>Top 10</option>
                            <option value="all">All</option>
                        </select>
                    </div>
                    <div id="candidates-list"></div>

                </div>

                <!-- ── FILTERS TAB (rendered by JS) ── -->
                <div class="tab-panel" id="tab-filters"><!-- rendered by renderFiltersTab() --></div>

                <!-- ── MODEL TAB (rendered by JS) ── -->
                <div class="tab-panel active" id="tab-model"><!-- rendered by renderModelTab() --></div>

            </div>"""

# Build CANDIDATES_BY_PRESET JSON for dashboard panel (Phase 4.7)
def _build_candidates_list(records):
    result = []
    for _c in records:
        _mean_tt = round(float(_c['cluster_mean_travel_time']), 1) if pd.notna(_c['cluster_mean_travel_time']) else None
        result.append({
            'rank':                 int(_c['candidate_id']),
            'cluster_id':          int(_c['cluster_id']),
            'lat':                  round(float(_c['lat']), 5),
            'lon':                  round(float(_c['lon']), 5),
            'cells':               int(_c['cluster_cells_count']),
            'population':          int(round(_c['cluster_population_sum'])),
            'uncovered_population': int(round(_c['cluster_uncovered_pop_sum'])),
            'mean_score':          round(float(_c['cluster_mean_score']), 3),
            'mean_travel_time':    _mean_tt,
            'radius_m':            int(_c.get('cluster_radius_m', 1500)),
            'district_name':       _c.get('district_name', ''),
        })
    return result

candidates_by_preset_json = {}
for _pname, _precs in candidates_by_preset.items():
    candidates_by_preset_json[_pname] = _build_candidates_list(_precs)

all_presets_json = json.dumps(candidates_by_preset_json)
# CANDIDATES defaults to the balanced preset for backward compat
balanced_json = json.dumps(candidates_by_preset_json.get('balanced', []))

# Build JS data block (Python-computed constants injected into JS scope)
datasets_obj = {
    'ems': {
        'label': 'EMS Stations',
        'supplyLabel': 'EMS Stations',
        'supplyIcon': 'ambulance',
        'threshold': EMS_THRESHOLD_MIN,
        'criteria': CRITERIA_CONFIG,
        'districts': districts_data,            # existing EMS districts list
        'supply': stations_data,                # existing EMS supply list
        'candidatesByPreset': candidates_by_preset_json,
    },
    'hospitals': {
        'label': 'Hospitals',
        'supplyLabel': 'Hospitals',
        'supplyIcon': 'hospital',
        'threshold': HOSPITAL_THRESHOLD_MIN,
        'criteria': HOSPITAL_CRITERIA_CONFIG,
        'districts': hospital_districts_data,
        'supply': hospitals_supply,
        'candidatesByPreset': hospital_candidates_by_preset,
        'bedBenchmark': BED_BENCHMARK,
    },
}
js_data = f"""        const DATASETS = {json.dumps(datasets_obj)};
        let ACTIVE_DATASET = 'ems';
        const GOVERNORATES = {json.dumps(governorates_list)};
        const MAX_POP = {max_population};
        const LEBANON_BOUNDS = {json.dumps(LEBANON_BOUNDS)};"""

# Assemble final HTML by replacing sentinels in the template
dashboard_html = (
    html_template
    .replace('%%FOLIUM_HEAD%%', folium_head)
    .replace('%%CSS_CONTENT%%', css_content)
    .replace('%%MAP_DIV%%', map_div)
    .replace('%%PANEL_HTML%%', panel_html)
    .replace('%%JS_DATA%%', js_data)
    .replace('%%JS_LOGIC%%', js_logic)
    .replace('%%FOLIUM_SCRIPTS%%', scripts)
)

# Save dashboard
with open(OUTPUT_DASHBOARD_FILE, 'w', encoding='utf-8') as f:
    f.write(dashboard_html)

print(f"  ✓ Dashboard saved to: {OUTPUT_DASHBOARD_FILE}")

# ============================================================================
# 9. PRINT SUMMARY
# ============================================================================
print()
print("=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"Districts loaded: {len(districts_agg)} (unique)")
print(f"EMS stations plotted: {len(ems_valid)}")
print(f"Total population: {total_population:,.0f}")
_high_count   = (districts_agg['ahp_priority'] == 'High').sum()
_medium_count = (districts_agg['ahp_priority'] == 'Medium').sum()
_low_count    = (districts_agg['ahp_priority'] == 'Low').sum()
print(f"AHP High priority:   {_high_count}")
print(f"AHP Medium priority: {_medium_count}")
print(f"AHP Low priority:    {_low_count}")
print()
print(f"Dashboard saved to: {OUTPUT_DASHBOARD_FILE}")
print("=" * 80)
