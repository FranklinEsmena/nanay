# helpers.py
# Small functions shared by the scripts and the Streamlit app.
# Keep these simple: each one does ONE job.

import math
import re

import networkx as nx
import pandas as pd

import config


# ---------------------------------------------------------------
# Facility levels
# ---------------------------------------------------------------
def level_rank(level):
    """Turn a level name into a number: birthing=1, BEmONC=2, CEmONC=3, anything else=0.
    A CEmONC hospital can also do everything a BEmONC or birthing facility can,
    so 'serves level X' means rank >= rank of X."""
    if level in config.LEVELS:
        return config.LEVELS.index(level) + 1
    return 0


def assign_levels(df):
    """Add three columns to the facility table:
       level         care level we use (confirmed value, or assumed from facility type)
       level_strict  same, but private hospitals with an ASSUMED level count one level lower
       level_basis   'confirmed' or 'assumed from facility type'
    A level typed into obstetric_level by the team always wins over the assumption."""
    df = df.copy()
    typed = df["obstetric_level"].fillna("").str.strip()
    confirmed = typed != ""
    by_type = df["facility_type"].map(config.LEVEL_BY_TYPE).fillna("none")

    df["level"] = typed.where(confirmed, by_type)
    df["level_basis"] = confirmed.map({True: "confirmed", False: "assumed from facility type"})

    private_hospital = (df["facility_type"] == "Hospital") & (df["ownership"] == "Private")
    demote = ~confirmed & private_hospital & (df["level"] == "CEmONC")
    df["level_strict"] = df["level"].where(~demote, config.STRICT_PRIVATE_HOSPITAL_LEVEL)
    return df


def use_scenario(facilities, scenario):
    """Return the facility table with obstetric_level set for the chosen scenario
    ('type' = main assumption, 'strict' = only government hospitals are CEmONC)."""
    col = "level_strict" if scenario == "strict" else "level"
    if col not in facilities.columns:   # e.g. the demo data has no scenario columns
        return facilities
    return facilities.assign(obstetric_level=facilities[col])


def facilities_serving(facilities, level, upgraded_codes=()):
    """Return the nhfr_codes of facilities that can provide care at `level`.
    `upgraded_codes` are facilities we pretend were upgraded to `level` (what-if)."""
    need = level_rank(level)
    ok = facilities[facilities["obstetric_level"].apply(level_rank) >= need]["nhfr_code"].tolist()
    return list(set(ok) | set(upgraded_codes))


# ---------------------------------------------------------------
# Distances and road speeds
# ---------------------------------------------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    """Straight-line distance in km between two points on Earth."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def first_value(x):
    """OSM tags can be a list (e.g. ['primary', 'secondary']). Take the first one."""
    if isinstance(x, list):
        return x[0]
    return x


def add_travel_times(G):
    """Add two edge attributes to the road graph, in MINUTES:
       time_dry   = length / dry speed
       time_rainy = length / (dry speed x rainy factor)"""
    for u, v, k, data in G.edges(keys=True, data=True):
        road = str(first_value(data.get("highway", ""))).replace("_link", "")
        speed = config.DRY_SPEEDS_KMH.get(road, config.DEFAULT_SPEED_KMH)

        rainy_factor = config.RAINY_FACTOR.get(road, 0.8)
        surface = str(first_value(data.get("surface", "")))
        if surface in ["unpaved", "gravel", "dirt", "ground", "mud", "earth", "sand"]:
            rainy_factor = rainy_factor * config.UNPAVED_RAINY_FACTOR

        km = data.get("length", 0) / 1000
        data["time_dry"] = km / speed * 60
        data["time_rainy"] = km / (speed * rainy_factor) * 60
    return G


def walk_minutes(km):
    """Minutes to walk `km` kilometers (from a barangay center to the nearest road)."""
    return km / config.WALK_SPEED_KMH * 60


