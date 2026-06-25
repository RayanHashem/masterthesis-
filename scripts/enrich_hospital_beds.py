import csv ,json ,math ,os ,re ,statistics ,unicodedata 

SCRIPT_DIR =os .path .dirname (os .path .abspath (__file__ ))
DATA_DIR =os .path .join (os .path .dirname (SCRIPT_DIR ),"data")
OSM_CSV =os .path .join (DATA_DIR ,"lebanon_hospitals.csv")
RAW_GEOJSON =os .path .join (DATA_DIR ,"lebanon_healthsites.geojson")
SYN_CSV =os .path .join (DATA_DIR ,"lebanon_hospitals_syndicate.csv")
MANUAL_CSV =os .path .join (DATA_DIR ,"hospitals_manual_coords.csv")

MATCH_THRESHOLD =0.5 

MATCH_BLOCKLIST_SYN ={'beirut','jabal amel','el bekaa'}
DEDUP_METERS =300 

VERIFIED_BIG =[

("Dar Al-Ajaza Al-Islamia Hospital",700 ,33.8680 ,35.4988 ,"nominatim-verified"),
("American University of Beirut Medical Center",400 ,33.8980 ,35.4859 ,"wikidata"),
("Dar Al-Amal University Hospital",220 ,33.9840 ,36.1611 ,"nominatim-verified"),
("Saint George Hospital University Medical Center",210 ,33.8942 ,35.5238 ,"nominatim-verified"),
("Bahman Hospital",200 ,33.8535 ,35.5061 ,"nominatim-verified"),
]

ARABIC_BED_MATCHES ={
'3938046522':75 ,
'4986254041':84 ,
'467941851':70 ,
'5818614453':120 ,
'2932842648':150 ,
'837158168':100 ,
'975076458':300 ,
'3561187768':20 ,
'835250420':430 ,
'994902555':150 ,
'842359835':137 ,
'6205014685':13 ,
'1052515181':200 ,
'844266947':907 ,
'642515061':200 ,
'4461868278':60 ,
'4966703572':100 ,
'284812334':150 ,
'236020132':240 ,
'409468812':150 ,
'519087818':130 ,
'2706923700':75 ,
'4923267521':50 ,
'409961805':50 ,
'1321433640':37 ,
'4522495797':50 ,
'993574780':130 ,
'802992023':78 ,
'303946250':65 ,
'305423504':100 ,
'3061157514':32 ,
'386796001':120 ,
'835249938':160 ,
'1181973647':120 ,
'445619060':200 ,
'835863086':159 ,
'386795333':100 ,
'1857670915':128 ,
'583705258':234 ,
}

PUBLIC_BED_MATCHES ={

'993570500':(544 ,'wikipedia'),

'837909683':(122 ,'moph-locator'),
'1053701650':(100 ,'moph-locator'),
'838327593':(78 ,'moph-locator'),
'842721483':(59 ,'moph-locator'),
'1041902677':(32 ,'moph-locator'),
'836106045':(55 ,'moph-locator'),
'1015151934':(55 ,'moph-locator'),
'844274432':(20 ,'moph-locator'),
'843152614':(44 ,'moph-locator'),
'943312183':(57 ,'moph-locator'),
'1049394290':(38 ,'moph-locator'),
'837390755':(39 ,'moph-locator'),
}

STOP ={'hospital','medical','center','centre','hopital','clinique','clinic',
'university','of','the','de','el','al','la','st','saint'}

def norm (s ):
    s =unicodedata .normalize ('NFKD',s ).encode ('ascii','ignore').decode ().lower ()
    s =re .sub (r'[^a-z0-9 ]',' ',s )
    return [t for t in s .split ()if t not in STOP and len (t )>1 ]

def jac (a ,b ):
    A ,B =set (a ),set (b )
    return len (A &B )/len (A |B )if A |B else 0 

def parse_beds (val ):
    if val is None :
        return None 
    m =re .search (r"\d{1,4}",str (val ).replace (",",""))
    return int (m .group ())if m else None 

def haversine_m (lat1 ,lon1 ,lat2 ,lon2 ):
    R =6371000 
    p1 ,p2 =math .radians (lat1 ),math .radians (lat2 )
    dp =math .radians (lat2 -lat1 )
    dl =math .radians (lon2 -lon1 )
    a =math .sin (dp /2 )**2 +math .cos (p1 )*math .cos (p2 )*math .sin (dl /2 )**2 
    return 2 *R *math .asin (math .sqrt (a ))

