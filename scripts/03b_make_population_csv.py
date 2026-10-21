# 03b_make_population_csv.py
# Step 3b (run once, BEFORE step 3): turn the PSA 2020 Census Excel file into the
# simple CSV that step 3 reads (columns: municipality, barangay, population_2020).
#
# Input : data/raw/psa_2020_cph_region_vii.xlsx
#         PSA "Total Population by Province, City, Municipality, and Barangay, as of May 1, 2020",
#         Region VII file (Negros Oriental was part of Region VII in 2020). Sheet "neg or".
# Output: data/raw/barangay_population_2020.csv
#
# How the sheet is laid out:  a CITY/MUNICIPALITY row in CAPITALS with its total,
# then its barangays in normal case, each with its population.
#
# Run from the project folder:  python scripts/03b_make_population_csv.py

import re
import sys
from pathlib import Path

import openpyxl
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

SOURCE = config.RAW / "psa_2020_cph_region_vii.xlsx"
SHEET = "neg or"

if not SOURCE.exists():
    sys.exit(f"Save the PSA Region VII Excel file as {SOURCE} first.")

ws = openpyxl.load_workbook(SOURCE, read_only=True, data_only=True)[SHEET]

province_total = None
town_totals = {}   # what the PSA says each town has
rows = []          # one row per barangay
town = None

for cells in ws.iter_rows(values_only=True):
    values = [c for c in cells if c is not None and str(c).strip() != ""]
    # we only want rows that are exactly: a name + a population number
    if len(values) != 2 or not isinstance(values[0], str) or not isinstance(values[1], (int, float)):
        continue
    name, people = values[0].strip(), int(values[1])

    if name.upper().startswith("NEGROS ORIENTAL"):
        province_total = people
    # CAPITALS = city or municipality. Ignore text in brackets, because the PSA writes
    # e.g. "CITY OF DUMAGUETE (Capital)" with "(Capital)" in normal case.
    elif re.sub(r"\(.*?\)", "", name) == re.sub(r"\(.*?\)", "", name).upper():
        town = re.sub(r"\s*[\d*]+$", "", name)  # drop footnote marks like "1" or "*" at the end
        town_totals[town] = people
    elif town is not None:              # normal case = barangay of the current town
        rows.append({"municipality": town, "barangay": name, "population_2020": people})

pop = pd.DataFrame(rows)

# ---- Checks: the barangays must add up to the PSA's own totals ----
print(f"Cities/municipalities: {len(town_totals)}, barangays: {len(pop)}")
sums = pop.groupby("municipality")["population_2020"].sum()
bad = [(t, town_totals[t], sums.get(t, 0)) for t in town_totals if sums.get(t, 0) != town_totals[t]]
if bad:
    print("WARNING: barangays do not add up to the town total for:")
    for t, want, got in bad:
        print(f"  {t}: PSA total {want:,}, barangays add up to {got:,}")
print(f"Province total (PSA): {province_total:,} | barangays add up to: {pop['population_2020'].sum():,}")

pop.to_csv(config.POPULATION_FILE, index=False)
print(f"Saved {config.POPULATION_FILE.relative_to(config.ROOT)}")