# ---------------------------------------------------------------
# Access calculations (work on the travel-time matrix, no map needed)
# ---------------------------------------------------------------
def nearest_facility(matrix, codes):
    """matrix: rows = barangay_id, columns = nhfr_code (as text), values = minutes.
    Returns a table with the fastest minutes and the code of that facility,
    using only the facilities in `codes`."""
    cols = [str(c) for c in codes if str(c) in matrix.columns]
    if len(cols) == 0:
        return pd.DataFrame({"minutes": math.nan, "nearest_code": None}, index=matrix.index)
    sub = matrix[cols]
    out = pd.DataFrame(index=matrix.index)
    out["minutes"] = sub.min(axis=1)
    # idxmax/idxmin fail on all-NaN rows, so fill those with a placeholder first
    out["nearest_code"] = sub.fillna(1e9).idxmin(axis=1)
    out.loc[out["minutes"].isna(), "nearest_code"] = None
    return out


def access_table(barangays, facilities, matrix, level, threshold, upgraded_codes=()):
    """Main result table: one row per barangay with travel minutes to the nearest
    facility at `level`, and whether it is within `threshold` minutes."""
    codes = facilities_serving(facilities, level, upgraded_codes)
    near = nearest_facility(matrix, codes)
    t = barangays.set_index("barangay_id").join(near)
    names = facilities.set_index(facilities["nhfr_code"].astype(str))["facility_name"]
    t["nearest_facility"] = t["nearest_code"].map(names)
    t["within"] = t["minutes"] <= threshold
    t["unreachable"] = t["minutes"].isna()
    return t.reset_index()


def critical_facilities(barangays, facilities, matrix, level, threshold, weight_col):
    """How much each facility matters: for every facility at `level`, how many people would
    no longer have ANY facility at that level within `threshold` minutes if it closed.
    Returns a table sorted from most to least critical."""
    base = access_table(barangays, facilities, matrix, level, threshold)
    rows = []
    for code in facilities_serving(facilities, level):
        without = facilities[facilities["nhfr_code"].astype(str) != str(code)]
        t = access_table(barangays, without, matrix, level, threshold)
        lost = base.loc[base["within"] & ~t["within"], weight_col].sum()
        rows.append({"nhfr_code": str(code), "people_losing_access": lost})
    out = pd.DataFrame(rows, columns=["nhfr_code", "people_losing_access"])
    return out.sort_values("people_losing_access", ascending=False).reset_index(drop=True)


def coverage_summary(table, weight_col):
    """Headline numbers for the dashboard."""
    total = table[weight_col].sum()
    covered = table.loc[table["within"], weight_col].sum()
    return {
        "total": total,
        "covered": covered,
        "not_covered": total - covered,
        "pct_covered": 100 * covered / total if total > 0 else 0,
        "barangays_beyond": int((~table["within"]).sum()),
        "barangays_unreachable": int(table["unreachable"].sum()),
    }


def weight_column(barangays):
    """Use women 15-49 if we have the share from PSA, otherwise total population."""
    if config.WOMEN_15_49_SHARE is not None and "women_15_49" in barangays.columns:
        return "women_15_49", "women aged 15-49"
    return "population", "people (all ages)"


def travel_band(minutes, threshold=None):
    """Group minutes into the map's color bands, RELATIVE to the time limit:
    'near' = up to half the limit, 'mid' = up to the limit, 'far' = over it, 'none' = no road.
    (With the usual 120-min limit: under 1 h / 1-2 h / over 2 h.)"""
    threshold = threshold or config.THRESHOLD_MIN
    if pd.isna(minutes):
        return "none"
    if minutes <= threshold / 2:
        return "near"
    if minutes <= threshold:
        return "mid"
    return "far"


def minutes_text(m):
    """90 -> '90 min', 120 -> '2 h', 45 -> '45 min' (whole hours read better as hours)."""
    return f"{int(m // 60)} h" if m % 60 == 0 else f"{int(m)} min"


def band_labels(threshold=None):
    """Short legend labels for the bands, e.g. limit 90 -> under 45 min / 45 min–90 min / ..."""
    threshold = threshold or config.THRESHOLD_MIN
    half, full = minutes_text(threshold / 2), minutes_text(threshold)
    return {"near": f"under {half}", "mid": f"{half}–{full}", "far": f"over {full}", "none": "no road"}


