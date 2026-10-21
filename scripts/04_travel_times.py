# 04_travel_times.py
# Step 4: travel time (minutes) from every barangay to every facility,
# for the dry season and the rainy season.
#
# Inputs : data/processed/roads.graphml, barangays.csv, facilities.csv, candidates.csv
# Outputs: data/processed/time_matrix_dry.csv    (rows = barangays, columns = facilities)
#          data/processed/time_matrix_rainy.csv
#          data/processed/barangay_snap.csv      (how far each barangay center is from a road)
#
# How a trip is counted:
#   walk from barangay center to nearest road  +  ride along the roads  +  walk to the facility
#
# Run from the project folder:  python scripts/04_travel_times.py

import sys
import time
from pathlib import Path

import networkx as nx
import osmnx as ox
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
import helpers

start = time.time()

# ---- 1. Load data ----
G = ox.load_graphml(config.PROCESSED / "roads.graphml")
G = helpers.add_travel_times(G)
# Treat roads as two-way (in rural areas one-way streets barely matter)
UG = ox.convert.to_undirected(G)
print(f"Road graph: {len(UG.nodes):,} nodes")

barangays = pd.read_csv(config.PROCESSED / "barangays.csv")
facilities = pd.read_csv(config.PROCESSED / "facilities.csv", dtype={"nhfr_code": str})
candidates = pd.read_csv(config.PROCESSED / "candidates.csv", dtype={"nhfr_code": str})
# Every place we might need a time for = current facilities + upgrade candidates
places = pd.concat([facilities, candidates]).drop_duplicates("nhfr_code")
print(f"Barangays: {len(barangays)}, facilities + candidates: {len(places)}")


# ---- 2. Snap points to the nearest road node ----
def snap(df):
    """Find the nearest road node for each point and how far away it is (km)."""
    nodes = ox.distance.nearest_nodes(UG, X=df["lon"].values, Y=df["lat"].values)
    km = []
    for node, lat, lon in zip(nodes, df["lat"], df["lon"]):
        km.append(helpers.haversine_km(lat, lon, UG.nodes[node]["y"], UG.nodes[node]["x"]))
    return list(nodes), km


barangays["node"], barangays["walk_km"] = snap(barangays)
places = places.rename(columns={"latitude": "lat", "longitude": "lon"})
places["node"], places["walk_km"] = snap(places)

# Nobody walks across the sea: if the straight walk from a barangay center to its nearest
# road leaves the land (e.g. Apo Island to the mainland), treat it as "no road connection"
# (it needs a boat). Land = all barangay boundaries joined together. Real data only.
if not config.USE_DEMO_DATA and config.BOUNDARY_FILE.exists():
    from shapely.geometry import LineString
    import geopandas as gpd
    land = gpd.read_file(config.BOUNDARY_FILE).to_crs(32651).union_all().buffer(200)  # metres, 200 m slack
    walks = gpd.GeoSeries(
        [LineString([(lon, lat), (UG.nodes[n]["x"], UG.nodes[n]["y"])])
         for lon, lat, n in zip(barangays["lon"], barangays["lat"], barangays["node"])],
        crs=4326).to_crs(32651)
    over_water = walks.difference(land).length.values > 500  # more than 500 m of the walk is sea
    print(f"Barangays whose walk to a road crosses the sea (need a boat): {over_water.sum()}")
    if over_water.sum() > 0:
        print(barangays.loc[over_water, ["municipality", "barangay"]].to_string(index=False))
    barangays.loc[over_water, "walk_km"] = float("inf")  # counts as farther than MAX_WALK_KM

too_far = barangays["walk_km"] > config.MAX_WALK_KM
print(f"Barangays farther than {config.MAX_WALK_KM} km from any road: {too_far.sum()}")
if too_far.sum() > 0:
    print(barangays.loc[too_far, ["municipality", "barangay", "walk_km"]].to_string(index=False))
barangays[["barangay_id", "municipality", "barangay", "walk_km"]].to_csv(
    config.PROCESSED / "barangay_snap.csv", index=False
)

# ---- 3. One Dijkstra run per facility, per season ----
for season in ["dry", "rainy"]:
    weight = f"time_{season}"
    matrix = pd.DataFrame(index=barangays["barangay_id"])

    for i, fac in places.iterrows():
        # minutes from this facility's road node to every road node
        road_min = helpers.minutes_from(UG, fac["node"], weight)

        times = []
        for _, b in barangays.iterrows():
            if b["walk_km"] > config.MAX_WALK_KM or b["node"] not in road_min:
                times.append(None)  # no road connection (island, or a separate road piece)
            else:
                total = (
                    helpers.walk_minutes(b["walk_km"])
                    + road_min[b["node"]]
                    + helpers.walk_minutes(fac["walk_km"])
                )
                times.append(round(total, 1))
        matrix[fac["nhfr_code"]] = times

    matrix.to_csv(config.PROCESSED / f"time_matrix_{season}.csv")
    print(f"Saved time_matrix_{season}.csv  ({time.time() - start:.0f} s so far)")

print("Done.")
