# 00_make_demo_data.py
# Makes a small FAKE dataset so we can build and test the app before the real data is ready.
# Nothing here is real: fake roads, fake barangays, fake facilities.
# DELETE data/demo/ before the final submission.
#
# Run:  python scripts/00_make_demo_data.py
# Then: set NANAY_DEMO=1
#       python scripts/04_travel_times.py
#       python scripts/05_optimize.py
#       streamlit run app.py

import random
import sys
from pathlib import Path

import networkx as nx
import osmnx as ox
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
import helpers

random.seed(42)
out = config.DEMO
out.mkdir(parents=True, exist_ok=True)

# ---- Fake road grid: 25 x 25 intersections, about 1.1 km apart ----
G = nx.MultiDiGraph(crs="epsg:4326")
N = 25
lat0, lon0, step = 9.20, 122.90, 0.01


def node_id(r, c):
    return r * N + c


for r in range(N):
    for c in range(N):
        G.add_node(node_id(r, c), y=lat0 + r * step, x=lon0 + c * step)

for r in range(N):
    for c in range(N):
        for dr, dc in [(0, 1), (1, 0)]:
            r2, c2 = r + dr, c + dc
            if r2 >= N or c2 >= N:
                continue
            # rows/cols 0 and 12 are a "highway"; the east half is hilly dirt tracks
            if r == 0 or c == 0 or r == 12 or c == 12:
                road, surface = "primary", "paved"
            elif c > 15:
                road, surface = "track", "dirt"
            else:
                road, surface = "unclassified", "paved"
            a, b = node_id(r, c), node_id(r2, c2)
            km = helpers.haversine_km(G.nodes[a]["y"], G.nodes[a]["x"], G.nodes[b]["y"], G.nodes[b]["x"])
            for u, v in [(a, b), (b, a)]:
                G.add_edge(u, v, length=km * 1000, highway=road, surface=surface, osmid=len(G.edges))

# A tiny separate "island" road (not connected to the mainland grid)
G.add_node(9001, y=9.10, x=123.20)
G.add_node(9002, y=9.105, x=123.205)
G.add_edge(9001, 9002, length=700, highway="unclassified", surface="paved", osmid=99999)
G.add_edge(9002, 9001, length=700, highway="unclassified", surface="paved", osmid=99998)

ox.save_graphml(G, out / "roads.graphml")

# ---- Fake barangays ----
rows = []
for i in range(1, 121):
    rows.append({
        "barangay_id": i,
        "municipality": f"Demo Town {1 + (i - 1) // 20}",
        "barangay": f"Demo Barangay {i}",
        "lat": lat0 + random.uniform(0, (N - 1) * step),
        "lon": lon0 + random.uniform(0, (N - 1) * step),
        "population": random.randint(500, 6000),
    })
rows.append({"barangay_id": 121, "municipality": "Demo Town 7", "barangay": "Demo Island",
             "lat": 9.102, "lon": 123.202, "population": 900})
pd.DataFrame(rows).to_csv(out / "barangays.csv", index=False)

# ---- Fake facilities ----
fac = [
    ("D001", "DEMO PROVINCIAL HOSPITAL", "Hospital", "CEmONC", 9.21, 122.91),
    ("D002", "DEMO DISTRICT HOSPITAL", "Hospital", "CEmONC", 9.42, 123.02),
    ("D003", "DEMO INFIRMARY", "Infirmary", "BEmONC", 9.30, 123.05),
    ("D004", "DEMO BIRTHING HOME A", "Birthing Home", "birthing", 9.25, 123.00),
    ("D005", "DEMO BIRTHING HOME B", "Birthing Home", "birthing", 9.40, 123.10),
]
cand = [
    ("D101", "DEMO RHU EAST", "Rural Health Unit", "none", 9.33, 123.11),
    ("D102", "DEMO RHU NORTH-EAST", "Rural Health Unit", "none", 9.40, 123.12),
    ("D103", "DEMO RHU SOUTH-EAST", "Rural Health Unit", "none", 9.25, 123.11),
    ("D104", "DEMO RHU CENTRAL", "Rural Health Unit", "none", 9.31, 123.03),
    ("D003", "DEMO INFIRMARY", "Infirmary", "BEmONC", 9.30, 123.05),
]
cols = ["nhfr_code", "facility_name", "facility_type", "obstetric_level", "latitude", "longitude"]
pd.DataFrame(fac, columns=cols).to_csv(out / "facilities.csv", index=False)
pd.DataFrame(cand, columns=cols).to_csv(out / "candidates.csv", index=False)

# ---- Fake context-KPI files (same columns as the real PSA / PAGASA files) ----
# Births: 3 fake years, with a made-up bump in the later months
births = [{"year": y, "month": m, "registered_births": random.randint(900, 1100) + (150 if m >= 9 else 0)}
          for y in [2021, 2022, 2023] for m in range(1, 13)]
pd.DataFrame(births).to_csv(out / "births_by_month.csv", index=False)

# Rainfall: made-up "dry first half, wet second half" pattern
rain = [{"month": m, "normal_rainfall_mm": (80 if m <= 5 else 260) + random.randint(-20, 20),
         "rainy_days": (7 if m <= 5 else 18) + random.randint(-2, 2)} for m in range(1, 13)]
pd.DataFrame(rain).to_csv(out / "monthly_rainfall.csv", index=False)

# Poverty: one made-up incidence per demo town
towns = sorted({r["municipality"] for r in rows})
poverty = [{"municipality": t, "poverty_incidence_pct": round(random.uniform(10, 50), 1), "year": 2021}
           for t in towns]
pd.DataFrame(poverty).to_csv(out / "poverty_municipal.csv", index=False)

print(f"FAKE demo data written to {out}")
