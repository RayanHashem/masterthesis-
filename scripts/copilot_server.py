import os 
import re 
import json 
import math 
from typing import Optional ,List ,Dict ,Any 

import requests 
import numpy as np 
import pandas as pd 
import geopandas as gpd 
import rasterio 
from rasterio .transform import xy 
from shapely .geometry import Point 

from fastapi import FastAPI 
from fastapi .middleware .cors import CORSMiddleware 
from pydantic import BaseModel 

from lebanon_ems_rules import RULES ,CITATIONS ,is_urban ,rules_summary_markdown 

SCRIPT_DIR =os .path .dirname (os .path .abspath (__file__ ))
PROJECT_ROOT =os .path .dirname (SCRIPT_DIR )
DATA_DIR =os .path .join (PROJECT_ROOT ,"data")

DISTRICTS_FILE =os .path .join (DATA_DIR ,"gadm41_LBN_2.json")
EMS_STATIONS_FILE =os .path .join (DATA_DIR ,"EMS_Station_Locations.xlsx")
POPULATION_RASTER_FILE =os .path .join (DATA_DIR ,"lbn_pop_2025_CN_1km_R2025A_UA_v1.tif")
AHP_SIDECAR_FILE =os .path .join (DATA_DIR ,"phase1_ahp_districts.json")
HOSPITALS_FILE =os .path .join (DATA_DIR ,"lebanon_hospitals.csv")

OLLAMA_URL =os .environ .get ("OLLAMA_URL","http://127.0.0.1:11434")
OLLAMA_MODEL =os .environ .get ("OLLAMA_MODEL","qwen2.5:3b")

print ("[copilot] loading data...",flush =True )

districts_gdf =gpd .read_file (DISTRICTS_FILE )
ems_df =pd .read_excel (EMS_STATIONS_FILE ,engine ="openpyxl")

def _find_col (df ,options ):
    for c in df .columns :
        if c .strip ().lower ()in options :
            return c 
    return None 

LAT_COL =_find_col (ems_df ,{"y","lat","latitude"})
LON_COL =_find_col (ems_df ,{"x","lon","lng","longitude"})
if not LAT_COL or not LON_COL :
    raise RuntimeError ("EMS station file is missing latitude/longitude columns.")

ems_valid =ems_df .dropna (subset =[LAT_COL ,LON_COL ]).copy ()
ems_gdf =gpd .GeoDataFrame (
ems_valid ,
geometry =[Point (lon ,lat )for lon ,lat in zip (ems_valid [LON_COL ],ems_valid [LAT_COL ])],
crs ="EPSG:4326",
)

with rasterio .open (POPULATION_RASTER_FILE )as src :
    raster_data =src .read (1 )
    raster_transform =src .transform 
    raster_nodata =src .nodata 
    raster_width =src .width 
    raster_height =src .height 

