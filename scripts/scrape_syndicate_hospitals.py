import csv 
import html 
import os 
import re 
import time 
import urllib .request 

BASE ="https://www.syndicateofhospitals.org.lb"
INDEX_URL =f"{BASE }/Hospitals/Index?name="
DETAIL_URL =f"{BASE }/Hospitals/Details/{{id}}"
UA ="Mozilla/5.0 (research; Lebanon EMS academic project)"
DELAY_SECONDS =0.5 

SCRIPT_DIR =os .path .dirname (os .path .abspath (__file__ ))
DATA_DIR =os .path .join (os .path .dirname (SCRIPT_DIR ),"data")
OUT_CSV =os .path .join (DATA_DIR ,"lebanon_hospitals_syndicate.csv")

FIELD_MAP ={
"Number of Beds":"beds",
"Location":"location",
"Address":"address",
"Date of Establishment":"established",
"Type of Care Offered":"type_of_care",
"Accredited by the Lebanese Ministry of Public Health":"moph_accredited",
}

def fetch (url ):
    req =urllib .request .Request (url ,headers ={"User-Agent":UA })
    with urllib .request .urlopen (req ,timeout =30 )as resp :
        return resp .read ().decode ("utf-8",errors ="ignore")

def clean (s ):
    return html .unescape (re .sub (r"<[^>]+>"," ",s )).strip ()

def parse_index (h ):
    pairs =re .findall (r'href="/Hospitals/Details/(\d+)"[^>]*>(.*?)</a>',h ,re .S )
    out =[]
    for sid ,nm in pairs :
        out .append ((int (sid ),clean (nm )))
    return out 

def parse_detail (h ):
    cells =re .findall (r"<td[^>]*>(.*?)</td>",h ,re .S )
    cells =[clean (c )for c in cells ]
    fields ={}

    for i in range (0 ,len (cells )-1 ,2 ):
        label ,value =cells [i ],cells [i +1 ]
        if label in FIELD_MAP :
            fields [FIELD_MAP [label ]]=value 
    return fields 

def parse_beds (val ):
    if not val :
        return None 
    m =re .search (r"\d{1,4}",val .replace (",",""))
    return int (m .group ())if m else None 

def main ():
    print ("Fetching index ...")
    index_html =fetch (INDEX_URL )
    hospitals =parse_index (index_html )
    print (f"  {len (hospitals )} hospitals listed (ids {min (i for i ,_ in hospitals )}"
    f"-{max (i for i ,_ in hospitals )})")

    rows =[]
    for n ,(sid ,name )in enumerate (hospitals ,1 ):
        try :
            detail =fetch (DETAIL_URL .format (id =sid ))
            f =parse_detail (detail )
        except Exception as e :
            print (f"  [{n }/{len (hospitals )}] id={sid } {name !r } FETCH ERROR: {e }")
            f ={}
        beds =parse_beds (f .get ("beds"))
        rows .append ({
        "syndicate_id":sid ,
        "name":name ,
        "beds":beds if beds is not None else "",
        "location":f .get ("location",""),
        "address":f .get ("address",""),
        "established":f .get ("established",""),
        "type_of_care":f .get ("type_of_care",""),
        "moph_accredited":f .get ("moph_accredited",""),
        })
        if n %20 ==0 or n ==len (hospitals ):
            print (f"  [{n }/{len (hospitals )}] last: {name !r } beds={beds }")
        time .sleep (DELAY_SECONDS )

    fields =["syndicate_id","name","beds","location","address",
    "established","type_of_care","moph_accredited"]
    with open (OUT_CSV ,"w",newline ="",encoding ="utf-8")as fh :
        w =csv .DictWriter (fh ,fieldnames =fields )
        w .writeheader ()
        w .writerows (rows )

    with_beds =sum (1 for r in rows if r ["beds"]!="")
    total_beds =sum (r ["beds"]for r in rows if r ["beds"]!="")
    print (f"\nOK: {len (rows )} hospitals | with bed counts: {with_beds } "
    f"| total beds: {total_beds :,}")
    print (f"Wrote {OUT_CSV }")

if __name__ =="__main__":
    main ()
