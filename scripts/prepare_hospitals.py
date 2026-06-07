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
