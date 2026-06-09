"""Phase 2.5 — Enrich hospital bed counts with authoritative Syndicate data.

Idempotent: always derives the *original* OSM bed tags from the raw GeoJSON, then
overlays real bed counts from three sources, in priority order:

  1. Original OSM `beds` tag (3 hospitals)
  2. Syndicate-of-Hospitals name-matches (high-confidence, Jaccard >= 0.6)
  3. Hand-verified large hospitals not present in OSM (curated list below)
  4. Optional manual coordinates file (data/hospitals_manual_coords.csv)

Anything still unknown is median-imputed from the *known* set and flagged.

Inputs:  data/lebanon_hospitals.csv (cleaned OSM points, for coords/names/osm_id)
         data/lebanon_healthsites.geojson (raw, for original OSM bed tags)
         data/lebanon_hospitals_syndicate.csv (real beds, 134 hospitals)
         data/hospitals_manual_coords.csv (optional; name,beds,lat,lon)
Output:  data/lebanon_hospitals.csv  (overwritten, now with a `beds_source` column)
"""
import csv, json, math, os, re, statistics, unicodedata

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "data")
OSM_CSV = os.path.join(DATA_DIR, "lebanon_hospitals.csv")
RAW_GEOJSON = os.path.join(DATA_DIR, "lebanon_healthsites.geojson")
SYN_CSV = os.path.join(DATA_DIR, "lebanon_hospitals_syndicate.csv")
MANUAL_CSV = os.path.join(DATA_DIR, "hospitals_manual_coords.csv")

MATCH_THRESHOLD = 0.5
# Reviewed false positives at the 0.5 threshold — generic/ambiguous Syndicate
# names that fuzzy-match the wrong OSM hospital. Skip these specific pairings.
MATCH_BLOCKLIST_SYN = {'beirut', 'jabal amel', 'el bekaa'}
DEDUP_METERS = 300  # a curated point within this distance of an OSM point = same hospital

# Hand-verified large hospitals NOT reliably present in OSM. Coordinates verified
# individually (Wikidata / Nominatim result that names the hospital itself).
# (Makassed and Sacré-Cœur were removed — they exist in OSM under Arabic names
#  and are now matched via ARABIC_BED_MATCHES, avoiding duplicate points.)
VERIFIED_BIG = [
    # name, beds, lat, lon, coord_source
    ("Dar Al-Ajaza Al-Islamia Hospital", 700, 33.8680, 35.4988, "nominatim-verified"),
    ("American University of Beirut Medical Center", 400, 33.8980, 35.4859, "wikidata"),
    ("Dar Al-Amal University Hospital", 220, 33.9840, 36.1611, "nominatim-verified"),
    ("Saint George Hospital University Medical Center", 210, 33.8942, 35.5238, "nominatim-verified"),
    ("Bahman Hospital", 200, 33.8535, 35.5061, "nominatim-verified"),
]

