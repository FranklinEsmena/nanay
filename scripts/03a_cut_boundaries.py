# 03a_cut_boundaries.py
# Step 3a (run once, BEFORE step 3): cut the Negros Oriental barangays out of the
# national boundary file, so step 3 does not have to read 360 MB every time.
#
# Input : data/raw/hdx_boundaries/phl_admin_boundaries.gdb.zip
#         "Philippines - Subnational Administrative Boundaries" (NAMRIA / PSA, via OCHA on HDX)
#         https://data.humdata.org/dataset/cod-ab-phl   (download the .gdb.zip, about 360 MB)
# Output: data/raw/hdx_boundaries/negros_oriental_barangays.gpkg
#
# Run from the project folder:  python scripts/03a_cut_boundaries.py

import sys
from pathlib import Path

import pyogrio

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

SOURCE = config.RAW / "hdx_boundaries" / "phl_admin_boundaries.gdb.zip"
LAYER = "phl_admin4"  # admin level 4 = barangays

if not SOURCE.exists():
    sys.exit(f"Download the HDX boundary file first and save it as {SOURCE}")

# Read only the Negros Oriental rows (the filter runs inside the file, which is much faster)
gdf = pyogrio.read_dataframe(
    f"zip://{SOURCE}!phl_admin_boundaries.gdb",
    layer=LAYER,
    where="adm2_name = 'Negros Oriental'",
    columns=["adm4_name", "adm4_pcode", "adm3_name", "adm3_pcode", "adm2_name", "adm2_pcode",
             "valid_on", "version", "area_sqkm"],
)
print(f"Negros Oriental barangays: {len(gdf)} in {gdf['adm3_name'].nunique()} cities/municipalities")
if len(gdf) == 0:
    sys.exit("No rows found: check the province name in the file (column adm2_name).")

gdf.to_file(config.BOUNDARY_FILE, driver="GPKG")
print(f"Saved {config.BOUNDARY_FILE.relative_to(config.ROOT)}")
