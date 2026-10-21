# 02_download_roads.py
# Step 2: download the road network of Negros Oriental from OpenStreetMap.
#
# Output: data/processed/roads.graphml
# This needs internet and can take 5-15 minutes. You only need to run it once.
#
# Run from the project folder:  python scripts/02_download_roads.py

import sys
import time
from pathlib import Path

import osmnx as ox

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

# Keep the 'surface' tag (paved / unpaved) so we can slow down dirt roads when it rains
ox.settings.useful_tags_way = list(ox.settings.useful_tags_way) + ["surface"]
ox.settings.log_console = True
ox.settings.requests_timeout = 300  # give a busy server more time to answer (seconds)

# The free OpenStreetMap road server (Overpass) is sometimes overloaded and answers
# "502/504 Gateway Timeout". Its own advice: wait, then retry with longer and longer waits.
# Pieces that already downloaded are saved in the cache/ folder, so each retry only
# fetches what is still missing.
WAIT_MINUTES = [2, 4, 8, 16, 32, 60]  # waits between tries (about 2 hours in total)

print(f"Downloading roads for: {config.PLACE_NAME}")
for attempt in range(len(WAIT_MINUTES) + 1):
    try:
        G = ox.graph_from_place(
            config.PLACE_NAME,
            custom_filter=config.ROAD_FILTER,
            simplify=True,
            retain_all=True,  # keep small road pieces too (e.g. on islands), not only the biggest network
        )
        break  # success
    except Exception as e:  # usually "server busy" or a timeout
        print(f"\nTry {attempt + 1} failed: {str(e).splitlines()[0][:150]}")
        if attempt == len(WAIT_MINUTES):
            sys.exit("Still failing after all retries. Try again later (saved pieces are kept in cache/).")
        wait = WAIT_MINUTES[attempt]
        print(f"Waiting {wait} min before trying again...")
        time.sleep(wait * 60)

print(f"Done: {len(G.nodes):,} intersections and {len(G.edges):,} road segments.")

config.PROCESSED.mkdir(parents=True, exist_ok=True)
ox.save_graphml(G, config.PROCESSED / "roads.graphml")
print("Saved data/processed/roads.graphml")

# Quick check picture (optional): opens a window with the road map
# fig, ax = ox.plot_graph(G, node_size=0, edge_linewidth=0.3)
