# app_data.py
# Things BOTH app pages need: loading the data tables, the logo paths,
# and the small "demo" / "data not loaded" messages.

import pandas as pd
import streamlit as st

import config
import helpers

LOGO = config.ROOT / "assets" / "nanay_logo.svg"  # emblem + "NANAY" name
ICON = config.ROOT / "assets" / "nanay_icon.png"  # emblem only, for the browser tab


@st.cache_data
def load_data():
    """Read the tables made by scripts 01-04 (cached so it only loads once)."""
    p = config.PROCESSED
    barangays = pd.read_csv(p / "barangays.csv")
    facilities = pd.read_csv(p / "facilities.csv", dtype={"nhfr_code": str})
    candidates = pd.read_csv(p / "candidates.csv", dtype={"nhfr_code": str})
    dry = pd.read_csv(p / "time_matrix_dry.csv", index_col=0)
    rainy = pd.read_csv(p / "time_matrix_rainy.csv", index_col=0)
    return barangays, facilities, candidates, {"Dry season": dry, "Rainy season": rainy}


@st.cache_data
def load_barangay_shapes():
    """Barangay outlines for the colored map, simplified to about 40 m detail so the page
    stays fast (6.8 MB -> about 0.3 MB). Returns None if there is no outline file
    (e.g. the demo data); the map then shows circles instead."""
    import geopandas as gpd
    path = config.PROCESSED / "barangays.geojson"
    if not path.exists():
        return None
    import shapely
    shapes = gpd.read_file(path)[["barangay_id", "geometry"]]
    shapes["geometry"] = shapes.to_crs(32651).simplify(40).to_crs(4326)  # 32651 = metres
    # round corner points to about 1 m (5 decimals): invisible on screen, much less data to send
    shapes["geometry"] = shapely.set_precision(shapes.geometry.values, grid_size=0.00001)
    return shapes


@st.cache_data
def load_town_points():
    """One point per city/municipality for its name on the map: a point inside the town's
    combined barangay outlines (or the average barangay point, if there are no outlines).
    Returns a table: municipality, lat, lon."""
    barangays = load_data()[0]
    shapes = load_barangay_shapes()
    if shapes is None:
        return barangays.groupby("municipality", as_index=False)[["lat", "lon"]].mean()
    towns = shapes.merge(barangays[["barangay_id", "municipality"]], on="barangay_id").dissolve("municipality")
    points = towns.geometry.representative_point()   # always inside the shape
    return pd.DataFrame({"municipality": towns.index, "lat": points.y.values, "lon": points.x.values})


@st.cache_resource(show_spinner="Loading the road map for routes (first route only, about 15 seconds)...")
def load_roads():
    """The road network (for drawing routes). Loaded once and shared by all users.
    Returns None if roads.graphml is missing."""
    import osmnx as ox
    path = config.PROCESSED / "roads.graphml"
    if not path.exists():
        return None
    G = helpers.add_travel_times(ox.load_graphml(path))
    return ox.convert.to_undirected(G)


def load_or_stop():
    """Load the data, or show a clear message and stop the page if a file is missing."""
    try:
        barangays, facilities, candidates, matrices = load_data()
    except FileNotFoundError as e:
        st.error(f"Missing data file: {e.filename}. Run scripts 01-04 first (see README).")
        st.stop()
    all_places = pd.concat([facilities, candidates]).drop_duplicates("nhfr_code")
    names = dict(zip(all_places["nhfr_code"], all_places["facility_name"]))
    return barangays, facilities, candidates, matrices, names


def demo_banner():
    if config.USE_DEMO_DATA:
        st.warning("DEMO MODE: all roads, barangays and facilities shown here are FAKE test data.")


def load_border_towns():
    """Towns that share a land border with Negros Occidental (made by scripts/03c).
    Empty if the file is missing (e.g. before step 3c was run)."""
    path = config.PROCESSED / "border_towns.csv"
    return set(pd.read_csv(path)["municipality"]) if path.exists() else set()


def load_context_files():
    """The optional KPI files (each is None if missing or still empty)."""
    births = helpers.load_optional_csv(config.BIRTHS_FILE, config.BIRTHS_COLUMNS)
    rainfall = helpers.load_optional_csv(config.RAINFALL_FILE, config.RAINFALL_COLUMNS)
    poverty = helpers.load_optional_csv(config.POVERTY_FILE, config.POVERTY_COLUMNS)
    return births, rainfall, poverty
