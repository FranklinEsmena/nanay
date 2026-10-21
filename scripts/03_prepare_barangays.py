# 03_prepare_barangays.py
# Step 3: one point per barangay (a point inside its boundary) + its population.
#
# Inputs : barangay boundaries (HDX) and our PSA 2020 population CSV (see config.py)
# Outputs: data/processed/barangays.csv      (id, names, lat, lon, population)
#          data/processed/barangays.geojson  (boundaries, for the map later)
#
# Run from the project folder:  python scripts/03_prepare_barangays.py

import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
import helpers


def clean_name(name):
    """Make names comparable: 'City of Bais' and 'BAIS CITY' both become 'BAIS'."""
    name = str(name).upper()
    name = name.replace("CITY OF", "").replace("CITY", "")
    name = name.replace("Ñ", "N")
    name = re.sub(r"\(.*?\)", "", name)        # drop text in brackets
    name = re.sub(r"[^A-Z0-9 ]", " ", name)    # drop punctuation
    return " ".join(name.split())


# ---- 1. Boundaries ----
gdf = gpd.read_file(config.BOUNDARY_FILE)
for col in [config.BOUNDARY_PROVINCE_COL, config.BOUNDARY_MUNI_COL, config.BOUNDARY_BRGY_COL]:
    if col not in gdf.columns:
        print("Columns in the boundary file:", list(gdf.columns))
        sys.exit(f"Column '{col}' not found. Update the column names in config.py.")

gdf = gdf[gdf[config.BOUNDARY_PROVINCE_COL].str.upper().str.contains("NEGROS ORIENTAL")].copy()
print(f"Barangay boundaries in Negros Oriental: {len(gdf)}")

gdf = gdf.to_crs(epsg=4326)
# representative_point() is always INSIDE the shape (a centroid can fall outside odd shapes)
points = gdf.geometry.representative_point()
gdf["lat"] = points.y
gdf["lon"] = points.x
gdf["municipality"] = gdf[config.BOUNDARY_MUNI_COL].apply(helpers.town_name)  # e.g. "Bayawan City"
gdf["barangay"] = gdf[config.BOUNDARY_BRGY_COL]
gdf["key"] = gdf["municipality"].apply(clean_name) + "|" + gdf["barangay"].apply(clean_name)

# ---- 2. Population ----
pop = pd.read_csv(config.POPULATION_FILE)
pop["key"] = pop["municipality"].apply(clean_name) + "|" + pop["barangay"].apply(clean_name)
pop = pop.groupby("key", as_index=False)["population_2020"].sum()

merged = gdf.merge(pop, on="key", how="left")
no_pop = merged[merged["population_2020"].isna()]
if len(no_pop) > 0:
    print(f"\n{len(no_pop)} barangays did not match a population row. Fix their names in the CSV:")
    print(no_pop[["municipality", "barangay"]].to_string(index=False))

# ---- 3. Save ----
merged["barangay_id"] = range(1, len(merged) + 1)
merged["population"] = merged["population_2020"]
if config.WOMEN_15_49_SHARE is not None:
    merged["women_15_49"] = (merged["population"] * config.WOMEN_15_49_SHARE).round()

cols = ["barangay_id", "municipality", "barangay", "lat", "lon", "population"]
if "women_15_49" in merged.columns:
    cols.append("women_15_49")

config.PROCESSED.mkdir(parents=True, exist_ok=True)
merged[cols].to_csv(config.PROCESSED / "barangays.csv", index=False)
merged[cols + ["geometry"]].to_file(config.PROCESSED / "barangays.geojson", driver="GeoJSON")
print(f"\nSaved {len(merged)} barangays to data/processed/barangays.csv")
