CITATIONS ={
"LRC-9":"Lebanese Red Cross / IFRC INP 2023 — 80% of EMS calls within 9 min",
"LRC-13":"Lebanese Red Cross / IFRC INP 2023 — 85% of EMS calls within 13 min",
"MoPH-473":"Lebanese Ministry of Public Health, Karar No. 473/2021 — EMS licensing",
"EU-8":"European standard — 8 min for critical (life-threatening) calls",
"WHO":"WHO Clinical Services & Systems framework — ambulance base station definition",
}

RULES ={
"response_time_target_min":{
"value":9 ,
"unit":"minutes",
"source":"LRC-9",
"type":"statutory_target",
"description":"LRC operational target: reach 80% of calls within 9 min.",
},
"response_time_extended_min":{
"value":13 ,
"unit":"minutes",
"source":"LRC-13",
"type":"statutory_target",
"description":"LRC operational target: reach 85% of calls within 13 min.",
},
"critical_response_min":{
"value":8 ,
"unit":"minutes",
"source":"EU-8",
"type":"international_reference",
"description":"European standard for life-threatening calls.",
},
"coverage_threshold_min":{
"value":10 ,
"unit":"minutes",
"source":"project_threshold",
"type":"demo_heuristic",
"description":"AHP coverage threshold: districts whose nearest station is beyond 10 min by road are flagged 'exposed'.",
},
"drive_radius_urban_km":{
"value":3.0 ,
"unit":"km",
"source":"derived",
"type":"demo_heuristic",
"description":"Approx. drive distance reachable in 9 min at urban speeds (20 km/h avg).",
},
"drive_radius_rural_km":{
"value":10.0 ,
"unit":"km",
"source":"derived",
"type":"demo_heuristic",
"description":"Approx. drive distance reachable in 13 min at rural speeds (45 km/h avg).",
},
"min_spacing_urban_km":{
"value":1.5 ,
"unit":"km",
"source":"heuristic",
"type":"demo_heuristic",
"description":"Suggested minimum spacing between EMS bases in urban areas to avoid coverage overlap. Lebanon does not publicly codify a spacing rule.",
},
"min_spacing_rural_km":{
"value":5.0 ,
"unit":"km",
"source":"heuristic",
"type":"demo_heuristic",
"description":"Suggested minimum spacing between EMS bases in rural areas.",
},
"overcrowded_stations_in_radius":{
"value":2 ,
"unit":"stations",
"source":"heuristic",
"type":"demo_heuristic",
"description":"If 2 or more existing stations fall within the minimum-spacing radius, the area is considered already well-served.",
},
"target_pop_per_station":{
"value":50000 ,
"unit":"residents",
"source":"derived",
"type":"demo_heuristic",
"description":"Target ratio derived from LRC's nationwide ~45 stations serving ~5.76M residents (~128k/station nationally), with 50k/station as an improvement target.",
},
"ahp_weights":{
"value":{"travel_time_gap":0.5 ,"pop_density":0.3 ,"exposed_pop":0.2 },
"unit":"weights",
"source":"project_default",
"type":"ahp_default",
"description":"Default AHP criteria weights: 50% travel-time gap, 30% population density, 20% exposed population.",
},
}

URBAN_GOVERNORATES ={"Beirut","MountLebanon","Mount Lebanon"}

def is_urban (governorate :str )->bool :
    return (governorate or "").replace (" ","")in {g .replace (" ","")for g in URBAN_GOVERNORATES }

def rules_summary_markdown ()->str :
    lines =["**Authoritative standards**"]
    for key in ("response_time_target_min","response_time_extended_min","critical_response_min"):
        r =RULES [key ]
        lines .append (f"- {r ['description']} *({CITATIONS [r ['source']]})*")
    lines .append ("\n**Project AHP defaults**")
    w =RULES ["ahp_weights"]["value"]
    lines .append (f"- Criteria weights: travel-time gap {int (w ['travel_time_gap']*100 )}%, "
    f"population density {int (w ['pop_density']*100 )}%, exposed population {int (w ['exposed_pop']*100 )}%.")
    lines .append (f"- Coverage threshold: {RULES ['coverage_threshold_min']['value']} min by road network.")
    lines .append ("\n**Demo heuristics (this project)**")
    for key in ("drive_radius_urban_km","min_spacing_urban_km","min_spacing_rural_km",
    "overcrowded_stations_in_radius","target_pop_per_station"):
        r =RULES [key ]
        lines .append (f"- {r ['description']}")
    return "\n".join (lines )
