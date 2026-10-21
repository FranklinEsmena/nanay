# NANAY: how far are mothers from emergency childbirth care?

NANAY (*Navigating Access Networks for At-risk mothers and Young women*; "nanay" means mother)
estimates how long it takes to travel from each of the 557 barangays of Negros Oriental to the
nearest facility that can handle a childbirth emergency, in the dry and the rainy season, and
suggests which facility upgrades would bring the most people within 2 hours of care.

It has two pages, for two kinds of health workers:

| Page | For | What it answers |
|---|---|---|
| **Planning dashboard** | Provincial and city health offices | Which barangays are far from care, how rain changes that, which facility has no backup, and where an upgrade would help most |
| **Birth-plan sheets** | Midwives and barangay health workers | A printable one-page sheet per barangay: nearest facility for each level of care, its phone number, dry and rainy travel times (one barangay, or a whole town as one PDF) |

**Live app:** _add the Streamlit Community Cloud link here after deployment_

Mothers are the people who benefit; they receive the information through the midwife's sheet.
All results describe **areas, not individual women**, and are decision support, not clinical guidance.

---

## Key results (rainy season, C-section care (CEmONC), 2-hour limit)

These are model estimates (see Known limits). People = all ages, PSA 2020 Census.

- **38,140 people (2.7%) live more than 2 hours** from a hospital that can do a caesarean section
  and give blood. In the **dry season: 8,723 (0.6%)**.
- **All 8,723 dry-season people live in 6 barangays our road data does not reach** (Apo Island,
  Olympia, and 4 upland Guihulngan barangays). Everyone with a road is within 2 hours in the dry
  season. The rainy season adds 12 barangays (29,417 people) that have a road but are too slow.
- **How sure:** with every assumed speed 20% slower or faster, the rainy number ranges from
  21,348 to 73,603. Counting private hospitals as basic care only (strict scenario) gives the
  same 38,140, so this result does not depend on how private hospitals are classified.
- **Border effect:** 24,634 of the 38,140 live in the 11 towns bordering Negros Occidental, whose
  hospitals are not in our model, so part of this gap may be overstated.
- **No backup:** if Gov. William (Billy) Villegas Memorial Hospital (Guihulngan City) closed,
  87,483 people would have no other C-section hospital within 2 hours.
- **Best upgrades (Maximal Covering Location Problem):** adding C-section capacity at Mabinay
  Medicare Community Hospital would bring 8,145 more people within 2 hours; the best 3 sites
  together, 19,619 (coverage 97.3% → 98.7%). Cost and staffing are not modelled.

---

## How the model works

1. **Facilities:** DOH National Health Facility Registry (no coordinates, no BEmONC/CEmONC field).
   The team located each facility on a map. Care level assumed from type: hospital = CEmONC
   (C-section and blood), infirmary = BEmONC (basic emergency care), birthing home = birthing.
2. **Barangays:** official boundaries (NAMRIA/PSA via HDX); one point inside each barangay;
   population from the PSA 2020 Census.
