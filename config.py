# config.py
# All the settings for NANAY live here, so we only change numbers in ONE place.
# Anything marked ASSUMPTION is a value we chose ourselves (not measured).
# These are the numbers we will vary in the sensitivity analysis (+/- 20%).

from pathlib import Path

# ---------------------------------------------------------------
# Folders
# ---------------------------------------------------------------
ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"            # files downloaded from official sources (never edit these)
MANUAL = ROOT / "data" / "manual"      # files our team fills in by hand
PROCESSED = ROOT / "data" / "processed"  # files our scripts create
DEMO = ROOT / "data" / "demo"          # FAKE data, only for testing the app. Delete before submission.
OUTPUTS = ROOT / "outputs"

# Set to True to run everything on FAKE demo data (before the real data is ready).
# You can also turn it on without editing this file:  set NANAY_DEMO=1  (Windows cmd)
import os
USE_DEMO_DATA = False or os.environ.get("NANAY_DEMO") == "1"
if USE_DEMO_DATA:
    PROCESSED = DEMO  # scripts 04-05 and the app read/write the demo folder instead

# ---------------------------------------------------------------
# Study area
# ---------------------------------------------------------------
PLACE_NAME = "Negros Oriental, Philippines"

# ---------------------------------------------------------------
# Road network
# ---------------------------------------------------------------
# Which OpenStreetMap roads to download. We include "track" because
# habal-habal (motorcycles) use dirt tracks in upland barangays.
ROAD_FILTER = (
    '["highway"~"trunk|trunk_link|primary|primary_link|secondary|secondary_link|'
    'tertiary|tertiary_link|unclassified|residential|living_street|service|track"]'
)

# ASSUMPTION: average travel speed (km/h) by road type, dry season.
# Based on a motorcycle / multicab trip, not a speeding ambulance.
DRY_SPEEDS_KMH = {
    "trunk": 50,
    "primary": 45,
    "secondary": 40,
    "tertiary": 35,
    "unclassified": 30,
    "residential": 25,
    "living_street": 20,
    "service": 20,
    "track": 15,
}
DEFAULT_SPEED_KMH = 25  # used if a road has an unknown type

# ASSUMPTION: rainy season speed = dry speed x this factor.
# Paved main roads barely slow down; dirt tracks slow down a lot.
RAINY_FACTOR = {
    "trunk": 0.9,
    "primary": 0.9,
    "secondary": 0.85,
    "tertiary": 0.8,
    "unclassified": 0.7,
    "residential": 0.8,
    "living_street": 0.8,
    "service": 0.8,
    "track": 0.4,
}
UNPAVED_RAINY_FACTOR = 0.5  # extra slowdown for any road tagged as unpaved/gravel/dirt

# ASSUMPTION: walking speed (km/h) from the barangay center to the nearest road.
WALK_SPEED_KMH = 4

# If a barangay center is farther than this from ANY connected road, we do not
# pretend people walk it (e.g. small islands need a boat). We mark it
# "No road connection" and handle it separately.
MAX_WALK_KM = 8

# ---------------------------------------------------------------
# Access thresholds
# ---------------------------------------------------------------
# 2 hours = global benchmark for timely access to emergency surgery,
# including caesarean section (Meara et al., 2015).
THRESHOLD_MIN = 120
# (The map's color bands are relative to the time limit: half of it, the limit, over it.)

# Facility levels used in the analysis, from lowest to highest.
# "obstetric_level" in data/manual/facility_capability.csv must use these words.
LEVELS = ["birthing", "BEmONC", "CEmONC"]

# ASSUMPTION: care level by DOH facility type, used ONLY when obstetric_level is blank
# (a level the team confirmed always wins). There is no public list of which
# Negros Oriental facilities are certified BEmONC / CEmONC, so this is our estimate:
#   Hospital      -> CEmONC   hospitals must have a surgery room, maternity care and a
#                             blood station (DOH AO 2012-0012, as reported by the Inquirer)
#   Infirmary     -> BEmONC   beds and maternity care, but no caesareans assumed
#   Birthing Home -> birthing licensed for normal deliveries
#   anything else -> none     (RHUs count only through their own licensed birthing home row)
LEVEL_BY_TYPE = {"Hospital": "CEmONC", "Infirmary": "BEmONC", "Birthing Home": "birthing"}

# STRICTER SCENARIO (sensitivity test): only GOVERNMENT hospitals count as CEmONC;
# private hospitals with an assumed level are counted one level lower.
STRICT_PRIVATE_HOSPITAL_LEVEL = "BEmONC"