def main ():
    osm =list (csv .DictReader (open (OSM_CSV ,encoding ="utf-8")))

    osm =[r for r in osm if str (r .get ("osm_id","")).strip ()]
    syn =list (csv .DictReader (open (SYN_CSV ,encoding ="utf-8")))

    raw =json .load (open (RAW_GEOJSON ,encoding ="utf-8"))
    osm_beds ={}
    for f in raw ["features"]:
        p =f .get ("properties",{})or {}
        oid =str (p .get ("osm_id")or "")
        if oid :
            osm_beds [oid ]=parse_beds (p .get ("beds"))

    for r in osm :
        b =osm_beds .get (str (r ["osm_id"]))
        r ["beds"]=b 
        r ["beds_source"]="osm-tag"if b is not None else ""

    n_match =0 
    for r in osm :
        if not re .search (r"[a-zA-Z]",r ["name"]):
            continue 
        ot =norm (r ["name"])
        if not ot :
            continue 
        best ,bsc =None ,0 
        for s in syn :
            sc =jac (ot ,norm (s ["name"]))
            if sc >bsc :
                bsc ,best =sc ,s 
        if (best and bsc >=MATCH_THRESHOLD and best ["beds"]
        and best ["name"].strip ().lower ()not in MATCH_BLOCKLIST_SYN ):
            r ["beds"]=int (best ["beds"])
            r ["beds_source"]="syndicate-match"
            n_match +=1 

    n_arabic =0 
    for r in osm :
        beds =ARABIC_BED_MATCHES .get (str (r .get ("osm_id","")))
        if beds :
            r ["beds"]=int (beds )
            r ["beds_source"]="syndicate-arabic"
            n_arabic +=1 

    n_public =0 
    for r in osm :
        match =PUBLIC_BED_MATCHES .get (str (r .get ("osm_id","")))
        if match :
            beds ,src =match 
            r ["beds"]=int (beds )
            r ["beds_source"]=f"public-{src }"
            n_public +=1 

    added =[]
    for name ,beds ,lat ,lon ,csrc in VERIFIED_BIG :

        near =min (osm ,key =lambda r :haversine_m (lat ,lon ,float (r ["lat"]),float (r ["lon"])))
        d =haversine_m (lat ,lon ,float (near ["lat"]),float (near ["lon"]))
        if d <=DEDUP_METERS :
            near ["beds"]=beds 
            near ["beds_source"]=f"syndicate-verified({csrc };merged)"
        else :
            added .append ({
            "name":name ,"lat":round (lat ,6 ),"lon":round (lon ,6 ),
            "beds":beds ,"beds_estimated":False ,
            "beds_source":f"syndicate-verified({csrc })",
            "operator":"","operator_type":"",
            "osm_id":"","geom_type":"Point",
            })

    n_manual =0 
    if os .path .exists (MANUAL_CSV ):
        for m in csv .DictReader (open (MANUAL_CSV ,encoding ="utf-8")):
            lat ,lon ,beds =m .get ("lat",""),m .get ("lon",""),parse_beds (m .get ("beds"))
            if not (lat and lon and beds ):
                continue 
            added .append ({
            "name":m .get ("name","").strip ()or "Hospital",
            "lat":round (float (lat ),6 ),"lon":round (float (lon ),6 ),
            "beds":beds ,"beds_estimated":False ,"beds_source":"manual",
            "operator":"","operator_type":"","osm_id":"","geom_type":"Point",
            })
            n_manual +=1 

    rows =osm +added 

    known =[r ["beds"]for r in rows if isinstance (r ["beds"],int )]
    median_beds =int (statistics .median (known ))if known else 0 
    for r in rows :
        if isinstance (r ["beds"],int ):
            r ["beds_estimated"]=False 
            if not r .get ("beds_source"):
                r ["beds_source"]="osm-tag"
        else :
            r ["beds"]=median_beds 
            r ["beds_estimated"]=True 
            r ["beds_source"]="median-estimate"

    n_pub =n_priv_tag =n_priv_inf =0 
    for r in rows :
        text =f"{r .get ('name','')} {r .get ('operator','')}".lower ()
        otype =(r .get ("operator_type")or "").lower ()
        bsrc =r .get ("beds_source","")
        is_public =(
        any (k in text for k in ("government","حكوم","ministry","moph"))
        or otype in ("public","government","military")
        )
        if is_public :
            r ["hospital_type"]="public"
            r ["ownership_source"]="tagged"
            n_pub +=1 
        elif otype in ("private","business")or bsrc .startswith ("syndicate"):
            r ["hospital_type"]="private"
            r ["ownership_source"]="tagged"
            n_priv_tag +=1 
        else :
            r ["hospital_type"]="private"
            r ["ownership_source"]="inferred"
            n_priv_inf +=1 

    fields =["name","lat","lon","beds","beds_estimated","beds_source",
    "hospital_type","ownership_source","operator","operator_type",
    "osm_id","geom_type"]
    with open (OSM_CSV ,"w",newline ="",encoding ="utf-8")as fh :
        w =csv .DictWriter (fh ,fieldnames =fields )
        w .writeheader ()
        for r in rows :
            w .writerow ({k :r .get (k ,"")for k in fields })

    feats =[{
    "type":"Feature",
    "geometry":{"type":"Point",
    "coordinates":[round (float (r ["lon"]),6 ),round (float (r ["lat"]),6 )]},
    "properties":{
    "name":r ["name"],"beds":int (r ["beds"]),
    "beds_estimated":bool (r ["beds_estimated"]),
    "beds_source":r .get ("beds_source",""),
    "hospital_type":r .get ("hospital_type",""),
    "ownership_source":r .get ("ownership_source",""),
    "operator":r .get ("operator",""),"operator_type":r .get ("operator_type",""),
    "osm_id":r .get ("osm_id",""),"geom_type":r .get ("geom_type","Point"),
    },
    }for r in rows ]
    with open (os .path .join (DATA_DIR ,"lebanon_hospitals.geojson"),"w",encoding ="utf-8")as fh :
        json .dump ({"type":"FeatureCollection","features":feats },fh ,ensure_ascii =False )

    real =sum (1 for r in rows if not r ["beds_estimated"])
    print (f"OK: {len (rows )} hospitals total")
    print (f"  name-matched (syndicate): {n_match }")
    print (f"  arabic-name matched: {n_arabic }")
    print (f"  public-hospital matched (moph/wikipedia): {n_public }")
    print (f"  hand-verified added/merged: {len (VERIFIED_BIG )}  (new points: {len (added )-n_manual })")
    print (f"  manual-coords added: {n_manual }")
    print (f"  REAL bed counts now: {real } / {len (rows )}  (was 3)")
    print (f"  median used for the remaining {len (rows )-real } estimates: {median_beds }")
    print (f"  type — public: {n_pub } | private (tagged): {n_priv_tag } | private (inferred): {n_priv_inf }")
    print (f"Wrote {OSM_CSV }")

if __name__ =="__main__":
    main ()