pop_points =[]
step =max (1 ,min (5 ,raster_width //100 ,raster_height //100 ))
for y_ in range (0 ,raster_height ,step ):
    for x_ in range (0 ,raster_width ,step ):
        v =raster_data [y_ ,x_ ]
        if raster_nodata is not None and v ==raster_nodata :
            continue 
        if np .isnan (v )or v <=0 :
            continue 
        lon ,lat =xy (raster_transform ,y_ ,x_ )
        pop_points .append ({"geometry":Point (lon ,lat ),"population":float (v )})
pop_gdf =gpd .GeoDataFrame (pop_points ,crs ="EPSG:4326")

joined =gpd .sjoin (districts_gdf ,pop_gdf ,how ="left",predicate ="contains")
district_pop =joined .groupby (joined .index ).agg ({"population":"sum"}).fillna (0 )
districts_gdf ["population"]=district_pop ["population"]

ems_in_districts =gpd .sjoin (ems_gdf ,districts_gdf ,how ="left",predicate ="within")
counts =ems_in_districts .groupby (ems_in_districts .index_right ).size ()
districts_gdf ["ems_stations"]=districts_gdf .index .map (counts ).fillna (0 ).astype (int )

districts_agg =(
districts_gdf .dissolve (
by ="NAME_2",
aggfunc ={"population":"sum","ems_stations":"sum","NAME_1":"first"},
)
.reset_index ()
)

ahp_lookup :Dict [str ,Dict [str ,Any ]]={}
if os .path .exists (AHP_SIDECAR_FILE ):
    try :
        with open (AHP_SIDECAR_FILE ,"r",encoding ="utf-8")as f :
            for d in json .load (f ):
                ahp_lookup [d ["district_name"]]=d 
        print (f"[copilot] AHP sidecar loaded: {len (ahp_lookup )} districts",flush =True )
    except Exception as e :
        print (f"[copilot] could not load AHP sidecar: {e }",flush =True )
else :
    print ("[copilot] AHP sidecar not found — run scripts/phase1_ahp_explore.py to enable AHP answers.",flush =True )

def _enrich (row ):
    name =row .get ("NAME_2")
    extra =ahp_lookup .get (name ,{})
    return {
    "ahp_score":extra .get ("ahp_score"),
    "ahp_priority":extra .get ("ahp_priority"),
    "min_travel_time_min":extra .get ("min_travel_time_min"),
    "exposed_population":extra .get ("exposed_population"),
    "pop_density":extra .get ("pop_density"),
    }

_extra =districts_agg .apply (_enrich ,axis =1 ,result_type ="expand")
districts_agg =pd .concat ([districts_agg ,_extra ],axis =1 )

def _alert (row ):
    if row .get ("ahp_priority"):
        return row ["ahp_priority"]
    pop =float (row .get ("population")or 0 )
    st =int (row .get ("ems_stations")or 0 )
    if st ==0 :
        return "Critical"
    if pop >=60000 and st <=1 :
        return "Critical"
    if pop >=40000 and st <=2 :
        return "At Risk"
    return "Adequate"

districts_agg ["alert_status"]=districts_agg .apply (_alert ,axis =1 )

print (f"[copilot] loaded {len (districts_agg )} districts, {len (ems_valid )} stations",flush =True )

hospitals_df =pd .read_csv (HOSPITALS_FILE )
hospitals_gdf =gpd .GeoDataFrame (
hospitals_df ,
geometry =gpd .points_from_xy (hospitals_df ["lon"],hospitals_df ["lat"]),
crs ="EPSG:4326",
)

_hosp_joined =gpd .sjoin (hospitals_gdf ,districts_gdf [["NAME_1","NAME_2","geometry"]],how ="left",predicate ="within")
hospitals_gdf ["district"]=_hosp_joined ["NAME_2"]
hospitals_gdf ["governorate"]=_hosp_joined ["NAME_1"]

_hosp_agg =(
hospitals_gdf .groupby ("district")
.agg (
hospital_count =("name","count"),
total_beds =("beds","sum"),
public_count =("hospital_type",lambda x :(x =="public").sum ()),
private_count =("hospital_type",lambda x :(x =="private").sum ()),
)
.reset_index ()
)
districts_agg =districts_agg .merge (_hosp_agg ,left_on ="NAME_2",right_on ="district",how ="left")
districts_agg ["hospital_count"]=districts_agg ["hospital_count"].fillna (0 ).astype (int )
districts_agg ["total_beds"]=districts_agg ["total_beds"].fillna (0 ).astype (int )
districts_agg ["public_count"]=districts_agg ["public_count"].fillna (0 ).astype (int )
districts_agg ["private_count"]=districts_agg ["private_count"].fillna (0 ).astype (int )

print (f"[copilot] loaded {len (hospitals_gdf )} hospitals",flush =True )

def _norm (s :str )->str :
    return re .sub (r"[^a-z]","",(s or "").lower ())

_district_index ={_norm (r ["NAME_2"]):r for _ ,r in districts_agg .iterrows ()}
_governorate_index :Dict [str ,List [Dict [str ,Any ]]]={}
for _ ,r in districts_agg .iterrows ():
    _governorate_index .setdefault (_norm (r ["NAME_1"]),[]).append (r .to_dict ())

def find_district (name :str )->Optional [Dict [str ,Any ]]:
    key =_norm (name )
    if key in _district_index :
        return _district_index [key ].to_dict ()
    for k ,v in _district_index .items ():
        if key and (key in k or k in key ):
            return v .to_dict ()
    return None 

def find_governorate (name :str )->Optional [List [Dict [str ,Any ]]]:
    key =_norm (name )
    if key in _governorate_index :
        return _governorate_index [key ]
    for k ,v in _governorate_index .items ():
        if key and (key in k or k in key ):
            return v 
    return None 

def haversine_km (lat1 ,lon1 ,lat2 ,lon2 ):
    R =6371.0 
    p1 ,p2 =math .radians (lat1 ),math .radians (lat2 )
    dp =math .radians (lat2 -lat1 )
    dl =math .radians (lon2 -lon1 )
    a =math .sin (dp /2 )**2 +math .cos (p1 )*math .cos (p2 )*math .sin (dl /2 )**2 
    return 2 *R *math .asin (math .sqrt (a ))

def _safe (v ,default =None ):
    if v is None :
        return default 
    try :
        if isinstance (v ,float )and (math .isnan (v )or math .isinf (v )):
            return default 
    except Exception :
        pass 
    return v 

def geocode_place (query :str )->Optional [Dict [str ,Any ]]:
    coord_match =re .search (r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)",query )
    if coord_match :
        lat =float (coord_match .group (1 ))
        lon =float (coord_match .group (2 ))
        if 33.0 <=lat <=34.8 and 35.0 <=lon <=36.8 :
            return {
            "display_name":f"{lat :.5f}, {lon :.5f}",
            "lat":lat ,
            "lon":lon ,
            "bbox":None ,
            }
    try :
        r =requests .get (
        "https://nominatim.openstreetmap.org/search",
        params ={
        "q":query +", Lebanon"if "lebanon"not in query .lower ()else query ,
        "format":"json",
        "limit":1 ,
        "polygon_geojson":1 ,
        "countrycodes":"lb",
        },
        headers ={"User-Agent":"lebanon-ems-ahp-copilot/1.0"},
        timeout =8 ,
        )
        r .raise_for_status ()
        hits =r .json ()
        if not hits :
            return None 
        h =hits [0 ]
        return {
        "display_name":h .get ("display_name"),
        "lat":float (h ["lat"]),
        "lon":float (h ["lon"]),
        "bbox":[float (b )for b in h .get ("boundingbox",[])]if h .get ("boundingbox")else None ,
        }
    except Exception as e :
        print (f"[copilot] geocode error: {e }",flush =True )
        return None 

def _underserved_alternatives (n :int =5 )->List [Dict [str ,Any ]]:
    df =districts_agg .copy ()
    if df ["ahp_score"].notna ().any ():
        ranked =df .sort_values (["ahp_score"],ascending =False ).head (n )
    else :
        ranked =(
        df [df ["alert_status"].isin (["High","Critical","Medium","At Risk"])]
        .sort_values ("population",ascending =False )
        .head (n )
        )
    out =[]
    for _ ,r in ranked .iterrows ():
        out .append ({
        "district":r ["NAME_2"],
        "governorate":r ["NAME_1"],
        "population":int (r ["population"]or 0 ),
        "stations":int (r ["ems_stations"]or 0 ),
        "ahp_priority":_safe (r .get ("ahp_priority"))or r ["alert_status"],
        "ahp_score":_safe (round (float (r ["ahp_score"]),3 ))if pd .notna (r .get ("ahp_score"))else None ,
        })
    return out 

def assess_placement (place_query :str )->Dict [str ,Any ]:
    geo =geocode_place (place_query )
    if not geo :
        return {"error":f"Could not locate '{place_query }' in Lebanon."}

    lat ,lon =geo ["lat"],geo ["lon"]
    pt =Point (lon ,lat )
    containing =districts_agg [districts_agg .geometry .contains (pt )]if "geometry"in districts_agg .columns else pd .DataFrame ()
    district_row =containing .iloc [0 ].to_dict ()if len (containing )>0 else None 
    governorate =district_row ["NAME_1"]if district_row else "Unknown"
    urban =is_urban (governorate )

    drive_radius =RULES ["drive_radius_urban_km"if urban else "drive_radius_rural_km"]["value"]
    min_spacing =RULES ["min_spacing_urban_km"if urban else "min_spacing_rural_km"]["value"]

    nearby =[]
    for _ ,s in ems_valid .iterrows ():
        d =haversine_km (lat ,lon ,float (s [LAT_COL ]),float (s [LON_COL ]))
        if d <=min_spacing :
            nearby .append ({
            "location":s .get ("location","EMS Station")if "location"in s else "EMS Station",
            "station_id":int (s .get ("station"))if "station"in s and pd .notna (s .get ("station"))else None ,
            "distance_km":round (d ,2 ),
            })
    nearby .sort (key =lambda x :x ["distance_km"])

    overcrowd_threshold =RULES ["overcrowded_stations_in_radius"]["value"]
    is_overcrowded =len (nearby )>=overcrowd_threshold 

    return {
    "query":place_query ,
    "resolved":geo ["display_name"],
    "coordinates":{"lat":lat ,"lon":lon },
    "district":district_row ["NAME_2"]if district_row else None ,
    "governorate":governorate ,
    "area_type":"urban"if urban else "rural",
    "applied_radius_km":drive_radius ,
    "applied_min_spacing_km":min_spacing ,
    "existing_stations_in_radius":nearby ,
    "is_overcrowded":is_overcrowded ,
    "verdict":(
    "overcrowded — placement here would duplicate existing coverage"
    if is_overcrowded 
    else ("acceptable — within spacing rules"if len (nearby )==0 else "marginal — one station nearby")
    ),
    "alternatives":_underserved_alternatives (5 ),
    "regulations_applied":{
    "response_time_target":f"{RULES ['response_time_target_min']['value']} min ({CITATIONS ['LRC-9']})",
    "min_spacing_km":min_spacing ,
    "min_spacing_source":"Demo heuristic — Lebanon does not publicly codify spatial spacing.",
    },
    }

def tool_district_info (name :str )->Dict [str ,Any ]:
    d =find_district (name )
    if not d :
        return {"error":f"District '{name }' not found."}
    pop =float (d .get ("population")or 0 )
    st =int (d .get ("ems_stations")or 0 )
    return {
    "district":d ["NAME_2"],
    "governorate":d ["NAME_1"],
    "population":int (pop ),
    "stations":st ,
    "pop_per_station":int (pop /st )if st >0 else None ,
    "ahp_priority":_safe (d .get ("ahp_priority")),
    "ahp_score":_safe (round (float (d ["ahp_score"]),3 ))if pd .notna (d .get ("ahp_score"))else None ,
    "min_travel_time_min":_safe (d .get ("min_travel_time_min")),
    "status":d .get ("alert_status"),
    }

def tool_compare (a :str ,b :str )->Dict [str ,Any ]:
    da =tool_district_info (a )
    db =tool_district_info (b )
    if "error"in da :
        return da 
    if "error"in db :
        return db 
    return {"a":da ,"b":db }

def tool_top_priority (n :int =5 )->Dict [str ,Any ]:
    df =districts_agg .copy ()
    if df ["ahp_score"].notna ().any ():
        ranked =df .sort_values ("ahp_score",ascending =False ).head (n )
        sort_key ="ahp_score"
    else :
        ranked =df .sort_values ("population",ascending =False ).head (n )
        sort_key ="population"
    rows =[]
    for _ ,r in ranked .iterrows ():
        rows .append ({
        "district":r ["NAME_2"],
        "governorate":r ["NAME_1"],
        "population":int (r ["population"]or 0 ),
        "stations":int (r ["ems_stations"]or 0 ),
        "ahp_score":_safe (round (float (r ["ahp_score"]),3 ))if pd .notna (r .get ("ahp_score"))else None ,
        "ahp_priority":_safe (r .get ("ahp_priority"))or r ["alert_status"],
        })
    return {"ranked_by":sort_key ,"count":len (rows ),"districts":rows }

def tool_governorate_summary (name :str )->Dict [str ,Any ]:
    rows =find_governorate (name )
    if not rows :
        return {"error":f"Governorate '{name }' not found."}
    pop =sum (float (r .get ("population")or 0 )for r in rows )
    st =sum (int (r .get ("ems_stations")or 0 )for r in rows )
    return {
    "governorate":rows [0 ]["NAME_1"],
    "districts":len (rows ),
    "population":int (pop ),
    "stations":st ,
    "pop_per_station":int (pop /st )if st >0 else None ,
    "district_breakdown":[
    {
    "district":r ["NAME_2"],
    "population":int (r .get ("population")or 0 ),
    "stations":int (r .get ("ems_stations")or 0 ),
    "ahp_priority":_safe (r .get ("ahp_priority"))or r .get ("alert_status"),
    }
    for r in rows 
    ],
    }

def tool_national_summary ()->Dict [str ,Any ]:
    pop =float (districts_agg ["population"].sum ())
    st =int (districts_agg ["ems_stations"].sum ())
    counts =districts_agg ["alert_status"].value_counts ().to_dict ()
    return {
    "total_districts":int (len (districts_agg )),
    "total_population":int (pop ),
    "total_stations":st ,
    "pop_per_station":int (pop /st )if st >0 else None ,
    "priority_breakdown":{k :int (v )for k ,v in counts .items ()},
    "ahp_loaded":bool (ahp_lookup ),
    }

def tool_hospital_district (name :str )->Dict [str ,Any ]:
    d =find_district (name )
    if not d :
        return {"error":f"District '{name }' not found."}
    district_name =d ["NAME_2"]
    hosp =hospitals_gdf [hospitals_gdf ["district"]==district_name ].copy ()
    if hosp .empty :
        return {
        "district":district_name ,
        "governorate":d ["NAME_1"],
        "hospital_count":0 ,
        "hospitals":[],
        "note":"No hospitals mapped in this district.",
        }
    rows =[]
    for _ ,h in hosp .iterrows ():
        rows .append ({
        "name":h ["name"],
        "type":h .get ("hospital_type","unknown"),
        "beds":int (h ["beds"])if pd .notna (h ["beds"])else None ,
        "beds_estimated":bool (h .get ("beds_estimated",False )),
        })
    rows .sort (key =lambda x :-(x ["beds"]or 0 ))
    return {
    "district":district_name ,
    "governorate":d ["NAME_1"],
    "hospital_count":len (rows ),
    "total_beds":int (hosp ["beds"].sum ()),
    "public":int ((hosp ["hospital_type"]=="public").sum ()),
    "private":int ((hosp ["hospital_type"]=="private").sum ()),
    "hospitals":rows ,
    }

def tool_hospital_governorate (name :str )->Dict [str ,Any ]:
    rows =find_governorate (name )
    if not rows :
        return {"error":f"Governorate '{name }' not found."}
    gov_name =rows [0 ]["NAME_1"]
    hosp =hospitals_gdf [hospitals_gdf ["governorate"]==gov_name ].copy ()
    district_breakdown =[]
    for r in rows :
        dn =r ["NAME_2"]
        dh =hosp [hosp ["district"]==dn ]
        district_breakdown .append ({
        "district":dn ,
        "hospital_count":len (dh ),
        "total_beds":int (dh ["beds"].sum ()),
        "public":int ((dh ["hospital_type"]=="public").sum ()),
        "private":int ((dh ["hospital_type"]=="private").sum ()),
        })
    return {
    "governorate":gov_name ,
    "hospital_count":len (hosp ),
    "total_beds":int (hosp ["beds"].sum ()),
    "public":int ((hosp ["hospital_type"]=="public").sum ()),
    "private":int ((hosp ["hospital_type"]=="private").sum ()),
    "district_breakdown":district_breakdown ,
    }

def tool_hospital_national ()->Dict [str ,Any ]:
    total =len (hospitals_gdf )
    beds =int (hospitals_gdf ["beds"].sum ())
    public =int ((hospitals_gdf ["hospital_type"]=="public").sum ())
    private =int ((hospitals_gdf ["hospital_type"]=="private").sum ())
    pop =float (districts_agg ["population"].sum ())
    return {
    "total_hospitals":total ,
    "total_beds":beds ,
    "public":public ,
    "private":private ,
    "beds_per_1000":round (beds /pop *1000 ,2 )if pop >0 else None ,
    "note":"Majority of bed counts are estimated (median-imputed); treat as directional.",
    }

def tool_nearest_hospital (place_query :str )->Dict [str ,Any ]:
    geo =geocode_place (place_query )
    if not geo :
        return {"error":f"Could not locate '{place_query }' in Lebanon."}
    lat ,lon =geo ["lat"],geo ["lon"]
    dists =hospitals_gdf .apply (
    lambda h :haversine_km (lat ,lon ,float (h ["lat"]),float (h ["lon"])),axis =1 
    )
    hospitals_gdf ["_dist_km"]=dists 
    nearest =hospitals_gdf .nsmallest (5 ,"_dist_km")
    results =[]
    for _ ,h in nearest .iterrows ():
        results .append ({
        "name":h ["name"],
        "type":h .get ("hospital_type","unknown"),
        "beds":int (h ["beds"])if pd .notna (h ["beds"])else None ,
        "beds_estimated":bool (h .get ("beds_estimated",False )),
        "district":h .get ("district"),
        "governorate":h .get ("governorate"),
        "distance_km":round (float (h ["_dist_km"]),2 ),
        })
    hospitals_gdf .drop (columns =["_dist_km"],inplace =True )
    return {
    "query":place_query ,
    "resolved":geo ["display_name"],
    "nearest_hospitals":results ,
    }

def tool_coverage_gaps (top_n :int =5 )->Dict [str ,Any ]:
    df =districts_agg .copy ()

    zero =df [df ["ems_stations"]==0 ][["NAME_2","NAME_1","population","ems_stations"]].copy ()

    has_ahp =df ["exposed_population"].notna ().any ()
    if has_ahp :
        ranked =df [df ["ems_stations"]>0 ].sort_values (
        ["exposed_population","min_travel_time_min"],ascending =[False ,False ]
        ).head (top_n )
    else :
        ranked =df [df ["ems_stations"]>0 ].sort_values ("population",ascending =False ).head (top_n )

    zero_rows =[
    {
    "district":r ["NAME_2"],"governorate":r ["NAME_1"],
    "population":int (r ["population"]or 0 ),"stations":0 ,
    "exposed_population":int (r .get ("exposed_population")or r ["population"]or 0 ),
    "min_travel_time_min":_safe (r .get ("min_travel_time_min")),
    "ahp_priority":_safe (r .get ("ahp_priority"))or "Critical",
    }
    for _ ,r in zero .iterrows ()
    ]
    gap_rows =[
    {
    "district":r ["NAME_2"],"governorate":r ["NAME_1"],
    "population":int (r ["population"]or 0 ),
    "stations":int (r ["ems_stations"]or 0 ),
    "exposed_population":int (r .get ("exposed_population")or 0 ),
    "min_travel_time_min":_safe (r .get ("min_travel_time_min")),
    "ahp_priority":_safe (r .get ("ahp_priority"))or r .get ("alert_status"),
    }
    for _ ,r in ranked .iterrows ()
    ]
    return {
    "zero_station_districts":zero_rows ,
    "highest_gap_districts":gap_rows ,
    "note":"Exposed population = residents estimated beyond EMS coverage radius.",
    }

def tool_affordability (name :str =None )->Dict [str ,Any ]:
    if name :

        rows =find_governorate (name )
        if rows :
            gov =rows [0 ]["NAME_1"]
            no_pub =[r ["NAME_2"]for r in rows if (r .get ("public_count")or 0 )==0 ]
            pub_total =sum (int (r .get ("public_count")or 0 )for r in rows )
            priv_total =sum (int (r .get ("private_count")or 0 )for r in rows )
            total =pub_total +priv_total 
            return {
            "scope":"governorate",
            "name":gov ,
            "total_hospitals":total ,
            "public":pub_total ,
            "private":priv_total ,
            "public_pct":round (pub_total /total *100 ,1 )if total >0 else 0 ,
            "districts_without_public_hospital":no_pub ,
            }
        d =find_district (name )
        if d :
            pub =int (d .get ("public_count")or 0 )
            priv =int (d .get ("private_count")or 0 )
            total =pub +priv 
            pop =float (d .get ("population")or 0 )
            return {
            "scope":"district",
            "name":d ["NAME_2"],
            "governorate":d ["NAME_1"],
            "total_hospitals":total ,
            "public":pub ,
            "private":priv ,
            "public_pct":round (pub /total *100 ,1 )if total >0 else 0 ,
            "has_public_hospital":pub >0 ,
            "population":int (pop ),
            "verdict":(
            "No public hospital — residents rely entirely on private (fee-based) care."
            if pub ==0 else 
            f"{pub } public hospital(s) serving {int (pop ):,} residents."
            ),
            }
        return {"error":f"Location '{name }' not found."}

    no_pub =districts_agg [districts_agg ["public_count"]==0 ]["NAME_2"].tolist ()
    pub_total =int (districts_agg ["public_count"].sum ())
    priv_total =int (districts_agg ["private_count"].sum ())
    total =pub_total +priv_total 
    pop_no_pub =int (districts_agg [districts_agg ["public_count"]==0 ]["population"].sum ())
    return {
    "scope":"national",
    "total_hospitals":total ,
    "public":pub_total ,
    "private":priv_total ,
    "public_pct":round (pub_total /total *100 ,1 )if total >0 else 0 ,
    "districts_without_public_hospital":no_pub ,
    "population_without_public_hospital":pop_no_pub ,
    "note":"88% of Lebanon's hospitals are private — access is largely fee-based.",
    }

def tool_exposed_population (name :str =None )->Dict [str ,Any ]:
    if name :
        d =find_district (name )
        if d :
            exp =_safe (d .get ("exposed_population"))
            pop =float (d .get ("population")or 0 )
            return {
            "district":d ["NAME_2"],
            "governorate":d ["NAME_1"],
            "population":int (pop ),
            "exposed_population":int (exp )if exp is not None else None ,
            "exposed_pct":round (exp /pop *100 ,1 )if exp and pop >0 else None ,
            "min_travel_time_min":_safe (d .get ("min_travel_time_min")),
            "ahp_priority":_safe (d .get ("ahp_priority")),
            }
        rows =find_governorate (name )
        if rows :
            gov =rows [0 ]["NAME_1"]
            total_pop =sum (float (r .get ("population")or 0 )for r in rows )
            total_exp =sum (float (r .get ("exposed_population")or 0 )for r in rows )
            breakdown =[
            {
            "district":r ["NAME_2"],
            "exposed_population":int (r .get ("exposed_population")or 0 ),
            "exposed_pct":round (float (r .get ("exposed_population")or 0 )/float (r .get ("population")or 1 )*100 ,1 ),
            }
            for r in rows 
            ]
            return {
            "governorate":gov ,
            "population":int (total_pop ),
            "exposed_population":int (total_exp ),
            "exposed_pct":round (total_exp /total_pop *100 ,1 )if total_pop >0 else None ,
            "district_breakdown":breakdown ,
            }
        return {"error":f"Location '{name }' not found."}

    total_pop =float (districts_agg ["population"].sum ())
    total_exp =float (districts_agg ["exposed_population"].sum ())if "exposed_population"in districts_agg else 0 
    worst =districts_agg .sort_values ("exposed_population",ascending =False ).head (5 )
    return {
    "scope":"national",
    "population":int (total_pop ),
    "exposed_population":int (total_exp ),
    "exposed_pct":round (total_exp /total_pop *100 ,1 )if total_pop >0 else None ,
    "worst_districts":[
    {"district":r ["NAME_2"],"governorate":r ["NAME_1"],
    "exposed_population":int (r .get ("exposed_population")or 0 )}
    for _ ,r in worst .iterrows ()
    ],
    }

COVERAGE_GAP_RE =re .compile (r"\b(?:coverage\s+gap|gaps?\s+in\s+coverage|underserved|under-served|no\s+(?:ems\s+)?station|zero\s+station|missing\s+coverage|which\s+districts?\s+(?:have|lack|need|are)(?!\s+(?:no\s+)?public)|(?:have|is\s+there|any|what('s|s|\s+is))\s+(?:a\s+)?(?:coverage\s+)?gap|gap\s+in)\b",re .I )
AFFORDABILITY_RE =re .compile (r"(?:\baffordab|\bpublic\s+hospital|\bprivate\s+hospital|\bno\s+public\s+hospital|\bwithout\s+(?:a\s+)?public|\bfee.based|\bcost\s+of\s+care|\bhospital\s+access)",re .I )
EXPOSED_POP_RE =re .compile (r"\b(?:exposed\s+population|population\s+(?:without|lacking|outside)\s+coverage|unserved\s+population|population\s+at\s+risk)\b",re .I )
HOSPITAL_DISTRICT_RE =re .compile (r"\b(?:hospitals?|clinics?|medical\s+centers?|beds?)\b.{0,60}\b(?:in|at|for|of)\s+([\w\s'\-]+?)(?:[?.]|$)",re .I )
HOSPITAL_COUNT_RE =re .compile (r"\bhow\s+many\s+hospitals?\b.{0,60}\b(?:in|at|for)\s+([\w\s'\-]+?)(?:[?.]|$)",re .I )
HOSPITAL_BEDS_RE =re .compile (r"\b(?:beds?|bed\s+count|bed\s+capacity)\b.{0,60}\b(?:in|at|for)\s+([\w\s'\-]+?)(?:[?.]|$)",re .I )
NEAREST_HOSPITAL_RE =re .compile (r"\b(?:nearest|closest|near(?:by)?)\s+hospital\b.{0,80}",re .I )
HOSPITAL_NATIONAL_RE =re .compile (r"\b(?:hospitals?\s+(?:in\s+)?lebanon|national\s+hospital|total\s+hospitals?|all\s+hospitals?|hospital\s+(?:overview|summary|stats))\b",re .I )

PLACE_PATTERNS =[
r"\b(?:open|place|put|set\s*up|build|locate|establish|start)\b.{0,80}\b(?:ems|station|center|centre|ambulance)\b",
r"\b(?:ems|station|center|centre|ambulance)\b.{0,40}\b(?:in|at|near)\s+([a-z\u00C0-\u017F\s\-']+)",
r"\bwhere\s+(?:can|should|could)\s+i\s+(?:open|place|put|build)\b",
]
COMPARE_RE =re .compile (r"\bcompare\b\s+([\w\s'\-]+?)\s+(?:and|vs\.?|versus|with|to)\s+([\w\s'\-]+?)(?:[?.]|$)",re .I )
PRIORITY_RE =re .compile (r"\b(high(?:est)?\s+priority|most\s+in\s+need|under\s*served|worst|biggest\s+gap|top\s+\d+)\b",re .I )
HOWMANY_RE =re .compile (r"\bhow\s+many\s+(?:ems\s+)?(?:stations|ambulances|centers|centres)\s+(?:are\s+)?(?:in|at|for)\s+([\w\s'\-]+?)(?:[?.]|$)",re .I )
POP_RE =re .compile (r"\b(?:population|residents|people)\s+(?:of|in)\s+([\w\s'\-]+?)(?:[?.]|$)",re .I )
SUMMARIZE_GOV_RE =re .compile (r"\b(?:summari[sz]e|summary|overview|brief\s+on|tell\s+me\s+about)\s+(?:the\s+)?([\w\s'\-]+?)(?:\s+(?:governorate|gov))?(?:[?.]|$)",re .I )
NATIONAL_RE =re .compile (r"\b(?:national|nationwide|country(?:wide)?|lebanon|overall|total)\b",re .I )
RULES_RE =re .compile (r"\b(?:rules?|regulations?|law|legal|standards?|requirements?|threshold|methodology|how\s+does\s+(?:this|the\s+ahp)\s+work)\b",re .I )
AHP_EXPLAIN_RE =re .compile (r"\b(?:what\s+is\s+(?:the\s+)?ahp|how\s+does\s+ahp\s+work|explain\s+(?:the\s+)?ahp|ahp\s+(?:score|model|methodology))\b",re .I )

def route_intent (message :str ,mode :str ="ems")->Optional [Dict [str ,Any ]]:
    msg =message .strip ()

    if re .search (r"\b(?:assess|evaluate|check|open|place|put|build|locate|establish|station|center|centre)\b",msg ,re .I ):
        coord_match =re .search (r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)",msg )
        if coord_match :
            return {"intent":"placement","result":assess_placement (coord_match .group (0 ))}

    if any (re .search (p ,msg ,re .I )for p in PLACE_PATTERNS ):
        m =re .search (r"\b(?:in|at|near)\s+([A-Z0-9][\w\s'\-.,]+?)(?:[?]|$)",msg )
        if m :
            return {"intent":"placement","result":assess_placement (m .group (1 ).strip ())}
        return {"intent":"placement","result":{"error":"Please specify a neighborhood, e.g. 'in Ras al Nabeh, Beirut'."}}

    m =COMPARE_RE .search (msg )
    if m :
        return {"intent":"compare","result":tool_compare (m .group (1 ).strip (),m .group (2 ).strip ())}

    m =HOWMANY_RE .search (msg )
    if m :
        name =m .group (1 ).strip ()
        if find_district (name ):
            return {"intent":"district_info","result":tool_district_info (name )}
        if find_governorate (name ):
            return {"intent":"governorate_summary","result":tool_governorate_summary (name )}

    if EXPOSED_POP_RE .search (msg ):
        loc_m =re .search (r"\b(?:in|of|for)\s+([\w\s'\-]+?)(?:[?.]|$)",msg ,re .I )
        if loc_m :
            name =re .sub (r"\s+(?:district|governorate|gov|province|region|area)$","",loc_m .group (1 ).strip (),flags =re .I )
            return {"intent":"exposed_population","result":tool_exposed_population (name )}
        return {"intent":"exposed_population","result":tool_exposed_population ()}

    if AFFORDABILITY_RE .search (msg ):
        loc_m =re .search (r"\b(?:in|of|for)\s+([\w\s'\-]+?)(?:[?.]|$)",msg ,re .I )
        if loc_m :
            name =re .sub (r"\s+(?:district|governorate|gov|province|region|area)$","",loc_m .group (1 ).strip (),flags =re .I )
            return {"intent":"affordability","result":tool_affordability (name )}
        return {"intent":"affordability","result":tool_affordability ()}

    m =POP_RE .search (msg )
    if m :
        name =m .group (1 ).strip ()
        if find_district (name ):
            return {"intent":"district_info","result":tool_district_info (name )}
        if find_governorate (name ):
            return {"intent":"governorate_summary","result":tool_governorate_summary (name )}

    if PRIORITY_RE .search (msg ):
        nmatch =re .search (r"top\s+(\d+)",msg ,re .I )
        n =int (nmatch .group (1 ))if nmatch else 5 
        return {"intent":"top_priority","result":tool_top_priority (n )}

    m =SUMMARIZE_GOV_RE .search (msg )
    if m :
        name =m .group (1 ).strip ()
        if find_governorate (name ):
            return {"intent":"governorate_summary","result":tool_governorate_summary (name )}
        if find_district (name ):
            return {"intent":"district_info","result":tool_district_info (name )}

    if NATIONAL_RE .search (msg )and any (w in msg .lower ()for w in ("overview","summary","total","stats","statistics"))and "hospital"not in msg .lower ():
        return {"intent":"national","result":tool_national_summary ()}

    if AHP_EXPLAIN_RE .search (msg )or RULES_RE .search (msg ):
        return {"intent":"rules","result":{"markdown":rules_summary_markdown ()}}

    if HOSPITAL_NATIONAL_RE .search (msg ):
        return {"intent":"hospital_national","result":tool_hospital_national ()}

    if NEAREST_HOSPITAL_RE .search (msg ):
        loc_m =re .search (r"\b(?:to|from|near|in|at)\s+([A-Z][\w\s'\-,]+?)(?:[?.]|$)",msg )
        if loc_m :
            loc_name =re .sub (r"\s+(?:district|governorate|gov|province|region|area)$","",loc_m .group (1 ).strip (),flags =re .I )
            return {"intent":"nearest_hospital","result":tool_nearest_hospital (loc_name )}
        coord_m =re .search (r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)",msg )
        if coord_m :
            return {"intent":"nearest_hospital","result":tool_nearest_hospital (coord_m .group (0 ))}
        return {"intent":"nearest_hospital","result":{"error":"Please specify a location, e.g. 'nearest hospital to Tripoli'."}}

    for pattern in (HOSPITAL_COUNT_RE ,HOSPITAL_BEDS_RE ,HOSPITAL_DISTRICT_RE ):
        m =pattern .search (msg )
        if m :
            name =re .sub (r"\s+(?:district|governorate|gov|province|region|area)$","",m .group (1 ).strip (),flags =re .I )
            if find_governorate (name ):
                return {"intent":"hospital_governorate","result":tool_hospital_governorate (name )}
            if find_district (name ):
                return {"intent":"hospital_district","result":tool_hospital_district (name )}

    if COVERAGE_GAP_RE .search (msg ):
        nmatch =re .search (r"top\s+(\d+)",msg ,re .I )
        n =int (nmatch .group (1 ))if nmatch else 5 
        loc_m =re .search (r"\b(?:in|for)\s+([\w\s'\-]+?)(?:[?.]|$)",msg ,re .I )
        if loc_m :
            candidate =re .sub (r"\s+(?:district|governorate|gov|province|region|area)$","",loc_m .group (1 ).strip (),flags =re .I )
            if find_district (candidate ):

                if mode =="hospitals":
                    return {"intent":"hospital_district","result":tool_hospital_district (candidate )}
                return {"intent":"exposed_population","result":tool_exposed_population (candidate )}
            rows =find_governorate (candidate )
            if rows :
                gov_filter =rows [0 ]["NAME_1"]
                if mode =="hospitals":
                    return {"intent":"hospital_governorate","result":tool_hospital_governorate (candidate )}
                result =tool_coverage_gaps (n )
                all_gaps =tool_coverage_gaps (top_n =26 )
                result ["zero_station_districts"]=[d for d in result ["zero_station_districts"]if d ["governorate"]==gov_filter ]
                result ["highest_gap_districts"]=[d for d in all_gaps ["highest_gap_districts"]if d ["governorate"]==gov_filter ]
                result ["filter"]=gov_filter 
                if not result ["zero_station_districts"]and not result ["highest_gap_districts"]:
                    result ["note"]=f"No significant coverage gaps detected in {gov_filter } based on current data."
                return {"intent":"coverage_gaps","result":result }
        return {"intent":"coverage_gaps","result":tool_coverage_gaps (n )}

    return None 

SYSTEM_PROMPT ="""You are EMS Copilot, an analyst for the Lebanon EMS AHP project.
You help researchers, doctors, and public health staff interpret an
Analytic Hierarchy Process (AHP) coverage model for Lebanon.
You also have access to Lebanon's hospital dataset (179 hospitals, public/private split, bed counts).

Hard rules:
1. NEVER invent numbers. All quantitative claims must come from the TOOL_RESULT block.
2. If TOOL_RESULT is provided, treat it as the single source of truth and explain
   it in clear, friendly English (2-6 short sentences). Use bullet points for lists.
3. The model ranks districts by an AHP score (0-1, higher = higher priority for a
   new station). Default weights: 50% travel-time gap, 30% population density,
   20% exposed population. Priority tiers: High / Medium / Low.
4. When TOOL_RESULT contains an "is_overcrowded" verdict, state it plainly and
   offer the listed alternative districts.
5. When citing rules, include the source tag in parentheses (e.g. "[LRC-9]").
6. If no TOOL_RESULT is provided, you may answer general EMS / AHP concept
   questions, but you must NOT cite specific Lebanese statistics from memory.
7. For hospital bed counts marked beds_estimated=true, note they are median-estimated.
8. Nearest hospital distances are straight-line (haversine), not road distances.
9. Exposed population = residents estimated to be outside EMS coverage radius.
10. Affordability = access to public (free/subsidized) vs. private (fee-based) hospitals.
11. Keep answers under 200 words. No emojis. No markdown headers, only bold and lists.
"""

def call_ollama (user_message :str ,tool_result :Optional [Dict [str ,Any ]],extra_system :Optional [str ]=None )->str :
    payload_messages =[{"role":"system","content":SYSTEM_PROMPT }]
    if extra_system :
        payload_messages .append ({"role":"system","content":extra_system })
    if tool_result is not None :
        payload_messages .append ({
        "role":"system",
        "content":"TOOL_RESULT (authoritative data, do not contradict):\n"+json .dumps (tool_result ,indent =2 ,default =str ,ensure_ascii =False ),
        })
    payload_messages .append ({"role":"user","content":user_message })

    try :
        r =requests .post (
        f"{OLLAMA_URL }/api/chat",
        json ={
        "model":OLLAMA_MODEL ,
        "messages":payload_messages ,
        "stream":False ,
        "options":{"temperature":0.3 ,"num_ctx":4096 },
        },
        timeout =120 ,
        )
        r .raise_for_status ()
        return r .json ()["message"]["content"].strip ()
    except requests .exceptions .ConnectionError :
        return ("(offline) Ollama is not running. Start it with `ollama serve` and "
        f"make sure you've pulled the model: `ollama pull {OLLAMA_MODEL }`.")
    except Exception as e :
        return f"(LLM error) {e }"

def format_tool_result (intent :str ,result :Dict [str ,Any ])->str :
    if "error"in result :
        return result ["error"]

    if intent =="district_info":
        r =result 
        bits =[f"**{r ['district']}** ({r ['governorate']})",
        f"population {r ['population']:,}",
        f"{r ['stations']} EMS station(s)"]
        if r .get ("ahp_priority"):
            bits .append (f"AHP priority **{r ['ahp_priority']}**")
        if r .get ("ahp_score")is not None :
            bits .append (f"score {r ['ahp_score']:.3f}")
        if r .get ("min_travel_time_min")is not None :
            bits .append (f"~{r ['min_travel_time_min']:.1f} min to nearest station")
        return " — ".join (bits )+"."

    if intent =="compare":
        a ,b =result ["a"],result ["b"]
        def line (d ):
            tag =d .get ("ahp_priority")or d .get ("status")or ""
            return (f"**{d ['district']}**: pop {d ['population']:,}, "
            f"{d ['stations']} st, priority {tag }"
            +(f", score {d ['ahp_score']:.3f}"if d .get ('ahp_score')is not None else ""))
        return line (a )+"\n"+line (b )

    if intent =="top_priority":
        lines =[f"Top {result ['count']} districts (ranked by {result ['ranked_by']}):"]
        for d in result ["districts"]:
            extra =f" — score {d ['ahp_score']:.3f}"if d .get ("ahp_score")is not None else ""
            lines .append (f"- {d ['district']} ({d ['governorate']}): "
            f"{d ['population']:,} pop, {d ['stations']} st, "
            f"priority {d ['ahp_priority']}{extra }")
        return "\n".join (lines )

    if intent =="governorate_summary":
        r =result 
        head =(f"**{r ['governorate']}**: {r ['districts']} districts, "
        f"{r ['population']:,} residents, {r ['stations']} stations"
        +(f" ({r ['pop_per_station']:,} per station)"if r .get ('pop_per_station')else ""))
        return head +"."

    if intent =="national":
        r =result 
        breakdown =", ".join (f"{k }: {v }"for k ,v in (r .get ('priority_breakdown')or {}).items ())
        return (f"Lebanon: {r ['total_districts']} districts, {r ['total_population']:,} residents, "
        f"{r ['total_stations']} stations"
        +(f" ({r ['pop_per_station']:,} per station)"if r .get ('pop_per_station')else "")
        +(f". {breakdown }."if breakdown else "."))

    if intent =="placement":
        r =result 
        if "error"in r :
            return r ["error"]
        lines =[
        f"Location resolved: {r ['resolved']}",
        f"District: {r ['district']} ({r ['governorate']}, {r ['area_type']})",
        f"Applied minimum spacing: {r ['applied_min_spacing_km']} km — **{r ['verdict']}**",
        ]
        if r ["existing_stations_in_radius"]:
            lines .append ("Existing stations nearby:")
            for s in r ["existing_stations_in_radius"]:
                sid =f" (#{s ['station_id']})"if s .get ("station_id")else ""
                lines .append (f"  - {s ['location']}{sid } — {s ['distance_km']} km")
        if r ["alternatives"]:
            lines .append ("\nHigher-impact alternatives by AHP score:")
            for a in r ["alternatives"]:
                extra =f", score {a ['ahp_score']:.3f}"if a .get ("ahp_score")is not None else ""
                lines .append (f"  - {a ['district']} ({a ['governorate']}): "
                f"{a ['population']:,} pop, {a ['stations']} st, "
                f"priority {a ['ahp_priority']}{extra }")
        return "\n".join (lines )

    if intent =="rules":
        return result ["markdown"]

    if intent =="hospital_district":
        r =result 
        if "error"in r :
            return r ["error"]
        if r ["hospital_count"]==0 :
            return f"**{r ['district']}** ({r ['governorate']}): no hospitals mapped in this district."
        lines =[f"**{r ['district']}** ({r ['governorate']}): {r ['hospital_count']} hospital(s), "
        f"{r ['total_beds']} beds — {r ['public']} public, {r ['private']} private."]
        for h in r ["hospitals"][:8 ]:
            est =" *(est.)*"if h ["beds_estimated"]else ""
            lines .append (f"- {h ['name']} [{h ['type']}] — {h ['beds']} beds{est }")
        return "\n".join (lines )

    if intent =="hospital_governorate":
        r =result 
        if "error"in r :
            return r ["error"]
        lines =[f"**{r ['governorate']}**: {r ['hospital_count']} hospitals, "
        f"{r ['total_beds']} beds — {r ['public']} public, {r ['private']} private."]
        for d in r ["district_breakdown"]:
            if d ["hospital_count"]>0 :
                lines .append (f"- {d ['district']}: {d ['hospital_count']} hospitals, {d ['total_beds']} beds "
                f"({d ['public']} pub / {d ['private']} priv)")
        return "\n".join (lines )

    if intent =="hospital_national":
        r =result 
        bper =f", {r ['beds_per_1000']} beds/1,000 population"if r .get ("beds_per_1000")else ""
        return (f"Lebanon: **{r ['total_hospitals']}** hospitals, **{r ['total_beds']}** beds{bper }. "
        f"{r ['public']} public, {r ['private']} private. _{r ['note']}_")

    if intent =="nearest_hospital":
        r =result 
        if "error"in r :
            return r ["error"]
        lines =[f"Nearest hospitals to **{r ['resolved']}**:"]
        for h in r ["nearest_hospitals"]:
            est =" *(est.)*"if h .get ("beds_estimated")else ""
            dist_str =f"{h ['distance_km']} km (straight-line)"
            lines .append (f"- {h ['name']} [{h ['type']}] — {h ['beds']} beds{est }, {dist_str } "
            f"({h .get ('district','?')}, {h .get ('governorate','?')})")
        return "\n".join (lines )

    if intent =="coverage_gaps":
        r =result 
        if not r .get ("zero_station_districts")and not r .get ("highest_gap_districts"):
            return r .get ("note","No coverage gap data available.")
        lines =[]
        if r .get ("filter"):
            lines .append (f"Coverage gaps in **{r ['filter']}**:")
        if r ["zero_station_districts"]:
            lines .append ("**Districts with zero EMS stations:**")
            for d in r ["zero_station_districts"]:
                lines .append (f"- {d ['district']} ({d ['governorate']}): {d ['population']:,} residents, "
                f"{d .get ('exposed_population',d ['population']):,} exposed")
        if r ["highest_gap_districts"]:
            lines .append ("\n**Highest coverage gaps (by exposed population):**")
            for d in r ["highest_gap_districts"]:
                tt =f", ~{d ['min_travel_time_min']:.0f} min to station"if d .get ("min_travel_time_min")else ""
                lines .append (f"- {d ['district']} ({d ['governorate']}): "
                f"{d ['exposed_population']:,} exposed, {d ['stations']} station(s){tt }, "
                f"priority {d ['ahp_priority']}")
        lines .append (f"\n_{r ['note']}_")
        return "\n".join (lines )

    if intent =="affordability":
        r =result 
        if "error"in r :
            return r ["error"]
        if r ["scope"]=="district":
            verdict =r ["verdict"]
            return (f"**{r ['name']}** ({r ['governorate']}): {r ['total_hospitals']} hospital(s) — "
            f"{r ['public']} public ({r ['public_pct']}%), {r ['private']} private. {verdict }")
        if r ["scope"]=="governorate":
            no_pub =", ".join (r ["districts_without_public_hospital"])or "none"
            return (f"**{r ['name']}**: {r ['total_hospitals']} hospitals — "
            f"{r ['public']} public ({r ['public_pct']}%), {r ['private']} private. "
            f"Districts with no public hospital: {no_pub }.")

        no_pub =", ".join (r ["districts_without_public_hospital"][:8 ])
        more =f" (+{len (r ['districts_without_public_hospital'])-8 } more)"if len (r ["districts_without_public_hospital"])>8 else ""
        return (f"Lebanon: {r ['public_pct']}% public hospitals ({r ['public']}/{r ['total_hospitals']}). "
        f"{r ['population_without_public_hospital']:,} residents live in districts with no public hospital. "
        f"Districts affected: {no_pub }{more }. _{r ['note']}_")

    if intent =="exposed_population":
        r =result 
        if "error"in r :
            return r ["error"]
        if "district"in r :
            exp =r .get ("exposed_population")
            pct =r .get ("exposed_pct")
            if exp is not None :
                exp_str =f"{exp :,} ({pct }%)"if pct is not None else f"{exp :,} (0%)"
            else :
                exp_str ="N/A"
            tt =f", ~{r ['min_travel_time_min']:.0f} min to nearest station"if r .get ("min_travel_time_min")else ""
            return (f"**{r ['district']}** ({r ['governorate']}): population {r ['population']:,}, "
            f"exposed {exp_str }{tt }, AHP priority {r .get ('ahp_priority')or 'N/A'}.")
        if "governorate"in r :
            lines =[f"**{r ['governorate']}**: {r ['exposed_population']:,} of {r ['population']:,} residents exposed ({r .get ('exposed_pct','?')}%)."]
            for d in r ["district_breakdown"]:
                lines .append (f"- {d ['district']}: {d ['exposed_population']:,} exposed ({d ['exposed_pct']}%)")
            return "\n".join (lines )

        lines =[f"Lebanon: **{r ['exposed_population']:,}** of {r ['population']:,} residents outside EMS coverage ({r .get ('exposed_pct','?')}%)."]
        lines .append ("Worst districts:")
        for d in r ["worst_districts"]:
            lines .append (f"- {d ['district']} ({d ['governorate']}): {d ['exposed_population']:,} exposed")
        return "\n".join (lines )

    return json .dumps (result ,indent =2 ,default =str )

app =FastAPI (title ="Lebanon EMS Copilot (AHP)")
app .add_middleware (
CORSMiddleware ,
allow_origins =["*"],
allow_methods =["*"],
allow_headers =["*"],
)

class ChatRequest (BaseModel ):
    message :str 
    use_llm :bool =True 
    dataset_mode :str ="ems"

class ChatResponse (BaseModel ):
    answer :str 
    intent :Optional [str ]=None 
    data :Optional [Dict [str ,Any ]]=None 

@app .get ("/health")
def health ():
    try :
        r =requests .get (f"{OLLAMA_URL }/api/tags",timeout =2 )
        ollama_ok =r .status_code ==200 
        models =[m ["name"]for m in r .json ().get ("models",[])]if ollama_ok else []
    except Exception :
        ollama_ok ,models =False ,[]
    return {
    "status":"ok",
    "ollama":ollama_ok ,
    "model":OLLAMA_MODEL ,
    "model_pulled":OLLAMA_MODEL in models or any (OLLAMA_MODEL in m for m in models ),
    "ahp_loaded":bool (ahp_lookup ),
    "districts_loaded":int (len (districts_agg )),
    "stations_loaded":int (len (ems_valid )),
    }

HOSPITAL_MODE_HINT =(
"The user is currently viewing the **Hospitals** dataset. "
"Prioritise hospital-related answers: bed counts, public/private access, "
"nearest hospitals, affordability, and hospital coverage gaps. "
"If the question is ambiguous (e.g. 'do we have a gap'), interpret it as "
"a hospital access gap question, not an EMS station gap."
)

EMS_FALLBACK =(
"I can answer questions about district populations, EMS stations, "
"AHP priority rankings, comparisons, and placement. "
"Try: 'Which districts are highest priority?' or "
"'Where can I open an EMS center in Ras al Nabeh, Beirut?'"
)

HOSPITAL_FALLBACK =(
"I can answer questions about hospitals, bed counts, public vs. private access, "
"nearest hospitals, and affordability. "
"Try: 'How many hospitals in Bekaa?' or 'Which districts have no public hospitals?'"
)

@app .post ("/chat",response_model =ChatResponse )
def chat (req :ChatRequest ):
    mode =req .dataset_mode or "ems"

    routed =route_intent (req .message ,mode =mode )
    intent =routed ["intent"]if routed else None 
    tool_result =routed ["result"]if routed else None 

    if req .use_llm :
        extra_system =HOSPITAL_MODE_HINT if mode =="hospitals"else None 
        answer =call_ollama (req .message ,tool_result ,extra_system =extra_system )
        if answer .startswith ("(")and tool_result is not None :
            answer =format_tool_result (intent ,tool_result )+"\n\n_(LLM unavailable — showing deterministic answer.)_"
    else :
        if tool_result is not None :
            answer =format_tool_result (intent ,tool_result )
        else :
            answer =HOSPITAL_FALLBACK if mode =="hospitals"else EMS_FALLBACK 

    return ChatResponse (answer =answer ,intent =intent ,data =tool_result )

if __name__ =="__main__":
    import uvicorn 
    uvicorn .run (app ,host ="127.0.0.1",port =8000 )
