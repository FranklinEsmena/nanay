# 03c_find_border_towns.py
# Step 3c (run once): which Negros Oriental towns share a land border with Negros Occidental?
#
# Why: our road network stops at the province border, so the model never sends anyone to a
# hospital in Negros Occidental. People in border towns may really go there, so their travel
# times (and gaps) may be overstated. The app warns about these towns.
#
# Input : data/raw/hdx_boundaries/phl_admin_boundaries.gdb.zip  (same HDX file as step 3a)
# Output: data/processed/border_towns.csv   (one column: municipality, same names as barangays.csv)
#
# Run from the project folder:  python scripts/03c_find_border_towns.py

import sys
from pathlib import Path

import pandas as pd
import pyogrio

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
import helpers

SOURCE = config.RAW / "hdx_boundaries" / "phl_admin_boundaries.gdb.zip"
if not SOURCE.exists():
    sys.exit(f"Download the HDX boundary file first and save it as {SOURCE}")
gdb = f"zip://{SOURCE}!phl_admin_boundaries.gdb"

# Negros Occidental as one shape (admin level 2 = province)
occidental = pyogrio.read_dataframe(gdb, layer="phl_admin2", where="adm2_name = 'Negros Occidental'")
if len(occidental) == 0:
    sys.exit("Negros Occidental not found: check the province name in the file (column adm2_name).")
occidental = occidental.to_crs(32651).union_all()  # 32651 = metres

# Negros Oriental towns (admin level 3 = city/municipality)
towns = pyogrio.read_dataframe(gdb, layer="phl_admin3", where="adm2_name = 'Negros Oriental'").to_crs(32651)

# A town is a border town if its outline comes within 100 m of Negros Occidental
# (100 m of slack, because two provinces' outlines never line up perfectly)
towns["border"] = towns.geometry.distance(occidental) <= 100
border = sorted(helpers.town_name(n) for n in towns.loc[towns["border"], "adm3_name"])
print(f"Negros Oriental towns bordering Negros Occidental: {len(border)}")
print(", ".join(border))

# Check the names match the ones the app uses (barangays.csv)
known = set(pd.read_csv(config.PROCESSED / "barangays.csv")["municipality"])
unknown = [b for b in border if b not in known]
if unknown:
    sys.exit(f"These names do not match barangays.csv: {unknown}")

pd.DataFrame({"municipality": border}).to_csv(config.PROCESSED / "border_towns.csv", index=False)
print("Saved data/processed/border_towns.csv")
