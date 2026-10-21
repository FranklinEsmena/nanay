# 01_prepare_facilities.py
# Step 1: check our hand-filled facility list and save a clean copy.
# Blank care levels are filled with the ASSUMPTION by facility type in config.py.
#
# Input : data/manual/facility_capability.csv  (we fill in obstetric_level, latitude, longitude)
# Output: data/processed/facilities.csv
#
# Run from the project folder:  python scripts/01_prepare_facilities.py

import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
import helpers

df = pd.read_csv(config.MANUAL / "facility_capability.csv", dtype=str, keep_default_na=False)
print(f"Read {len(df)} facilities from the manual file.")

# 1. obstetric_level must be one of our allowed words (or blank / 'none')
allowed = config.LEVELS + ["none", ""]
bad_level = df[~df["obstetric_level"].isin(allowed)]
if len(bad_level) > 0:
    print("\nThese rows have a misspelled obstetric_level (allowed: birthing, BEmONC, CEmONC, none):")
    print(bad_level[["nhfr_code", "facility_name", "obstetric_level"]].to_string(index=False))
    sys.exit("Fix the spelling in data/manual/facility_capability.csv and run again.")

# 2. Coordinates must be numbers inside (roughly) Negros Oriental
typed = (df["latitude"].str.strip() != "") | (df["longitude"].str.strip() != "")
df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")

unreadable = df[typed & (df["latitude"].isna() | df["longitude"].isna())]
if len(unreadable) > 0:
    print("\nWARNING: these coordinates are not valid numbers (typo?), so the facility is skipped:")
    print(unreadable[["nhfr_code", "facility_name"]].to_string(index=False))
inside = df["latitude"].between(8.9, 10.6) & df["longitude"].between(122.5, 123.6)
has_coords = df["latitude"].notna() & df["longitude"].notna()

outside = df[has_coords & ~inside]
if len(outside) > 0:
    print("\nWARNING: these coordinates are outside Negros Oriental (maybe lat/long swapped?):")
    print(outside[["nhfr_code", "facility_name", "latitude", "longitude"]].to_string(index=False))

# 3. Care level: the confirmed obstetric_level if the team filled it in, otherwise the
#    ASSUMPTION by facility type from config.py. Also make the stricter scenario column.
df = helpers.assign_levels(df)
n_assumed = (df["level_basis"] != "confirmed").sum()
print(f"\nCare levels: {len(df) - n_assumed} confirmed, {n_assumed} assumed from facility type (config.LEVEL_BY_TYPE)")

# 4. Keep only facilities that are usable: they have a level AND good coordinates
usable = df[df["level"].isin(config.LEVELS) & has_coords & inside].copy()
missing = df[~df.index.isin(usable.index)]

print(f"\nUsable facilities: {len(usable)}")
if len(usable) > 0:
    print(pd.crosstab(usable["level"], usable["level_basis"]).to_string())
    print("Stricter scenario (only government hospitals are CEmONC):",
          usable["level_strict"].value_counts().to_dict())
else:
    print("None yet. Fill in obstetric_level, latitude and longitude in the manual file.")
print(f"\nNot used (level 'none' or no coordinates): {len(missing)}")

# Phone numbers: a number our team typed in a "phone" column of the manual file wins;
# otherwise use the number in the DOH registry (many registry entries are blank).
registry = pd.read_csv(config.RAW / "nhfr_negros_oriental_all_facilities.csv", dtype=str,
                       keep_default_na=False, encoding="utf-8-sig")
reg_phone = dict(zip(registry["nhfr_code"], registry["phone"].str.strip()))
team_phone = df["phone"].str.strip() if "phone" in df.columns else pd.Series("", index=df.index)
df["phone"] = team_phone.where(team_phone != "", df["nhfr_code"].map(reg_phone).fillna(""))
df["phone_source"] = "team"
df.loc[team_phone == "", "phone_source"] = "DOH registry"
df.loc[df["phone"] == "", "phone_source"] = ""
usable = df.loc[usable.index].copy()  # copy the phone columns into the usable table
print(f"Phone numbers: {(usable['phone'] != '').sum()} of {len(usable)} usable facilities")

# The rest of the pipeline reads obstetric_level, so put the level we use there
# (level_strict and level_basis are kept for the app's scenario switch and labels).
usable["obstetric_level"] = usable["level"]

# 5. Warn about coordinates from 01a_suggest_coordinates.py that nobody has checked yet
#    (these points are also used for the upgrade candidates below)
unchecked = df[has_coords & df["coordinate_source"].str.startswith("SUGGESTED")]
if len(unchecked) > 0:
    print(f"\nWARNING: {len(unchecked)} facilities still have UNCHECKED suggested coordinates.")
    print("Check them on a map (data/manual/coordinate_suggestions_review.csv has the links),")
    print("then change coordinate_source to say who checked them and when.")

usable["nhfr_code"] = usable["nhfr_code"].astype(str)
config.PROCESSED.mkdir(parents=True, exist_ok=True)
usable.to_csv(config.PROCESSED / "facilities.csv", index=False)

# Also keep the candidates for the what-if / optimization (facilities that could be upgraded),
# even if their current level is 'none'. They still need coordinates.
cand = df[df["facility_type"].isin(config.CANDIDATE_TYPES) & has_coords & inside].copy()
cand["nhfr_code"] = cand["nhfr_code"].astype(str)
cand["obstetric_level"] = cand["level"]
cand.to_csv(config.PROCESSED / "candidates.csv", index=False)
print(f"Upgrade candidates with coordinates: {len(cand)}")
print("\nSaved data/processed/facilities.csv and data/processed/candidates.csv")