# Light-to-dark single teal ramp from the logo (longer trip = darker), gray for "no road".
# Checked for color-blind safety (simulated red-green color blindness): every pair stays
# clearly different (OKLab difference >= 14, target >= 8; normal vision >= 15).
BAND_COLORS = {
    "near": "#7fd1d5",
    "mid": "#02a6ad",
    "far": "#034649",
    "none": "#696969",
}


# ---------------------------------------------------------------
# Context KPIs (dashboard cards)
# ---------------------------------------------------------------
def load_optional_csv(path, columns):
    """Read a KPI input file. Returns None (instead of crashing) if the file is
    missing, has no rows yet, or lacks one of the expected columns."""
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return None
    if len(df) == 0 or any(c not in df.columns for c in columns):
        return None
    return df


def seasonal_demand(births, month):
    """Average registered births in `month` (1-12) over all years in the file,
    compared with the average month. Returns None if that month has no data."""
    b = births.dropna(subset=["registered_births"])
    per_month = b.groupby("month")["registered_births"].mean()
    if month not in per_month.index:
        return None
    average_month = per_month.mean()
    this_month = per_month[month]
    return {
        "month_avg": this_month,
        "average_month": average_month,
        "pct_vs_average": 100 * (this_month - average_month) / average_month,
        "years": b["year"].nunique(),
    }


def month_weather(rainfall, month, rainy_threshold_mm):
    """Normal rainfall and rainy days for `month` (1-12), and whether it counts
    as a rainy-season month (rainfall >= threshold). None if the month is missing."""
    row = rainfall[rainfall["month"] == month]
    if len(row) == 0:
        return None
    mm = float(row["normal_rainfall_mm"].iloc[0])
    return {
        "rain_mm": mm,
        "rainy_days": float(row["rainy_days"].iloc[0]),
        "is_rainy": mm >= rainy_threshold_mm,
    }


def backup_coverage(table, matrix, codes, threshold, weight_col):
    """% of people with 2 OR MORE facilities (in `codes`) within `threshold` minutes.
    Plain idea: if the nearest facility is closed or full, is there another one in reach?"""
    cols = [str(c) for c in codes if str(c) in matrix.columns]
    n_in_reach = (matrix[cols] <= threshold).sum(axis=1)  # "no road" (NaN) counts as not in reach
    people = table.set_index("barangay_id")[weight_col].fillna(0)
    n_in_reach = n_in_reach.reindex(people.index).fillna(0)
    total = people.sum()
    return 100 * people[n_in_reach >= 2].sum() / total if total > 0 else 0


def town_name(name):
    """One display style for every city/municipality:
    'City of Bayawan (Tulong)' -> 'Bayawan City', 'CITY OF DUMAGUETE' -> 'Dumaguete City',
    'Dumaguete City (Capital)' -> 'Dumaguete City', 'Amlan (Ayuquitan)' -> 'Amlan'."""
    name = re.sub(r"\s*\(.*?\)", "", str(name)).strip()   # drop old/alternate names in brackets
    if name.isupper():                                      # registry style: ALL CAPITALS
        name = name.title()
    match = re.match(r"(?i)city of (.+)", name)
    if match:
        name = f"{match.group(1)} City"
    return name


# Short forms in facility names that must stay in capitals (Python's .title() would turn
# "RHU" into "Rhu"): RHU = rural health unit, BHS = barangay health station, IMAP = the
# midwives' association, ACE / SUMC / NJ / GPC / CDV / FBD = parts of facility names.
KEEP_CAPITALS = {"RHU", "BHS", "CHO", "IMAP", "ACE", "SUMC", "NJ", "GPC", "CDV", "FBD", "BRGY"}


def facility_name(name):
    """Registry names are ALL CAPITALS; show them with normal capitals but keep short forms:
    'MABINAY RHU 1 BIRTHING FACILITY' -> 'Mabinay RHU 1 Birthing Facility'."""
    words = str(name).title().split(" ")
    return " ".join(w.upper() if w.strip("().,-").upper() in KEEP_CAPITALS else w for w in words)