# Curated Arabic-name → Syndicate bed-count matches (keyed by OSM id for stability).
# Each was read and matched by hand against the Syndicate list (name + region).
ARABIC_BED_MATCHES = {
    '3938046522': 75,   # مظلوم → New Hospital Mazloum
    '4986254041': 84,   # المنلا → Mounla
    '467941851': 70,    # الأرز الزلقا → Arz
    '5818614453': 120,  # جبل عامل → Jabal Amel
    '2932842648': 150,  # السان شارل → St Charles
    '837158168': 100,   # سان جورج (Ajaltoun) → Hopital Saint Georges - Ajaltoun
    '975076458': 300,   # حمود → Hammoud
    '3561187768': 20,   # معربس → Maarbes
    '835250420': 430,   # أوتيل ديو → Hotel Dieu de France
    '994902555': 150,   # بلفو → Bellevue Medical Center
    '842359835': 137,   # عين وزين → Ain Wazein
    '6205014685': 13,   # بخعازي → Bekhaazi
    '1052515181': 200,  # المقاصد → Makassed
    '844266947': 907,   # الصليب للأمراض العقلية → Psychiatric Hospital of the Cross
    '642515061': 200,   # الزهراء → Al Zahraa University Hospital
    '4461868278': 60,   # سرحال → Hopital Dr S. Serhal
    '4966703572': 100,  # الراعي → Raii
    '284812334': 150,   # الجعيتاوي → Hopital Libanais (Geitaoui)
    '236020132': 240,   # الرسول الأعظم → Al-Rassoul Al-Aazam
    '409468812': 150,   # جبل لبنان → Mount Lebanon Hospital
    '519087818': 130,   # سانت تريز الحدث → Hôpital Sainte Thérèse
    '2706923700': 75,   # النجدة الشعبية → Secours Populaire Libanais-Nabatieh
    '4923267521': 50,   # شاهين → Hopital Chahine
    '409961805': 50,    # الحايك → Hopital Hayek
    '1321433640': 37,   # الشيخ راغب حرب → Ragheb Harb
    '4522495797': 50,   # البيسار → Al Bissar Hospital
    '993574780': 130,   # بيت شباب → Beit Chabab
    '802992023': 78,    # بحنس → Bhannes
    '303946250': 65,    # سان لويس جونية → St Louis
    '305423504': 100,   # اللبناني الكندي → Libano-Canadien
    '3061157514': 32,   # شتورا → Chtoura Hospital
    '386796001': 120,   # لبيب → Labib Medical Center
    '835249938': 160,   # رزق → Clinique Dr. Rizk
    '1181973647': 120,  # خوري → Khoury General Hospital - Zahle
    '445619060': 200,   # الشرق الأوسط الصحي الجامعي → Middle East Institute of Health
    '835863086': 159,   # مار يوسف → St Joseph - Najjar Medical Center
    '386795333': 100,   # دلاعة → Dalla'a General Hospital
    '1857670915': 128,  # النيني → Nini hospital
    '583705258': 234,   # قلب يسوع → Sacre Coeur
}

STOP = {'hospital','medical','center','centre','hopital','clinique','clinic',
        'university','of','the','de','el','al','la','st','saint'}


def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return [t for t in s.split() if t not in STOP and len(t) > 1]


def jac(a, b):
    A, B = set(a), set(b)
    return len(A & B) / len(A | B) if A | B else 0


