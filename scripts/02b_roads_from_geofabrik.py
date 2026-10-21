# 02b_roads_from_geofabrik.py
# Step 2 (OFFLINE option): build the Negros Oriental road network from a downloaded
# OpenStreetMap file, instead of asking the online Overpass server (script 02),
# which is often overloaded. Use ONE of the two; both save the same file.
#
# Input : data/raw/geofabrik/philippines-latest.osm.pbf
#           OpenStreetMap data for the whole Philippines, from Geofabrik:
#           https://download.geofabrik.de/asia/philippines-latest.osm.pbf  (about 600 MB)
#         data/raw/hdx_boundaries/negros_oriental_barangays.gpkg  (made by script 03a)
# Output: data/processed/roads.graphml   (same as script 02)
#
# How it works (plain language):
#   1. Draw a box around Negros Oriental (from the barangay boundaries, plus a small margin).
#   2. Read the big file and keep only the roads of the types in config.ROAD_FILTER
#      that touch that box.
#   3. Turn them into a road network, cut it to the province outline, and save it.
#
# Run from the project folder:  python scripts/02b_roads_from_geofabrik.py
# Needs the "osmium" package (in requirements.txt). Takes a few minutes.

import re
import sys
import time
from pathlib import Path

import geopandas as gpd
import osmium
import osmnx as ox

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

PBF = config.RAW / "geofabrik" / "philippines-latest.osm.pbf"
ROADS_OSM = config.RAW / "geofabrik" / "negros_oriental_roads.osm"  # in-between file
MARGIN_KM = 2  # keep roads up to 2 km outside the outline (coastlines are simplified)

for f in [PBF, config.BOUNDARY_FILE]:
    if not f.exists():
        sys.exit(f"Missing {f}. See the README (steps 2 and 3a).")
start = time.time()

# ---- 1. The area we want: Negros Oriental outline + margin ----
barangays = gpd.read_file(config.BOUNDARY_FILE)
province = barangays.to_crs(32651).union_all().buffer(MARGIN_KM * 1000)  # UTM 51N = metres
province = gpd.GeoSeries([province], crs=32651).to_crs(4326).iloc[0]
west, south, east, north = province.bounds
print(f"Box: lat {south:.3f}-{north:.3f}, lon {west:.3f}-{east:.3f}")

# Same road types as script 02, e.g. "trunk|primary|...|track"
road_types = re.search(r'~"(.+?)"', config.ROAD_FILTER).group(1)

# ---- 2a. First pass: which map points (nodes) are inside the box? ----
inside = set()
for node in osmium.FileProcessor(str(PBF), osmium.osm.NODE):
    loc = node.location
    if south <= loc.lat <= north and west <= loc.lon <= east:
        inside.add(node.id)
print(f"Map points inside the box: {len(inside):,}  ({time.time() - start:.0f} s)")

# ---- 2b. Second pass: keep the roads that touch the box ----
# BackReferenceWriter also writes the map points each road needs.
n_roads = 0
with osmium.BackReferenceWriter(str(ROADS_OSM), ref_src=str(PBF), overwrite=True) as writer:
    for way in osmium.FileProcessor(str(PBF), osmium.osm.WAY).with_filter(osmium.filter.KeyFilter("highway")):
        if not re.search(road_types, way.tags.get("highway", "")):
            continue
        if any(n.ref in inside for n in way.nodes):
            writer.add_way(way)
            n_roads += 1
print(f"Roads kept: {n_roads:,}  ({time.time() - start:.0f} s)")

# ---- 3. Road network: build, cut to the province, simplify, save ----
# Keep the 'surface' tag (paved / unpaved) so we can slow down dirt roads when it rains
ox.settings.useful_tags_way = list(ox.settings.useful_tags_way) + ["surface"]
G = ox.graph_from_xml(ROADS_OSM, simplify=False, retain_all=True)
G = ox.truncate.truncate_graph_polygon(G, province, truncate_by_edge=True)
G = ox.simplify_graph(G)
print(f"Done: {len(G.nodes):,} intersections and {len(G.edges):,} road segments.")

config.PROCESSED.mkdir(parents=True, exist_ok=True)
ox.save_graphml(G, config.PROCESSED / "roads.graphml")
print(f"Saved data/processed/roads.graphml  ({time.time() - start:.0f} s in total)")