# Which scenario the app shows first: "type" (main assumption) or "strict"
DEFAULT_LEVEL_SCENARIO = "type"

# ---------------------------------------------------------------
# Barangay input files (you download these into data/raw/)
# ---------------------------------------------------------------
# Barangay boundaries: Philippines admin level 4 (barangay) boundaries from HDX
# (NAMRIA / PSA via OCHA, "cod-ab-phl"). scripts/03a_cut_boundaries.py cuts the
# Negros Oriental part out of the national file and saves it here:
BOUNDARY_FILE = RAW / "hdx_boundaries" / "negros_oriental_barangays.gpkg"
BOUNDARY_PROVINCE_COL = "adm2_name"   # province name column
BOUNDARY_MUNI_COL = "adm3_name"       # city/municipality name column
BOUNDARY_BRGY_COL = "adm4_name"       # barangay name column

# Barangay population from the PSA 2020 census. We make this CSV ourselves from
# the PSA Excel file, with exactly these three columns:
#   municipality, barangay, population_2020
POPULATION_FILE = RAW / "barangay_population_2020.csv"

# ---------------------------------------------------------------
# Population
# ---------------------------------------------------------------
# Share of the population who are women aged 15-49.
# Leave as None until we take the real number from the PSA 2020 census
# for Negros Oriental. While None, the app counts ALL people and labels it that way.
WOMEN_15_49_SHARE = None

# ---------------------------------------------------------------
# Context KPIs (dashboard cards). Each file is optional: if it is missing
# or still empty, the app shows "Data not loaded yet" for that card only.
# In demo mode we read FAKE versions from data/demo/ instead.
# ---------------------------------------------------------------
KPI_FOLDER = DEMO if USE_DEMO_DATA else RAW

# PSA registered live births in Negros Oriental, by month
BIRTHS_FILE = KPI_FOLDER / "births_by_month.csv"
BIRTHS_COLUMNS = ["year", "month", "registered_births"]

# PAGASA climatological normals, station nearest to Negros Oriental
RAINFALL_FILE = KPI_FOLDER / "monthly_rainfall.csv"
RAINFALL_COLUMNS = ["month", "normal_rainfall_mm", "rainy_days"]

# PSA small-area poverty estimates, city/municipality level
POVERTY_FILE = KPI_FOLDER / "poverty_municipal.csv"
POVERTY_COLUMNS = ["municipality", "poverty_incidence_pct", "year"]

# ASSUMPTION: a month with at least this much normal rainfall (mm) uses the
# RAINY-season travel times. Our own choice, not a PAGASA definition.
# Replace with a sourced value when we have one.
RAINY_MONTH_MM_THRESHOLD = 200

# Equity KPI: compare the poorest 20% of municipalities with the least-poor 20%.
EQUITY_GROUP_SHARE = 0.20

# ---------------------------------------------------------------
# Optimization
# ---------------------------------------------------------------
# Which facility types can be "upgraded" in the what-if / optimization.
CANDIDATE_TYPES = ["Rural Health Unit", "Birthing Home", "Infirmary", "City Health Office"]
MAX_NEW_SITES = 3

# The province's own CEmONC siting choices: it built CEmONC facilities at the Bayawan and
# Guihulngan district hospitals (Provincial Government of Negros Oriental news release,
# negor.gov.ph/?p=535, cited in our concept proposal). The app marks these two so planners
# can see how much each choice protects. Names exactly as in data/processed/facilities.csv.
PROVINCE_CEMONC_SITES = ["BAYAWAN DISTRICT HOSPITAL", "GOV. WILLIAM (BILLY) VILLEGAS MEMORIAL HOSPITAL"]

# ---------------------------------------------------------------
# Sensitivity check
# ---------------------------------------------------------------
# ASSUMPTION TEST: our road and walking speeds are guesses. The app re-counts the
# headline with EVERY speed 20% slower and 20% faster, to show how much the result
# depends on them (the concept proposal promises a +/-20% check).
SENSITIVITY_SPEED_CHANGE = 0.20

# ---------------------------------------------------------------
# Data dates (printed on the birth-plan sheets, so an old printout can be recognised)
# ---------------------------------------------------------------
FACILITY_DATA_DATE = "15 Oct 2026"   # DOH National Health Facility Registry download
ROAD_DATA_DATE = "18 Oct 2026"       # OpenStreetMap roads (Geofabrik extract)