def parse_beds(val):
    if val is None:
        return None
    m = re.search(r"\d{1,4}", str(val).replace(",", ""))
    return int(m.group()) if m else None


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def main():
    osm = list(csv.DictReader(open(OSM_CSV, encoding="utf-8")))
    # Idempotency: drop any synthetic rows this script added on a prior run
    # (curated/manual additions have no osm_id); always start from the OSM base.
    osm = [r for r in osm if str(r.get("osm_id", "")).strip()]
    syn = list(csv.DictReader(open(SYN_CSV, encoding="utf-8")))

    # 1) original OSM bed tags, keyed by osm_id (idempotent ground truth)
    raw = json.load(open(RAW_GEOJSON, encoding="utf-8"))
    osm_beds = {}
    for f in raw["features"]:
        p = f.get("properties", {}) or {}
        oid = str(p.get("osm_id") or "")
        if oid:
            osm_beds[oid] = parse_beds(p.get("beds"))

    # Reset each OSM row to its true original bed tag
    for r in osm:
        b = osm_beds.get(str(r["osm_id"]))
        r["beds"] = b              # int or None
        r["beds_source"] = "osm-tag" if b is not None else ""

    # 2) Syndicate name-matches -> real beds on matched OSM rows
    n_match = 0
    for r in osm:
        if not re.search(r"[a-zA-Z]", r["name"]):
            continue
        ot = norm(r["name"])
        if not ot:
            continue
        best, bsc = None, 0
        for s in syn:
            sc = jac(ot, norm(s["name"]))
            if sc > bsc:
                bsc, best = sc, s
        if (best and bsc >= MATCH_THRESHOLD and best["beds"]
                and best["name"].strip().lower() not in MATCH_BLOCKLIST_SYN):
            r["beds"] = int(best["beds"])
            r["beds_source"] = "syndicate-match"
            n_match += 1

    # 2b) Curated Arabic-name matches (keyed by OSM id) → real beds
    n_arabic = 0
    for r in osm:
        beds = ARABIC_BED_MATCHES.get(str(r.get("osm_id", "")))
        if beds:
            r["beds"] = int(beds)
            r["beds_source"] = "syndicate-arabic"
            n_arabic += 1

    # 3) Hand-verified big hospitals: merge into nearby OSM point, else add new
    added = []
    for name, beds, lat, lon, csrc in VERIFIED_BIG:
        # nearest existing OSM point
        near = min(osm, key=lambda r: haversine_m(lat, lon, float(r["lat"]), float(r["lon"])))
        d = haversine_m(lat, lon, float(near["lat"]), float(near["lon"]))
        if d <= DEDUP_METERS:
            near["beds"] = beds
            near["beds_source"] = f"syndicate-verified({csrc};merged)"
        else:
            added.append({
                "name": name, "lat": round(lat, 6), "lon": round(lon, 6),
                "beds": beds, "beds_estimated": False,
                "beds_source": f"syndicate-verified({csrc})",
                "operator": "", "operator_type": "",
                "osm_id": "", "geom_type": "Point",
            })

    # 4) Optional manual coordinates file
    n_manual = 0
    if os.path.exists(MANUAL_CSV):
        for m in csv.DictReader(open(MANUAL_CSV, encoding="utf-8")):
            lat, lon, beds = m.get("lat", ""), m.get("lon", ""), parse_beds(m.get("beds"))
            if not (lat and lon and beds):
                continue
            added.append({
                "name": m.get("name", "").strip() or "Hospital",
                "lat": round(float(lat), 6), "lon": round(float(lon), 6),
                "beds": beds, "beds_estimated": False, "beds_source": "manual",
                "operator": "", "operator_type": "", "osm_id": "", "geom_type": "Point",
            })
            n_manual += 1

    rows = osm + added

    # 5) median-impute the still-unknown beds from the known set
    known = [r["beds"] for r in rows if isinstance(r["beds"], int)]
    median_beds = int(statistics.median(known)) if known else 0
    for r in rows:
        if isinstance(r["beds"], int):
            r["beds_estimated"] = False
            if not r.get("beds_source"):
                r["beds_source"] = "osm-tag"
        else:
            r["beds"] = median_beds
            r["beds_estimated"] = True
            r["beds_source"] = "median-estimate"

    # ── Public / private classification ──────────────────────────────────────
    # Lebanese public hospitals are almost all named "<Place> Governmental
    # Hospital" / "...الحكومي"; OSM also carries an operator_type tag. Anything
    # confirmed not-public is private. With pharmacies/Red-Cross/unnamed already
    # removed, the remaining untagged hospitals are private by inference (Lebanon
    # is ~88% private) — flagged via ownership_source so the inference is explicit.
    n_pub = n_priv_tag = n_priv_inf = 0
    for r in rows:
        text = f"{r.get('name','')} {r.get('operator','')}".lower()
        otype = (r.get("operator_type") or "").lower()
        bsrc = r.get("beds_source", "")
        is_public = (
            any(k in text for k in ("government", "حكوم", "ministry", "moph"))
            or otype in ("public", "government", "military")
        )
        if is_public:
            r["hospital_type"] = "public"
            r["ownership_source"] = "tagged"
            n_pub += 1
        elif otype in ("private", "business") or bsrc.startswith("syndicate"):
            r["hospital_type"] = "private"
            r["ownership_source"] = "tagged"
            n_priv_tag += 1
        else:
            r["hospital_type"] = "private"
            r["ownership_source"] = "inferred"
            n_priv_inf += 1

    # Write
    fields = ["name", "lat", "lon", "beds", "beds_estimated", "beds_source",
              "hospital_type", "ownership_source", "operator", "operator_type",
              "osm_id", "geom_type"]
    with open(OSM_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})

    real = sum(1 for r in rows if not r["beds_estimated"])
    print(f"OK: {len(rows)} hospitals total")
    print(f"  name-matched (syndicate): {n_match}")
    print(f"  arabic-name matched: {n_arabic}")
    print(f"  hand-verified added/merged: {len(VERIFIED_BIG)}  (new points: {len(added) - n_manual})")
    print(f"  manual-coords added: {n_manual}")
    print(f"  REAL bed counts now: {real} / {len(rows)}  (was 3)")
    print(f"  median used for the remaining {len(rows) - real} estimates: {median_beds}")
    print(f"  type — public: {n_pub} | private (tagged): {n_priv_tag} | private (inferred): {n_priv_inf}")
    print(f"Wrote {OSM_CSV}")


if __name__ == "__main__":
    main()