3. **Trip:** walk from the barangay point to the nearest road (4 km/h), ride the fastest road route
   on OpenStreetMap (assumed speed per road type, Dijkstra's shortest path), walk to the facility.
   A barangay more than 8 km from a road, on a road piece cut off from the network, or across the
   sea counts as "no road".
4. **Rainy season:** every road type is slowed by an assumed factor; dirt roads the most.
5. **Covered:** a trip within the time limit (default 2 hours, the benchmark for timely access to
   caesarean section; Meara et al., 2015).
6. **Upgrades:** the Maximal Covering Location Problem (Church & ReVelle, 1974), solved with PuLP,
   picks the rural health units, birthing homes or infirmaries whose upgrade covers the most people.
7. **Checks:** the headline is recounted with all speeds ±20%, and under the strict care-level scenario.

Every assumption (speeds, rain factors, care levels, limits) is labelled in `config.py`.

## Known limits

- **Care levels are assumed** (0 of 40 confirmed). Hospitals may not all offer 24-hour C-section
  and blood services; facilities may not be staffed or open 24 hours.
- **Rural health units** count as a place to give birth only if they also hold a birthing-home
  licence. Many are part of the BEmONC network, so basic-emergency and birthing gaps may be overstated.
- **Province border:** roads stop at the border, so hospitals in Negros Occidental are left out.
  Gaps in the 11 border towns may be overstated.
- **Rain factors and speeds are assumptions** with no measured source; the rainy result is a
  scenario (see the ±20% range).
- **"No road"** can mean an island that needs a boat, or a road missing on OpenStreetMap. The 4
  Guihulngan barangays sit on road pieces OpenStreetMap does not connect to the main network.
- **One point per barangay:** people living far from that point in large upland barangays may
  travel longer than shown.
- **All people, not women 15-49;** population from 2020.
- Only the second of the "three delays" (reaching care) is studied; deciding to seek care and
  quality of care are out of scope.

---

## Run it yourself (Windows, Python 3.13)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m pytest tests
streamlit run app.py
```

The processed data is included, so the app runs straight away. To rebuild everything from the
official files, run the scripts in order:

| Step | Command | Output |
|---|---|---|
| 1 | `python scripts\01_prepare_facilities.py` (reads `data/manual/facility_capability.csv`) | `data/processed/facilities.csv`, `candidates.csv` |
| 2 | Download https://download.geofabrik.de/asia/philippines-latest.osm.pbf into `data/raw/geofabrik/`, then `python scripts\02b_roads_from_geofabrik.py` (needs step 3a) | `data/processed/roads.graphml` |
| 3a | Download `phl_admin_boundaries.gdb.zip` from HDX (cod-ab-phl) into `data/raw/hdx_boundaries/`, then `python scripts\03a_cut_boundaries.py` | Negros Oriental barangay boundaries |
| 3b | `python scripts\03b_make_population_csv.py` (reads the PSA 2020 Region VII file) | `data/raw/barangay_population_2020.csv` |
| 3 | `python scripts\03_prepare_barangays.py` | `data/processed/barangays.csv` |
| 3c | `python scripts\03c_find_border_towns.py` | `data/processed/border_towns.csv` |
| 4 | `python scripts\04_travel_times.py` | dry and rainy travel-time tables |
| 5 | `python scripts\05_optimize.py` | `outputs/optimization_results.csv` |

Other scripts: `00_make_demo_data.py` (fake test data, run with `set NANAY_DEMO=1`),
`01a_suggest_coordinates.py` (OpenStreetMap coordinate suggestions, to check by hand),
`02_download_roads.py` (online alternative to step 2).

Optional (not included, no data yet): adding `data/raw/births_by_month.csv`, `monthly_rainfall.csv`
or `poverty_municipal.csv` (columns listed in `config.py`) makes the app show a month picker and an
equity measure.

## AI assistance

This app was developed with help from **Claude**, an AI assistant made by Anthropic. Claude helped
write and test the code, the data-processing scripts and this documentation. The team defined the
project and its users, collected and checked the data, made the design decisions and reviewed the
results.

## Data sources

- Department of Health. (2026). *National Health Facility Registry* [Data set]. Retrieved October 15, 2026, from https://nhfr.doh.gov.ph/VActivefacilitiesList
- OpenStreetMap contributors. (2026). *OpenStreetMap* [Data set]. https://www.openstreetmap.org (ODbL). Road extract for the Philippines from Geofabrik (https://download.geofabrik.de/asia/philippines.html), data as of October 18, 2026.
- Philippine Statistics Authority. (2021). *2020 Census of Population and Housing: Total population by province, city, municipality, and barangay, as of May 1, 2020 – Region VII* [Data set]. https://psa.gov.ph/content/2020-census-population-and-housing-2020-cph-population-counts-declared-official-president
- National Mapping and Resource Information Authority & Philippine Statistics Authority, via UN OCHA. (2025). *Philippines – Subnational Administrative Boundaries* (COD-AB, version v03) [Data set]. Humanitarian Data Exchange. https://data.humdata.org/dataset/cod-ab-phl (CC BY-IGO). Retrieved October 20, 2026.
- Meara, J. G., et al. (2015). Global Surgery 2030. *The Lancet*, 386(9993), 569–624.
- Church, R., & ReVelle, C. (1974). The maximal covering location problem. *Papers of the Regional Science Association*, 32(1), 101–118.

## Project layout

```
app.py           starts the app (two pages)
app_pages/       dashboard.py (health offices) and birth_plan.py (midwives)
app_data.py      data loading shared by both pages
config.py        all settings and labelled assumptions
helpers.py       shared calculations (tested in tests/)
scripts/         pipeline steps 00-05, run in order
data/raw/        official files (not edited)
data/manual/     facility list checked by hand
data/processed/  made by the scripts; used by the app
static/, assets/ logos
```
