# 01a_suggest_coordinates.py
# Step 1a (optional helper, run BEFORE step 1):
# look up SUGGESTED coordinates for each facility on OpenStreetMap.
#
# Every suggestion must be CHECKED BY A PERSON on a map before we trust it.
# The script only fills EMPTY latitude/longitude cells; it never overwrites
# coordinates the team already typed in.
#
# Input : data/manual/facility_capability.csv
# Output: the same file (blank coordinates filled, marked "SUGGESTED ... VERIFY")
#         data/manual/coordinate_suggestions_review.csv  (map links for checking)
#
# Uses the free OpenStreetMap search service "Nominatim". Its usage policy says
# at most 1 request per second and no repeated bulk queries, so we wait between
# requests and save every answer in a cache file (re-running costs nothing).
#
# Run from the project folder:  python scripts/01a_suggest_coordinates.py

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

if config.USE_DEMO_DATA:
    sys.exit("Turn demo mode off first (set NANAY_DEMO=) - this script works on the REAL facility list.")

MANUAL_FILE = config.MANUAL / "facility_capability.csv"
REVIEW_FILE = config.MANUAL / "coordinate_suggestions_review.csv"
CACHE_FILE = config.PROCESSED / "nominatim_cache.json"

SEARCH_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "NANAY-maternal-access-study/1.0"  # Nominatim asks every app to name itself
# Box around Negros Oriental (same limits as script 01): west, north, east, south
VIEWBOX = "122.5,10.6,123.6,8.9"

# OpenStreetMap tags that mean "this point is a health facility"
HEALTH_TYPES = {"hospital", "clinic", "doctors", "health_post", "healthcare", "birthing_center",
                "midwife", "centre", "health_centre"}
# OpenStreetMap tags that mean "this point is a barangay / village"
PLACE_TYPES = {"village", "suburb", "neighbourhood", "hamlet", "quarter", "administrative"}
# ...but never accept a whole town/city as a "barangay center" (far too rough)
TOO_BIG = {"city", "town", "municipality", "county", "state", "region"}


# ---------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------
def short_municipality(name):
    """'CITY OF BAIS' -> 'Bais'  (OpenStreetMap uses the short name)."""
    name = re.sub(r"^CITY OF ", "", name.strip().upper())
    return name.title()


def clean_facility_name(name):
    """Drop parts that rarely appear on OpenStreetMap: '(ACE)', 'INC.', 'IMAP', '- ...'."""
    name = re.sub(r"\(.*?\)", " ", name)
    name = re.sub(r"\b(INC|IMAP)\b\.?", " ", name, flags=re.IGNORECASE)
    name = name.split(" - ")[0]
    return re.sub(r"\s+", " ", name).strip(" ,.-")


def simple_barangay(name):
    """'POBLACION NO. III' and 'Poblacion 3' -> 'poblacion 3', so we can compare them."""
    name = name.lower().replace("no.", " ").replace("district", " ")
    for roman, digit in [("viii", "8"), ("vii", "7"), ("vi", "6"), ("iv", "4"), ("v", "5"),
                         ("iii", "3"), ("ii", "2"), ("i", "1")]:
        name = re.sub(rf"\b{roman}\b", digit, name)
    return re.sub(r"\s+", " ", name).strip()


def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def search(query, cache):
    """Ask Nominatim (or the cache) for up to 5 matches inside Negros Oriental."""
    if query in cache:
        return cache[query]
    params = {"q": query, "format": "jsonv2", "countrycodes": "ph", "limit": 5,
              "viewbox": VIEWBOX, "bounded": 1}
    url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        results = json.loads(response.read().decode("utf-8"))
    time.sleep(1.1)  # usage policy: max 1 request per second
    cache[query] = results
    CACHE_FILE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return results


def first_match(results, municipality, wanted_types):
    """First result of the wanted kind whose address mentions the right municipality."""
    for r in results:
        kind = {r.get("type", ""), r.get("category", ""), r.get("addresstype", "")}
        in_town = municipality.lower() in r.get("display_name", "").lower()
        first_part = r.get("display_name", "").split(",")[0].strip().lower()
        is_whole_town = r.get("addresstype", "") in TOO_BIG or first_part == municipality.lower()
        if kind & wanted_types and in_town and not is_whole_town:
            return r
    return None


# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------
df = pd.read_csv(MANUAL_FILE, dtype=str, keep_default_na=False, encoding="utf-8-sig")
config.PROCESSED.mkdir(parents=True, exist_ok=True)
cache = load_cache()
review_rows = []
counts = {"facility found": 0, "facility found, different barangay": 0,
          "barangay center only": 0, "not found": 0, "already filled": 0}

for i, row in df.iterrows():
    if row["latitude"].strip() and row["longitude"].strip():
        counts["already filled"] += 1
        continue

    muni = short_municipality(row["city_municipality"])
    brgy = row["barangay"].strip().title()
    name = row["facility_name"].strip()

    # 1) Try to find the facility itself (full name, then a cleaned-up name)
    match, how = None, None
    for query_name in dict.fromkeys([name, clean_facility_name(name)]):  # no duplicates
        match = first_match(search(f"{query_name}, {muni}, Negros Oriental", cache), muni, HEALTH_TYPES)
        if match:
            # Same barangay as the registry? If not, it may be a DIFFERENT branch/office.
            same_brgy = simple_barangay(brgy) in simple_barangay(match["display_name"])
            how = "facility found" if same_brgy else "facility found, different barangay"
            break

    # 2) Otherwise fall back to the CENTER of its barangay (less precise!)
    if match is None and brgy:
        match = first_match(search(f"{brgy}, {muni}, Negros Oriental", cache), muni, PLACE_TYPES)
        if match:
            how = "barangay center only"

    if match is None:
        counts["not found"] += 1
        print(f"  not found: {name} ({muni})")
        continue

    counts[how] += 1
    lat, lon = round(float(match["lat"]), 6), round(float(match["lon"]), 6)
    note = {"facility found": "facility found",
            "facility found, different barangay": "a facility with this name found in a DIFFERENT "
                                                  "barangay than the registry - check carefully",
            "barangay center only": "barangay center only, NOT the building"}[how]
    df.at[i, "latitude"] = str(lat)
    df.at[i, "longitude"] = str(lon)
    df.at[i, "coordinate_source"] = (f"SUGGESTED by OpenStreetMap search {time.strftime('%Y-%m-%d')}: "
                                     f"{note} - VERIFY on a map")
    review_rows.append({
        "nhfr_code": row["nhfr_code"], "facility_name": name, "municipality": muni, "barangay": brgy,
        "match": how, "osm_result": match.get("display_name", ""), "latitude": lat, "longitude": lon,
        "check_on_openstreetmap": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=18/{lat}/{lon}",
        "check_on_google_maps": f"https://www.google.com/maps/search/?api=1&query={lat},{lon}",
    })

df.to_csv(MANUAL_FILE, index=False, encoding="utf-8-sig")  # utf-8-sig so Excel shows Ñ correctly
pd.DataFrame(review_rows).to_csv(REVIEW_FILE, index=False, encoding="utf-8-sig")

print("\nResults:")
for k, v in counts.items():
    print(f"  {k}: {v}")
print(f"\nUpdated {MANUAL_FILE.name}. Check every suggestion using the links in {REVIEW_FILE.name}.")
print("After checking a point, change its coordinate_source to say who checked it and when.")