def simple_place_name(name):
    """Make municipality names comparable across files:
    'CITY OF BAIS', 'Bais City' -> 'BAIS';  'Sta. Catalina' -> 'SANTA CATALINA'."""
    name = str(name).upper()
    name = re.sub(r"\(.*?\)", " ", name)       # drop notes like "(Capital)"
    name = name.replace("STA.", "SANTA").replace("STO.", "SANTO")
    name = re.sub(r"^CITY OF |\bCITY\b", " ", name)
    name = re.sub(r"[^A-Z ]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def equity_gap(table, poverty, weight_col, group_share):
    """Coverage of the poorest vs. the least-poor municipalities.
    Uses the latest year in the poverty file. Groups = top / bottom `group_share`
    of matched municipalities ranked by poverty incidence.
    Returns None if fewer than 2 municipalities could be matched."""
    pov = poverty[poverty["year"] == poverty["year"].max()].copy()
    pov["key"] = pov["municipality"].apply(simple_place_name)

    t = table.copy()
    t["key"] = t["municipality"].apply(simple_place_name)
    t["people"] = t[weight_col].fillna(0)
    t["people_covered"] = t["people"] * t["within"]
    by_muni = t.groupby("key")[["people", "people_covered"]].sum().reset_index()

    merged = by_muni.merge(pov[["key", "poverty_incidence_pct"]], on="key")
    unmatched = sorted(set(by_muni["key"]) - set(merged["key"]))
    if len(merged) < 2:
        return None

    merged = merged.sort_values("poverty_incidence_pct", ascending=False)
    k = max(1, round(len(merged) * group_share))
    poorest, least_poor = merged.head(k), merged.tail(k)

    def pct(group):
        return 100 * group["people_covered"].sum() / group["people"].sum() if group["people"].sum() > 0 else 0

    return {
        "poorest_pct": pct(poorest),
        "least_poor_pct": pct(least_poor),
        "gap_pts": pct(least_poor) - pct(poorest),  # positive = poorest towns have LESS access
        "n_each": k,
        "n_matched": len(merged),
        "unmatched": unmatched,
        "year": int(pov["year"].max()),
    }


# ---------------------------------------------------------------
# Maximal Covering Location Problem (MCLP)
# ---------------------------------------------------------------
def town_summary(table_dry, table_rainy, weight_col):
    """One row per city/municipality: the share of people within 1 hour and within 2 hours
    of care (dry and rainy season), the middle barangay's travel time (median), and how many
    people live more than 2 hours away in the rainy season. Barangays with no road connection
    count as "not within" (their minutes are blank)."""
    rows = []
    for town, dry in table_dry.groupby("municipality"):
        rainy = table_rainy[table_rainy["municipality"] == town]
        people = dry[weight_col].sum()

        def share(t, minutes):
            return round(100 * t.loc[t["minutes"] <= minutes, weight_col].sum() / people, 1) if people > 0 else 0.0

        rows.append({
            "municipality": town, "people": people,
            "pct_1h_dry": share(dry, 60), "pct_1h_rainy": share(rainy, 60),
            "pct_2h_dry": share(dry, 120), "pct_2h_rainy": share(rainy, 120),
            "median_min_dry": round(dry["minutes"].median(), 0),
            "median_min_rainy": round(rainy["minutes"].median(), 0),
            "beyond_2h_rainy": people - rainy.loc[rainy["minutes"] <= 120, weight_col].sum(),
        })
    return pd.DataFrame(rows).sort_values("pct_2h_rainy").reset_index(drop=True)


def sensitivity_range(barangays, facilities, matrix, level, threshold, weight_col, change,
                      upgraded_codes=()):
    """How many people would be beyond the time limit if ALL our assumed speeds were
    `change` (0.20 = 20%) slower, or faster.
    Every part of a trip is distance / speed, so 20% slower speeds make every trip exactly
    1 / 0.8 = 1.25 times longer (the fastest road stays the same road): no need to
    recompute routes, we just multiply the travel-time table."""
    out = {}
    for name, factor in [("slower", 1 / (1 - change)), ("faster", 1 / (1 + change))]:
        t = access_table(barangays, facilities, matrix * factor, level, threshold, upgraded_codes)
        out[name] = coverage_summary(t, weight_col)["not_covered"]
    return out


def best_sites(table, matrix, candidate_codes, threshold, n_sites, weight_col):
    """Choose `n_sites` facilities to upgrade so that the MOST people who are
    currently beyond `threshold` minutes become covered.

    Plain idea:   pick sites (yes/no) -> a barangay counts as newly covered
                  if at least one picked site is within the threshold.
    Math name:    Maximal Covering Location Problem (Church & ReVelle, 1974),
                  solved as an integer linear program with PuLP.
    Returns (list of chosen codes, people newly covered)."""
    import pulp

    not_covered = table[~table["within"]]
    cands = [str(c) for c in candidate_codes if str(c) in matrix.columns]
    if len(not_covered) == 0 or len(cands) == 0:
        return [], 0

    sub = matrix.loc[not_covered["barangay_id"], cands]
    reach = sub <= threshold  # True if candidate j would cover barangay i
    weights = not_covered.set_index("barangay_id")[weight_col].fillna(0)

    model = pulp.LpProblem("NANAY_MCLP", pulp.LpMaximize)
    x = {j: pulp.LpVariable(f"site_{j}", cat="Binary") for j in cands}            # pick site j?
    y = {i: pulp.LpVariable(f"covered_{i}", cat="Binary") for i in reach.index}   # barangay i covered?

    model += pulp.lpSum(weights[i] * y[i] for i in reach.index)       # maximize people covered
    model += pulp.lpSum(x.values()) == min(n_sites, len(cands))       # exactly n sites
    for i in reach.index:
        covering = [x[j] for j in cands if reach.at[i, j]]
        model += y[i] <= pulp.lpSum(covering)                         # covered only if a picked site reaches it

    model.solve(pulp.PULP_CBC_CMD(msg=False))
    chosen = [j for j in cands if x[j].value() is not None and x[j].value() > 0.5]
    gain = sum(weights[i] for i in reach.index if y[i].value() is not None and y[i].value() > 0.5)
    return chosen, gain


# ---------------------------------------------------------------
# Road network routing
# ---------------------------------------------------------------
def route_points(G_undirected, source_node, target_node, weight):
    """The fastest road path between two road nodes, as a list of (lat, lon) points
    that follow the road's real shape (so it can be drawn on the map).
    Returns [] if the two nodes are not connected."""
    try:
        nodes = nx.shortest_path(G_undirected, source_node, target_node, weight=weight)
    except nx.NetworkXNoPath:
        return []
    points = [(G_undirected.nodes[nodes[0]]["y"], G_undirected.nodes[nodes[0]]["x"])]
    for u, v in zip(nodes[:-1], nodes[1:]):
        # between two nodes there can be several roads: take the fastest one
        edge = min(G_undirected[u][v].values(), key=lambda d: d.get(weight, math.inf))
        if "geometry" in edge:
            xy = list(edge["geometry"].coords)  # (lon, lat) pairs along the curve
            # the stored curve may run v -> u; flip it so it starts at u
            ux, uy = G_undirected.nodes[u]["x"], G_undirected.nodes[u]["y"]
            if (xy[0][0] - ux) ** 2 + (xy[0][1] - uy) ** 2 > (xy[-1][0] - ux) ** 2 + (xy[-1][1] - uy) ** 2:
                xy = xy[::-1]
            points += [(lat, lon) for lon, lat in xy[1:]]
        else:
            points.append((G_undirected.nodes[v]["y"], G_undirected.nodes[v]["x"]))
    return points


def minutes_from(G_undirected, source_node, weight):
    """Fastest travel time (minutes) from one road node to every other road node.
    Dijkstra's algorithm = always expand the closest unvisited place first."""
    return nx.single_source_dijkstra_path_length(G_undirected, source_node, weight=weight)
