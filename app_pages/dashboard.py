# app_pages/dashboard.py
# Page 1 of the app: the planning dashboard.
# Layout:  ONE control panel on the left (every choice lives there)
#          + a row of key-number cards, then a BIG map (barangays as colored areas)
#          + folded sections below: barangay ranking, about the data.
# Explanations live in hover tooltips and "?" icons, so the page itself stays calm.

import calendar
import datetime
import html
import json

import altair as alt
import folium
import osmnx as ox
import pandas as pd
import pydeck as pdk
import streamlit as st
from branca.element import MacroElement, Template
from folium.plugins import MarkerCluster, PolyLineTextPath
from streamlit_folium import st_folium

import app_data
import config
import helpers

MAP_HEIGHT = 640   # px; starting height only: the CSS below then fits the map to the screen height
PANEL_WIDTH = 270  # px

# ---------------------------------------------------------------
# Page style (the only custom CSS).
#  - Wide screens: the panel floats on the left and stays put while scrolling,
#    and the numbers strip floats on the top-left corner of the map.
#  - Narrow screens (phones): both simply sit in the normal page flow.
# ---------------------------------------------------------------
st.html(f"""
<style>
  .st-key-controls {{
    background: #ffffff; border-radius: 16px;
    box-shadow: 0 4px 18px rgba(30, 43, 43, 0.12); padding: 0.75rem 1.1rem;
    gap: 0.4rem !important;    /* tighter spacing so the whole panel fits on a laptop screen */
  }}
  .st-key-controls p {{ margin-bottom: 0; }}
  /* small grey text: a little bigger and darker so it reads well on projectors and in the video */
  [data-testid="stCaptionContainer"] {{ font-size: 0.88rem; color: #3d4d4d; }}
  /* less empty space above the title, so the map starts higher */
  [data-testid="stMainBlockContainer"] {{ padding-top: 3.8rem; }}
  @media (min-width: 992px) {{
    .st-key-controls {{
      position: fixed; top: 4.2rem; left: 1rem; z-index: 999;
      width: {PANEL_WIDTH}px; max-height: calc(100vh - 5.2rem); overflow-y: auto;
    }}
    [data-testid="stMainBlockContainer"] {{ padding-left: calc({PANEL_WIDTH}px + 2.5rem); }}
  }}
  /* The map grows or shrinks with the screen height, so on a laptop the whole map fits
     on screen without scrolling (at least 380 px tall, at most 820 px). Works for 2D and 3D. */
  iframe[title="streamlit_folium.st_folium"], [data-testid="stDeckGlJsonChart"] {{
    height: clamp(380px, calc(100vh - 360px), 820px) !important;
  }}
  /* the map's own full-screen button (see draw_2d) marks the frame data-expanded="1":
     it then covers the whole window, above the panel and the top bar */
  iframe[title="streamlit_folium.st_folium"][data-expanded="1"] {{
    position: fixed !important; top: 0; left: 0; width: 100vw !important; height: 100vh !important;
    z-index: 1000000; background: #ffffff;
  }}
  /* The three result tiles above the map: white cards like the control panel, same height */
  [class*="st-key-tile_"] {{
    background: #ffffff; border-radius: 12px; box-shadow: 0 2px 10px rgba(30, 43, 43, 0.08);
    padding: 0.65rem 0.95rem; height: 100%; gap: 0.25rem !important;
  }}
  /* no paragraph gaps inside a tile (and undo Streamlit's matching -16px pull-up, or lines overlap) */
  [class*="st-key-tile_"] p {{ margin-bottom: 0; }}
  [class*="st-key-tile_"] [data-testid="stMarkdownContainer"] {{ margin-bottom: 0; }}
  /* every column that holds a tile stretches it to the tallest tile, so all three line up */
  [data-testid="stColumn"]:has([class*="st-key-tile_"]) [data-testid="stLayoutWrapper"] {{ flex: 1 1 auto; }}
  .tile-label, .tile-number, .tile-text, .tile-small {{ display: block; }}
  /* the "Show on map" link-style button in tile 3: no extra height */
  .st-key-tile_show button, .st-key-tile_remove button {{ min-height: 0; padding: 0.1rem 0; color: #047878; }}
  .tile-label {{ font-size: 0.82rem; color: #3d4d4d; }}
  .tile-number {{ font-size: 1.8rem; font-weight: 700; line-height: 1.15; color: #1e2b2b; }}
  .tile-side {{ font-size: 0.82rem; color: #3d4d4d; font-weight: 400; margin-left: 0.4rem; }}
  .tile-text {{ font-size: 0.85rem; color: #3d4d4d; line-height: 1.4; }}
  .tile-small {{ font-size: 0.78rem; color: #5a6b6b; }}
  .tile-bar {{ display: flex; height: 10px; border-radius: 3px; overflow: hidden; margin: 0.35rem 0 0.25rem; }}
  .tile-key {{ display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 4px; }}
</style>
""")

barangays, facilities_all, candidates, matrices, names = app_data.load_or_stop()
births, rainfall, poverty = app_data.load_context_files()
border_towns = app_data.load_border_towns()  # towns next to Negros Occidental (scripts/03c)
weight_col, weight_label = helpers.weight_column(barangays)

# Plain-language names for each level (plain words first, technical term in brackets).
# A higher level can also do everything a lower one does, so "birthing" = ANY level.
LEVEL_CHOICES = {"CEmONC": "C-section & blood (CEmONC)",
                 "BEmONC": "Basic emergency (BEmONC)",
                 "birthing": "Any place to give birth"}
FACILITY_A = {"CEmONC": "a hospital that can do an emergency C-section and give blood (CEmONC)",
              "BEmONC": "a facility with at least basic emergency care (BEmONC)",
              "birthing": "any place to give birth"}
FACILITY_ONE = {"CEmONC": "C-section & blood hospital (CEmONC)",
                "BEmONC": "basic emergency care (BEmONC)",
                "birthing": "place to give birth"}
FACILITIES_MANY = {"CEmONC": "C-section & blood hospitals (CEmONC)",
                   "BEmONC": "facilities with basic emergency care (BEmONC)",
                   "birthing": "places to give birth"}
PIN_NAME = {"CEmONC": "C-section & blood (CEmONC)",
            "BEmONC": "Basic emergency care (BEmONC)",
            "birthing": "Normal births (birthing home)"}
# Very short names for the map legends (the full names are in tooltips and the panel)
SHORT_PIN = {"CEmONC": "C-section & blood", "BEmONC": "Basic emergency", "birthing": "Birthing home"}
NO_ROUTE = -1  # the "No route" choice in "Show route from" (barangay ids start at 1)


def suggest_best():
    """Button callback: find the best facility(ies) to upgrade FOR THE AREA YOU SELECTED and put
    them on the map. Uses the same search as tile 3 and the Where to upgrade tab, so all three agree.
    (The chosen site may be outside the area, if that is what brings its people closest to care.)"""
    n = st.session_state.get("n_suggest", 1)
    best = best_sites_cached(level, threshold, season, level_scenario, tuple(shown_ids), weight_col)[n - 1]
    if best["gain"] <= 0:
        st.toast("No upgrade brings more people within the time limit in the selected area.")
        return
    st.session_state["upgrades"] = list(best["sites"])
    st.session_state["suggestion"] = {"sites": list(best["sites"]), "gain": best["gain"], "settings": settings}


def show_upgrade_set(sites, gain):
    """Button callback (Where to upgrade tab): put one suggested set of upgrades on the map."""
    st.session_state["upgrades"] = list(sites)
    st.session_state["suggestion"] = {"sites": list(sites), "gain": gain, "settings": settings}
    st.toast("⭐ Shown on the map above (orange stars).")


def clear_where():
    """Button callback: forget the chosen towns, barangays and route (back to the whole province)."""
    st.session_state["towns"] = []
    st.session_state["brgy_filter"] = []
    st.session_state["route_from"] = NO_ROUTE


def clear_upgrades():
    st.session_state["upgrades"] = []
    st.session_state.pop("suggestion", None)


# ---------------------------------------------------------------
# The ONE control panel: what to measure, where to look, view, upgrades
# ---------------------------------------------------------------
with st.container(key="controls"):
    # centered full logo WITH the tagline, plus a little space below it
    # (a plain image from static/, because st.image always sits on the left)
    st.markdown("<div style='text-align:center;margin-bottom:0.6rem'>"
                "<img src='/app/static/nanay_logo_full.svg' width='120' alt='NANAY logo'></div>",
                unsafe_allow_html=True)

    # Every control has a key, so app.py can keep its value when you switch pages.
    # Starting values are set once here (not in the widgets), as Streamlit expects for kept values.
    for k, v in {"level": "CEmONC", "threshold": config.THRESHOLD_MIN, "towns": [], "brgy_filter": [],
                 "map_mode": "2D", "level_scenario": config.DEFAULT_LEVEL_SCENARIO, "upgrades": []}.items():
        st.session_state.setdefault(k, v)

    st.markdown("<span class='brand-heading'>What to measure</span>", unsafe_allow_html=True)
    level = st.selectbox(
        "Level of care", list(LEVEL_CHOICES), format_func=LEVEL_CHOICES.get, key="level",
        help="C-section & blood (CEmONC): a hospital that can do an emergency caesarean "
             "section and give blood.  \n"
             "Basic emergency care (BEmONC): can treat common emergencies like heavy bleeding "
             "or seizures, but cannot operate. Hospitals count too.  \n"
             "Any place to give birth: the nearest facility of any level, including birthing "
             "homes for normal deliveries.  \n"
             "Rural health units count only if they also hold a birthing-home licence (see About the data).",
    )
    # Season is always visible. "Month" only appears once there is monthly data
    # (rainfall or births) behind it; without data it would change nothing.
    month = None
    if rainfall is not None or births is not None:
        month = st.selectbox("Month", range(1, 13), index=datetime.date.today().month - 1,
                             format_func=lambda m: calendar.month_name[m])
    season_options = (["Auto (from month)"] if rainfall is not None else []) + ["Rainy", "Dry"]
    if st.session_state.get("season_choice") not in season_options:
        st.session_state["season_choice"] = season_options[0]
    season_choice = st.radio(
        "Season", season_options, horizontal=True, key="season_choice",
        help="Rainy season: roads are slower, dirt roads the most (assumed slowdowns; see About the data). "
             "This is where most gaps appear."
             + (f" Auto: a month with {config.RAINY_MONTH_MM_THRESHOLD} mm or more normal rainfall "
                f"counts as rainy (our assumption)." if rainfall is not None else ""),
    )
    threshold = st.slider("Time limit (minutes)", 30, 180, step=15, key="threshold",
                          help="2 hours is the global benchmark for timely access to "
                               "caesarean section (Meara et al., 2015).")
    BAND_LABELS = helpers.band_labels(threshold)  # map colors follow the time limit
    facility_a, facility_one = FACILITY_A[level], FACILITY_ONE[level]
    facilities_many = FACILITIES_MANY[level]

    # Heading, plus a "Clear all" button on the right while any place or route is chosen
    head_col, clear_col = st.columns([3, 2], vertical_alignment="center")
    head_col.markdown("<span class='brand-heading'>Where to look</span>", unsafe_allow_html=True)
    if (st.session_state.get("towns") or st.session_state.get("brgy_filter")
            or st.session_state.get("route_from", NO_ROUTE) != NO_ROUTE):
        clear_col.button("Clear all", on_click=clear_where, key="clear_where", type="tertiary",
                         icon=":material/close:", help="Back to all of Negros Oriental, with no route.")
    towns = st.multiselect("Cities / municipalities", sorted(barangays["municipality"].unique()),
                           placeholder="All of Negros Oriental", key="towns")
    in_towns = barangays if not towns else barangays[barangays["municipality"].isin(towns)]
    # One town chosen: just the barangay name. Otherwise add the town, because many names
    # repeat across towns (14 barangays are called "Poblacion").
    if len(towns) == 1:
        brgy_label = {int(r.barangay_id): r.barangay for r in in_towns.itertuples()}
    else:
        brgy_label = {int(r.barangay_id): f"{r.barangay}, {r.municipality}" for r in in_towns.itertuples()}
    # forget barangays that are no longer in the chosen towns (before drawing the picker)
    if "brgy_filter" in st.session_state:
        st.session_state["brgy_filter"] = [b for b in st.session_state["brgy_filter"] if b in brgy_label]
    brgys = st.multiselect("Barangays", sorted(brgy_label, key=brgy_label.get), format_func=brgy_label.get,
                           key="brgy_filter",
                           placeholder="All barangays" + (" in the chosen towns" if towns else ""))
    shown_ids = list(brgy_label) if not brgys else brgys
    # The birth-plan page opens this place: (town, barangay id); a row picked in the
    # Barangays tab replaces it further down
    first_brgy = brgys[0] if brgys else None
    first_town = (barangays.loc[barangays["barangay_id"] == first_brgy, "municipality"].iloc[0]
                  if first_brgy is not None else (towns[0] if towns else None))
    st.session_state["dash_place"] = (first_town, first_brgy)
    route_label = {i: brgy_label[i] for i in shown_ids}
    # NO_ROUTE (-1) stands for "No route" (a stored None would show as an empty "Choose an option")
    route_options = [NO_ROUTE] + sorted(route_label, key=route_label.get)
    # When the area changes: exactly one barangay -> show its route straight away, otherwise no route.
    # (Only when it CHANGES, so a route you picked is still there when you come back to this page.)
    if st.session_state.get("_route_area") != shown_ids:
        st.session_state["_route_area"] = shown_ids
        st.session_state["route_from"] = shown_ids[0] if len(shown_ids) == 1 else NO_ROUTE
    if st.session_state.get("route_from") not in route_options:
        st.session_state["route_from"] = NO_ROUTE
    route_pick = st.selectbox("Show route from", route_options, key="route_from",
                              format_func=lambda i: "No route" if i == NO_ROUTE else route_label[i],
                              help=f"Draws the fastest road path from a barangay to a {facility_one}.")
    route_from = None if route_pick == NO_ROUTE else route_pick  # None = no route, below

    # "Route to": the 3 nearest facilities from that barangay, so the user can compare choices.
    # (Season and care-level scenario are read here already; Streamlit runs top to bottom.)
    route_to, route_times = [], {}
    if route_from is not None:
        scenario_now = st.session_state.get("level_scenario", config.DEFAULT_LEVEL_SCENARIO)
        weather_now = (helpers.month_weather(rainfall, month, config.RAINY_MONTH_MM_THRESHOLD)
                       if rainfall is not None and month else None)
        season_now = ("Rainy season" if weather_now and weather_now["is_rainy"] else "Dry season") \
            if season_choice == "Auto (from month)" else f"{season_choice} season"
        m_now = matrices[season_now]
        codes = helpers.facilities_serving(helpers.use_scenario(facilities_all, scenario_now), level,
                                           st.session_state.get("upgrades", []))
        nearby = m_now.loc[route_from, [c for c in codes if c in m_now.columns]].dropna().sort_values().head(3)
        route_times = nearby.to_dict()
        if len(nearby) > 0:
            route_to = st.multiselect(
                "Route to", list(nearby.index), default=[nearby.index[0]], max_selections=3,
                # minutes FIRST: if a long name is cut off in the narrow panel, the time still shows
                format_func=lambda c: f"{route_times[c]:.0f} min · {helpers.facility_name(names.get(c, c))}",
                key=f"route_to_{route_from}_{level}_{season_now}",  # new choices when these change
                help="The 3 nearest facilities from this barangay, fastest first. The nearest is "
                     "selected; add others to compare routes.")

    st.button("⭐ Suggest best upgrade", on_click=suggest_best, width="stretch",
              key="main_action_suggest",  # brand orange (style in app.py)
              help="Finds the facility whose upgrade to the chosen level would bring the most people "
                   "within the time limit (Maximal Covering Location Problem), and shows it on the map.")

    with st.expander("More options"):
        map_mode = st.radio("Map view", ["2D", "3D"], horizontal=True, key="map_mode",
                            help="3D: each barangay is a column; taller = longer trip. Right-click and drag "
                                 "(or Ctrl + drag) to tilt and turn. 2D is easier for reading exact values.")
        month_name = calendar.month_name[month] if month else None
        weather = (helpers.month_weather(rainfall, month, config.RAINY_MONTH_MM_THRESHOLD)
                   if rainfall is not None and month else None)
        scenario_labels = {"type": "By facility type", "strict": "Strict: only government hospitals are CEmONC"}
        level_scenario = st.radio(
            "Care levels", list(scenario_labels), format_func=scenario_labels.get, key="level_scenario",
            help="There is no public list of certified BEmONC/CEmONC facilities, so blank levels are "
                 "assumed from the DOH facility type (hospital = CEmONC, infirmary = BEmONC, birthing "
                 "home = birthing). 'Strict' counts private hospitals as BEmONC instead, to test how "
                 "much the results depend on this assumption.",
        )
        # Apply the care-level scenario (confirmed levels are never changed)
        facilities = helpers.use_scenario(facilities_all, level_scenario)
        already = helpers.facilities_serving(facilities, level)
        upgrade_options = [c for c in candidates["nhfr_code"] if c not in already]

        st.number_input("How many sites to suggest", 1, config.MAX_NEW_SITES, key="n_suggest")
        # drop saved upgrades that are not valid for the current level (before drawing the picker)
        st.session_state["upgrades"] = [c for c in st.session_state.get("upgrades", []) if c in upgrade_options]
        upgrades = st.multiselect(f"Or pick facilities to upgrade to {level}", upgrade_options,
                                  format_func=lambda c: names.get(c, c), key="upgrades")
        if upgrades:
            st.button("Remove upgrades", on_click=clear_upgrades, width="stretch")

# Which travel-time table to use
if season_choice == "Auto (from month)":
    season = "Rainy season" if (weather is not None and weather["is_rainy"]) else "Dry season"
else:
    season = f"{season_choice} season"
matrix = matrices[season]
settings = (level, threshold, season, level_scenario)  # a suggestion is only valid for these

# ---------------------------------------------------------------
# Calculations (before = no upgrades, table = with the what-if upgrades)
# ---------------------------------------------------------------
before = helpers.access_table(barangays, facilities, matrix, level, threshold)
table = helpers.access_table(barangays, facilities, matrix, level, threshold, upgrades)
filtered = bool(towns or brgys)
view = table[table["barangay_id"].isin(shown_ids)]            # what the map and table show
view0 = before[before["barangay_id"].isin(shown_ids)]
s1, s0 = helpers.coverage_summary(view, weight_col), helpers.coverage_summary(view0, weight_col)
backup1 = helpers.backup_coverage(view, matrix, helpers.facilities_serving(facilities, level, upgrades),
                                  threshold, weight_col)
backup0 = helpers.backup_coverage(view0, matrix, already, threshold, weight_col)
equity = (helpers.equity_gap(table, poverty, weight_col, config.EQUITY_GROUP_SHARE)
          if poverty is not None and not filtered else None)

# The same numbers for the OTHER season, so the cards can show the seasonal difference
other_season = "Dry season" if season == "Rainy season" else "Rainy season"
table_other = helpers.access_table(barangays, facilities, matrices[other_season], level, threshold, upgrades)
view_other = table_other[table_other["barangay_id"].isin(shown_ids)]
s_other = helpers.coverage_summary(view_other, weight_col)
backup_other = helpers.backup_coverage(view_other, matrices[other_season],
                                       helpers.facilities_serving(facilities, level, upgrades), threshold, weight_col)

# Sensitivity check: the headline count again with ALL assumed speeds 20% slower / faster
area = barangays[barangays["barangay_id"].isin(shown_ids)]
sens = helpers.sensitivity_range(area, facilities, matrix, level, threshold, weight_col,
                                 config.SENSITIVITY_SPEED_CHANGE, upgrades)

# Split the people beyond the limit into two groups that need DIFFERENT fixes:
#  - no road in our model (an island, or a road missing on OpenStreetMap): a boat or transport plan
#  - a road exists but the trip is too long: an upgrade or an ambulance
no_road = view[view["unreachable"]]
no_road_people = no_road[weight_col].sum()
# People beyond the limit who live in a town bordering Negros Occidental: the model never sends
# anyone across the border, so some of them may really have a nearer hospital there
border_people = view.loc[~view["within"] & view["municipality"].isin(border_towns), weight_col].sum()
too_far_people = s1["not_covered"] - no_road_people

# Care-level check: the same headline under the OTHER care-level scenario
other_scenario = "strict" if level_scenario == "type" else "type"
s_scenario = helpers.coverage_summary(
    helpers.access_table(area, helpers.use_scenario(facilities_all, other_scenario), matrix, level, threshold,
                         upgrades), weight_col)


@st.cache_data(show_spinner=False)
def critical_cached(level, threshold, season, scenario, ids, weight_col):
    """Remembered between redraws: it is the slowest calculation (up to ~0.3 s)."""
    brgy, fac, _cand, mats = app_data.load_data()
    fac = helpers.use_scenario(fac, scenario)
    area = brgy[brgy["barangay_id"].isin(ids)]
    return helpers.critical_facilities(area, fac, mats[season], level, threshold, weight_col)


@st.cache_data(show_spinner=False)
def best_sites_cached(level, threshold, season, scenario, ids, weight_col):
    """The best 1, 2 and 3 facilities to upgrade (current network, no what-if upgrades).
    Remembered between redraws."""
    brgy, fac, cand, mats = app_data.load_data()
    fac = helpers.use_scenario(fac, scenario)
    t = helpers.access_table(brgy[brgy["barangay_id"].isin(ids)], fac, mats[season], level, threshold)
    already = helpers.facilities_serving(fac, level)
    options = [c for c in cand["nhfr_code"] if c not in already]
    base = helpers.coverage_summary(t, weight_col)
    rows = []
    for n in range(1, config.MAX_NEW_SITES + 1):
        chosen, gain = helpers.best_sites(t, mats[season], options, threshold, n, weight_col)
        after = 100 * (base["covered"] + gain) / base["total"] if base["total"] > 0 else 0
        rows.append({"n": n, "sites": chosen, "gain": gain, "before": base["pct_covered"], "after": after})
    return rows


crit_raw = critical_cached(level, threshold, season, level_scenario, tuple(shown_ids), weight_col)

# "2 hours" / "90 minutes", for labels
limit_text = (f"{threshold // 60} hour{'s' if threshold >= 120 else ''}" if threshold % 60 == 0
              else f"{threshold} minutes")
places_all = pd.concat([facilities_all, candidates]).drop_duplicates("nhfr_code").set_index("nhfr_code")


def place_label(code):
    """'Mabinay Medicare Community Hospital (Mabinay)': facility name and town, normal capitals."""
    if code not in places_all.index:
        return names.get(code, code)
    row = places_all.loc[code]
    return f"{helpers.facility_name(row['facility_name'])} ({helpers.town_name(row['city_municipality'])})"


def people_round(n):
    """Headline numbers rounded to the nearest 100: the model is not exact to the person
    (see the sensitivity range). Exact numbers stay in the tables and downloads."""
    n = float(n)
    return f"{round(n, -2):,.0f}" if n >= 1000 else f"{n:,.0f}"

# ---------------------------------------------------------------
# Header (kept short so the map starts high on the screen)
# ---------------------------------------------------------------
# The title and the headline go in one box at the top of the page (small gaps between them)
page_top = st.container(key="page_top", gap="small")
page_top.markdown(
    "<div style='margin-bottom:0.2rem'><span class='brand-title' style='font-size:1.35rem;font-weight:700'>"
    "Travel Time to Childbirth Care · Negros Oriental</span><br>"
    f"<span style='font-size:0.88rem;color:#3d4d4d'><b>For provincial and city health offices</b> · {season} · "
    f"{LEVEL_CHOICES[level]} · {limit_text} limit" + (" · selected area" if filtered else "") + "</span></div>",
    unsafe_allow_html=True)
app_data.demo_banner()

# ---------------------------------------------------------------
# Routes: the road path from one barangay to each facility picked in "Route to"
# ---------------------------------------------------------------
# One color per route (all differ from the teal map colors): orange, violet, near-black
ROUTE_COLORS = ["#c2491d", "#5b2c83", "#1e1e1e"]
ROUTE_COLOR_NAMES = ["orange", "violet", "black"]
routes = []          # one dict per route that is drawn
route_note = None
if route_from is not None:
    r = view[view["barangay_id"] == route_from].iloc[0]
    roads = app_data.load_roads()
    if roads is None or not route_to:
        route_note = (f"{r['barangay']} has no road connection in this model (an island that needs a boat, "
                      f"or a road missing on OpenStreetMap), so there is no route to draw.")
    else:
        places = pd.concat([facilities, candidates]).drop_duplicates("nhfr_code").set_index("nhfr_code")
        weight = "time_rainy" if season == "Rainy season" else "time_dry"
        start_node = ox.distance.nearest_nodes(roads, X=r["lon"], Y=r["lat"])
        for i, code in enumerate(route_to):
            dest = places.loc[code]
            end_node = ox.distance.nearest_nodes(roads, X=dest["longitude"], Y=dest["latitude"])
            points = helpers.route_points(roads, start_node, end_node, weight)
            if not points:  # should not happen, but never crash the page over a drawing
                points = [(r["lat"], r["lon"]), (dest["latitude"], dest["longitude"])]
            road_km = sum(helpers.haversine_km(a[0], a[1], b[0], b[1]) for a, b in zip(points[:-1], points[1:]))
            routes.append({
                "points": points, "from": (r["lat"], r["lon"]), "to": (dest["latitude"], dest["longitude"]),
                "color": ROUTE_COLORS[i], "color_name": ROUTE_COLOR_NAMES[i], "start": r["barangay"],
                "text": f"{r['barangay']} → {helpers.facility_name(names.get(code, code))}: about {route_times[code]:.0f} min "
                        f"({season.lower()}), {road_km:.0f} km by road",
            })

# ---------------------------------------------------------------
# Results strip ABOVE the map: three tiles, each answering one planner question
#   1. How many people are too far?   2. Which facility can we not lose?   3. Where to upgrade first?
# ---------------------------------------------------------------
def draw_numbers():
    people = weight_label.split(" (")[0]          # "people" (or "women aged 15-49")
    other = other_season.lower()
    t1, t2, t3 = st.columns([1.55, 1, 1])

    # ---- Tile 1: people beyond the limit, split into "no road" and "road, too slow" ----
    with t1.container(key="tile_beyond"):
        details = (f"Exact number: {s1['not_covered']:,.0f} of {s1['total']:,.0f} {weight_label} "
                   f"({100 - s1['pct_covered']:.1f}%). Headline numbers are rounded to the nearest 100; "
                   f"the tables have exact numbers.  \n"
                   f"No road: barangays our road map does not reach (islands, or roads missing on "
                   f"OpenStreetMap). They need a boat or transport plan; see the No road tab.  \n"
                   f"Backup: {backup1:.1f}% have 2 or more {facilities_many} within {threshold} min "
                   f"({backup_other:.1f}% in the {other}).")
        if border_people > 0:
            details += (f"  \nBorder: {border_people:,.0f} of them live in towns bordering Negros Occidental. "
                        f"Our roads stop at the province border, so hospitals across it are left out: "
                        f"some of these people may be closer to care than shown.")
        if equity is not None:
            details += (f"  \nEquity gap: {equity['gap_pts']:.1f} pts between the poorest and least-poor "
                        f"municipalities (PSA poverty {equity['year']}).")
        st.markdown(f"<span class='tile-label'>{people.capitalize()} more than {limit_text} away</span>",
                    unsafe_allow_html=True, help=details)
        gained = s0["not_covered"] - s1["not_covered"]
        if upgrades and gained > 0:  # what-if: show how much the upgrade(s) changed the number
            side = (f"<span class='tile-side' style='color:#2e7d32'>↓ {people_round(gained)} "
                    f"with the upgrade{'s' if len(upgrades) > 1 else ''}</span>")
        elif upgrades:  # an upgrade that does not reach anyone in the selected area
            side = "<span class='tile-side'>the upgrade adds no one here</span>"
        else:
            side = f"<span class='tile-side'>{other} {people_round(s_other['not_covered'])}</span>"
        st.markdown(f"<span class='tile-number'>{people_round(s1['not_covered'])}{side}</span>",
                    unsafe_allow_html=True)  # the side note sits on the same line as the number
        if s1["not_covered"] > 0:
            # one bar = everyone beyond the limit; same colors as the map legend (grey = no road)
            grey, dark = helpers.BAND_COLORS["none"], helpers.BAND_COLORS["far"]
            share = 100 * no_road_people / s1["not_covered"]
            st.markdown(
                f"<div class='tile-bar'><div style='width:{share:.1f}%;background:{grey}'></div>"
                f"<div style='width:{100 - share:.1f}%;background:{dark}'></div></div>"
                f"<span class='tile-small'><span class='tile-key' style='background:{grey}'></span>"
                f"No road · {people_round(no_road_people)} &nbsp; "
                f"<span class='tile-key' style='background:{dark}'></span>"
                f"Road, too slow · {people_round(too_far_people)}</span>", unsafe_allow_html=True)
            pct = round(config.SENSITIVITY_SPEED_CHANGE * 100)
            levels = ("same with strict levels" if s_scenario["not_covered"] == s1["not_covered"]
                      else f"{people_round(s_scenario['not_covered'])} with other levels")
            st.markdown(f"<span class='tile-small'>Range {people_round(sens['faster'])}–"
                        f"{people_round(sens['slower'])} if speeds ±{pct}% · {levels}</span>",
                        unsafe_allow_html=True)
        else:
            st.markdown("<span class='tile-text'>Everyone is within the limit.</span>", unsafe_allow_html=True)

    # ---- Tile 2: the facility with no backup (the most people would lose access if it closed) ----
    with t2.container(key="tile_critical"):
        st.markdown("<span class='tile-label'>⚠ No backup if it closes</span>", unsafe_allow_html=True,
                    help=f"If this {facility_one} closed, these {weight_label} would have no other one within "
                         f"{threshold} min ({season.lower()}). All facilities: Existing facilities tab.")
        if len(crit_raw) > 0 and crit_raw["people_losing_access"].iloc[0] > 0:
            top = crit_raw.iloc[0]
            st.markdown(f"<span class='tile-number' style='color:#8a3a35'>"
                        f"{people_round(top['people_losing_access'])}</span>", unsafe_allow_html=True)
            st.markdown(f"<span class='tile-text'>{people} depend on {html.escape(place_label(top['nhfr_code']))}"
                        f"</span>", unsafe_allow_html=True)
        else:
            st.markdown("<span class='tile-number'>0</span>", unsafe_allow_html=True)
            st.markdown(f"<span class='tile-text'>Every area keeps another {facility_one} within the limit."
                        f"</span>", unsafe_allow_html=True)

    # ---- Tile 3: the best single upgrade, with a button to show it on the map ----
    with t3.container(key="tile_upgrade"):
        st.markdown("<span class='tile-label'>⭐ Best single upgrade</span>", unsafe_allow_html=True,
                    help=f"The rural health unit, birthing home or infirmary that, upgraded to {facility_one}, "
                         f"brings the most {weight_label} within {threshold} min (Maximal Covering Location "
                         f"Problem). Best 2 and 3: Where to upgrade tab.  \n"
                         f"It shows where added capacity would help most, not a costed plan: the staff (e.g. an obstetrician and an anesthesiologist), operating room, blood supply and cost are not modelled.")
        best = best_sites_cached(level, threshold, season, level_scenario, tuple(shown_ids), weight_col)[0]
        if best["gain"] > 0:
            st.markdown(f"<span class='tile-number' style='color:#047878'>+{people_round(best['gain'])}</span>",
                        unsafe_allow_html=True)
            st.markdown(f"<span class='tile-text'>{people} within {limit_text} if "
                        f"{html.escape(place_label(best['sites'][0]))} is upgraded</span>", unsafe_allow_html=True)
            if upgrades:
                st.button("Remove from map", on_click=clear_upgrades, key="tile_remove", type="tertiary",
                          icon=":material/close:")
            else:
                st.button("Show on map", on_click=show_upgrade_set, args=(best["sites"], best["gain"]),
                          key="tile_show", type="tertiary", icon=":material/arrow_forward:")
        else:
            st.markdown("<span class='tile-number'>0</span>", unsafe_allow_html=True)
            st.markdown("<span class='tile-text'>No single upgrade brings more people within the limit."
                        "</span>", unsafe_allow_html=True)


# ---------------------------------------------------------------
# Map (2D folium or 3D pydeck)
# ---------------------------------------------------------------
# folium.Icon color names and the hex color each one is drawn with (for the legends)
LEVEL_ICON = {"CEmONC": "darkred", "BEmONC": "purple", "birthing": "cadetblue"}
ICON_HEX = {"darkred": "#a23336", "purple": "#d252b9", "cadetblue": "#436978", "orange": "#f69730"}
shown_levels = [l for l in ["CEmONC", "BEmONC", "birthing"] if helpers.level_rank(l) >= helpers.level_rank(level)]

# zoom to the route if there is one, otherwise to the selected area (or the whole province)
zoom_to = ([p for rt in routes for p in rt["points"] + [rt["from"], rt["to"]]] if routes
           else list(zip(view["lat"], view["lon"])))


# ---- Hover cards (tooltips): small, labeled, wrapping text, normal capitalization ----
TIP_BOX = ("background:#ffffff; border:none; border-radius:8px; padding:7px 9px; "
           "box-shadow:0 2px 8px rgba(0,0,0,.25); color:#1e2b2b;")


def tip_card(title, subtitle, rows):
    """HTML for one hover card: bold title, grey subtitle, then 'Label: value' lines."""
    lines = "".join(f"<br><b>{html.escape(k)}:</b> {html.escape(str(v))}" for k, v in rows)
    return (f"<div style='font:12px/1.45 sans-serif;width:230px;white-space:normal'>"
            f"<b style='font-size:13px'>{html.escape(str(title))}</b>"
            f"<br><span style='color:#5a6b6b'>{html.escape(str(subtitle))}</span>{lines}</div>")


def barangay_tip(row):
    trip = "no road connection" if pd.isna(row["minutes"]) else f"about {row['minutes']:.0f} min ({season.lower()})"
    nearest = "-" if pd.isna(row["nearest_facility"]) else helpers.facility_name(row["nearest_facility"])
    people = 0 if pd.isna(row[weight_col]) else row[weight_col]
    return tip_card(row["barangay"], row["municipality"],
                    [("Trip", trip), ("Nearest", nearest),
                     (weight_label.split(" (")[0].capitalize(), f"{people:,.0f}")])


def draw_2d():
    # OpenStreetMap base map, shown in light grey (see "muted" below) so the colored barangays stand
    # out. (CARTO's grey tiles now need an account, this needs none.) Mouse wheel zooms the map.
    m = folium.Map(tiles="OpenStreetMap")
    muted = MacroElement()
    muted._template = Template("""
{% macro script(this, kwargs) %}
var tiles = {{ this._parent.get_name() }}.getPane('tilePane');
tiles.style.filter = 'grayscale(100%) brightness(1.08) contrast(0.85)';
tiles.style.opacity = '0.75';
// fill the whole map frame (its height is set by the page CSS); Leaflet then
// redraws by itself whenever the window, and so the frame, is resized
{{ this._parent.get_name() }}.getContainer().style.height = '100vh';
{{ this._parent.get_name() }}.invalidateSize();
document.documentElement.style.overflow = 'hidden';  // no stray scrollbar inside the frame
{% endmacro %}
""")
    m.add_child(muted)
    # Full-screen button (top-left, under + / -). Our own, because the browser's full-screen feature
    # is often blocked for maps inside a page frame (the button then did nothing). This one makes
    # the map frame fill the whole window instead (style: [data-expanded] in the page CSS above).
    # Press the button again, or Esc, to go back.
    expand = MacroElement()
    expand._template = Template("""
{% macro script(this, kwargs) %}
(function () {
  var map = {{ this._parent.get_name() }};
  var frame = window.frameElement;           // the map's frame in the page (same website)
  if (!frame) { return; }
  var ICON_OPEN = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#333" stroke-width="2.4"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>';
  var ICON_CLOSE = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#333" stroke-width="2.4"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>';
  var link;
  function showIcon(on) {
    link.innerHTML = on ? ICON_CLOSE : ICON_OPEN;
    link.title = on ? 'Exit full screen (Esc)' : 'Full screen';
    link.setAttribute('aria-label', link.title);
  }
  function setExpanded(on) {
    if (on) { frame.setAttribute('data-expanded', '1'); } else { frame.removeAttribute('data-expanded'); }
    frame.ownerDocument.body.style.overflow = on ? 'hidden' : '';   // no page scrolling behind it
    showIcon(on);
    // redraw at the new size; the center and zoom stay the same, you just see more (or less) around it
    setTimeout(function () { map.invalidateSize(); }, 60);
  }
  var Expand = L.Control.extend({
    options: { position: 'topleft' },
    onAdd: function () {
      var box = L.DomUtil.create('div', 'leaflet-bar leaflet-control');
      link = L.DomUtil.create('a', '', box);
      link.href = '#';
      link.setAttribute('role', 'button');
      link.style.display = 'flex'; link.style.alignItems = 'center'; link.style.justifyContent = 'center';
      L.DomEvent.on(link, 'click', function (e) {
        L.DomEvent.stop(e);
        setExpanded(!frame.hasAttribute('data-expanded'));
      });
      return box;
    }
  });
  map.addControl(new Expand());
  showIcon(false);
  frame.removeAttribute('data-expanded');        // a redrawn map always starts at normal size
  frame.ownerDocument.body.style.overflow = '';
  // Esc closes it, whether the map or the page around it has the keyboard focus
  function onKey(e) { if (e.key === 'Escape' && frame.hasAttribute('data-expanded')) { setExpanded(false); } }
  document.addEventListener('keydown', onKey);
  frame.ownerDocument.addEventListener('keydown', onKey);
})();
{% endmacro %}
""")
    m.add_child(expand)
    m.fit_bounds([[min(p[0] for p in zoom_to), min(p[1] for p in zoom_to)],
                  [max(p[0] for p in zoom_to), max(p[1] for p in zoom_to)]], max_zoom=14)

    # Barangays: colored AREAS (a "choropleth" map). Color = trip-time band.
    areas = view.copy()
    areas["band"] = areas["minutes"].map(lambda x: helpers.travel_band(x, threshold))
    areas["tip"] = areas.apply(barangay_tip, axis=1)

    shapes = app_data.load_barangay_shapes()
    if shapes is not None:
        areas = shapes.merge(areas[["barangay_id", "band", "tip"]], on="barangay_id")
        folium.GeoJson(
            areas,
            style_function=lambda f: {"fillColor": helpers.BAND_COLORS[f["properties"]["band"]],
                                      "fillOpacity": 0.75, "color": "#ffffff", "weight": 0.6},
            highlight_function=lambda f: {"color": "#1e2b2b", "weight": 2},
            tooltip=folium.GeoJsonTooltip(fields=["tip"], labels=False, style=TIP_BOX),
        ).add_to(m)
    else:
        # no outline file (e.g. demo data): fall back to one circle per barangay
        for _, row in areas.iterrows():
            folium.CircleMarker(
                location=[row["lat"], row["lon"]], radius=6, color="#ffffff", weight=1,
                fill=True, fill_color=helpers.BAND_COLORS[row["band"]], fill_opacity=0.9,
                tooltip=folium.Tooltip(row["tip"], style=TIP_BOX),
            ).add_to(m)

    # Place names ON TOP of the colors: the base map's own names are part of its pictures, so the
    # colored areas cover them. They follow the same two rules as the base map's names:
    #  1. by zoom: town names from zoom 9 (about the whole province), barangay names from zoom 12
    #     (from zoom 10 when only a small area is shown);
    #  2. never on top of each other: names are placed in order of importance (towns first, more
    #     people first) and a name that would overlap one already placed is hidden until there is room.
    town_points = app_data.load_town_points().merge(
        barangays.groupby("municipality", as_index=False)[weight_col].sum(), on="municipality")
    town_points = town_points.sort_values(weight_col, ascending=False)           # biggest towns first
    place_labels = MacroElement()
    place_labels.towns = json.dumps([[round(r.lat, 5), round(r.lon, 5), html.escape(r.municipality)]
                                     for r in town_points.itertuples()])
    place_labels.brgys = json.dumps([[round(r.lat, 5), round(r.lon, 5), html.escape(r.barangay)]
                                     for r in view.sort_values(weight_col, ascending=False).itertuples()])
    place_labels.town_zoom = 9
    place_labels.brgy_zoom = 10 if len(view) <= 60 else 12
    place_labels._template = Template("""
{% macro script(this, kwargs) %}
(function () {
  var map = {{ this._parent.get_name() }};
  var css = document.createElement('style');   // small dark text with a soft white outline, like the base map
  css.textContent = '.place-label{font:600 11px sans-serif;color:#2b3434;white-space:nowrap;'
    + 'transform:translate(-50%,-50%);text-shadow:0 0 2px #fff,0 0 2px #fff,0 0 1px #fff;}'
    + '.place-label.brgy{font:400 10px sans-serif;color:#3a4545;}';
  document.head.appendChild(css);
  map.createPane('placeLabels');
  map.getPane('placeLabels').style.zIndex = 450;            // above the colors, below the pins
  map.getPane('placeLabels').style.pointerEvents = 'none';  // hover cards still work underneath
  function layer(list, kind) {
    return L.layerGroup(list.map(function (p) {
      return L.marker([p[0], p[1]], {pane: 'placeLabels', interactive: false, keyboard: false,
        icon: L.divIcon({className: '', iconSize: null, html: '<div class="place-label ' + kind + '">' + p[2] + '</div>'})});
    }));
  }
  var towns = layer({{ this.towns }}, 'town');
  var brgys = layer({{ this.brgys }}, 'brgy');
  function showAtZoom(group, minZoom) {
    var show = map.getZoom() >= minZoom;
    if (show && !map.hasLayer(group)) { group.addTo(map); }
    if (!show && map.hasLayer(group)) { map.removeLayer(group); }
  }
  // hide any name that would overlap a more important one (towns first, then barangays, biggest first)
  function declutter() {
    var placed = [];
    [towns, brgys].forEach(function (group) {
      if (!map.hasLayer(group)) { return; }
      group.eachLayer(function (marker) {
        var el = marker.getElement();
        if (!el) { return; }
        var label = el.firstChild;
        label.style.visibility = 'visible';
        var r = label.getBoundingClientRect();
        var box = {l: r.left - 3, t: r.top - 2, r: r.right + 3, b: r.bottom + 2};   // a little breathing room
        var hit = placed.some(function (p) { return box.l < p.r && box.r > p.l && box.t < p.b && box.b > p.t; });
        if (hit) { label.style.visibility = 'hidden'; } else { placed.push(box); }
      });
    });
  }
  function update() {
    showAtZoom(towns, {{ this.town_zoom }});
    showAtZoom(brgys, {{ this.brgy_zoom }});
    declutter();
  }
  map.on('zoomend moveend', update);
  update();
  setTimeout(update, 300);   // once more after the first drawing has settled
})();
{% endmacro %}
""")
    m.add_child(place_labels)

    # Pins that sit on top of each other (e.g. the 4 hospitals in Dumaguete) are grouped into
    # one round badge with a number; zoom in (or click the badge) to see them separately.
    pin_group = MarkerCluster(
        options={"maxClusterRadius": 35, "disableClusteringAtZoom": 13, "showCoverageOnHover": False},
        icon_create_function="""function (cluster) {
            return L.divIcon({html: '<div style="background:#1e2b2b;color:#fff;border:2px solid #fff;'
                + 'border-radius:50%;width:30px;height:30px;line-height:26px;text-align:center;'
                + 'font:bold 13px sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.4)">'
                + cluster.getChildCount() + '</div>', className: '', iconSize: [30, 30]});
        }""",
    ).add_to(m)
    for _, f in facilities.iterrows():
        if f["obstetric_level"] in shown_levels:
            rows = [("Care", PIN_NAME[f["obstetric_level"]])]
            if "phone" in f and pd.notna(f["phone"]) and f["phone"]:
                rows.append(("Phone", f["phone"]))
            folium.Marker(
                [f["latitude"], f["longitude"]],
                tooltip=folium.Tooltip(tip_card(helpers.facility_name(f["facility_name"]), helpers.town_name(f["city_municipality"]),
                                                rows), style=TIP_BOX),
                icon=folium.Icon(color=LEVEL_ICON[f["obstetric_level"]], icon="plus"),
            ).add_to(pin_group)

    for code in upgrades:
        f = candidates[candidates["nhfr_code"] == code].iloc[0]
        folium.Marker([f["latitude"], f["longitude"]],
                      tooltip=folium.Tooltip(tip_card(helpers.facility_name(f["facility_name"]), "What-if upgrade",
                                                      [("Upgraded to", level)]), style=TIP_BOX),
                      icon=folium.Icon(color="orange", icon="star")).add_to(m)

    for i, rt in enumerate(routes):
        # solid line = by road; dashed lines = walking to/from the road
        line = folium.PolyLine(rt["points"], color=rt["color"], weight=7, opacity=0.95,
                               tooltip=f"Route {i + 1}: {rt['text']}")
        line.add_to(m)
        for walk in ([rt["from"], rt["points"][0]], [rt["points"][-1], rt["to"]]):
            folium.PolyLine(walk, color=rt["color"], weight=3, dash_array="6 6").add_to(m)
        # white arrows ON the line, pointing from the barangay TO the facility
        # (the points run barangay -> facility, and the arrows follow that order)
        PolyLineTextPath(line, "        ►        ", repeat=True, offset=4,
                         attributes={"fill": "#ffffff", "font-size": "11", "font-weight": "bold"}).add_to(m)
    if routes:
        # one "Start" marker at the barangay center (all routes start there)
        folium.CircleMarker(routes[0]["from"], radius=8, color=routes[0]["color"], weight=3, fill=True,
                            fill_color="#ffffff", fill_opacity=1,
                            tooltip=f"Start: {routes[0]['start']}").add_to(m)

    # ---- Legend box in the map's bottom-left corner (text + color, never color alone) ----
    def dot(color, size=11):
        # small rounded square = a colored barangay area
        return (f"<span style='display:inline-block;width:{size}px;height:{size}px;border-radius:3px;"
                f"background:{color};vertical-align:middle;margin-right:5px'></span>")

    def pin(color, symbol):
        return (f"<span style='display:inline-block;width:14px;height:14px;border-radius:50% 50% 50% 0;"
                f"transform:rotate(-45deg);background:{color};vertical-align:middle;margin-right:6px'>"
                f"<span style='display:block;transform:rotate(45deg);color:#fff;font-size:9px;"
                f"line-height:14px;text-align:center'>{symbol}</span></span>")

    # Two short lines only: circle colors, then the pin types that are on the map
    gap = "&nbsp;&nbsp;"
    rows = ["<b>Trip to care:</b>" + gap + gap.join(dot(col) + BAND_LABELS[b]
                                                   for b, col in helpers.BAND_COLORS.items())]
    marks = [pin(ICON_HEX[LEVEL_ICON[l]], "+") + SHORT_PIN[l] for l in shown_levels]
    marks.append("<span style='display:inline-block;width:15px;height:15px;border-radius:50%;background:#1e2b2b;"
                 "color:#fff;font-size:9px;line-height:15px;text-align:center;vertical-align:middle;"
                 "margin-right:4px'>3</span>several, zoom in")
    if upgrades:
        marks.append(pin(ICON_HEX["orange"], "★") + "upgrade")
    if routes:
        lines = "".join(f"<span style='display:inline-block;width:14px;border-top:4px solid {rt['color']};"
                        f"vertical-align:middle;margin-right:2px'></span>" for rt in routes)
        marks.append(f"{lines} route{'s' if len(routes) > 1 else ''}: "
                     f"<span style='display:inline-block;width:9px;height:9px;border-radius:50%;"
                     f"border:2px solid {routes[0]['color']};background:#fff;vertical-align:middle'></span> start "
                     f"► to facility")
    rows.append(gap.join(marks))

    legend = MacroElement()
    legend._template = Template("""
{% macro script(this, kwargs) %}
var legend = L.control({position: 'bottomleft'});
legend.onAdd = function () {
    var div = L.DomUtil.create('div');
    div.style.cssText = 'background:rgba(255,255,255,.92);padding:5px 9px;border-radius:8px;'
                      + 'font:13px sans-serif;color:#1e2b2b;line-height:1.7;box-shadow:0 1px 6px rgba(0,0,0,.18)';
    div.innerHTML = """ + json.dumps("<br>".join(rows)) + """;
    return div;
};
legend.addTo({{ this._parent.get_name() }});
{% endmacro %}
""")
    m.add_child(legend)
    st_folium(m, height=MAP_HEIGHT, use_container_width=True, returned_objects=[])


def rgb(hex_color, alpha=230):
    """'#02a6ad' -> [2, 166, 173, alpha]  (pydeck wants colors as number lists)"""
    h = hex_color.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)] + [alpha]


def draw_3d():
    """3D view: one column per barangay. Height = travel minutes, color = travel band.
    Facilities are dots on the ground; the route (if any) is a line."""
    cols = view.copy()
    cols["color"] = cols["minutes"].map(lambda x: rgb(helpers.BAND_COLORS[helpers.travel_band(x, threshold)]))
    cols["people"] = cols[weight_col].fillna(0).map(lambda p: f"{p:,.0f} {weight_label}")
    cols["trip"] = cols["minutes"].map(lambda x: "no road connection" if pd.isna(x) else f"{x:.0f} min")
    cols["height"] = cols["minutes"].fillna(5)  # no-road barangays: a short gray stub
    cols["nearest"] = cols["nearest_facility"].fillna("-")
    cols = cols[["lon", "lat", "height", "color", "barangay", "municipality", "trip", "nearest", "people"]]

    layers = [pdk.Layer("ColumnLayer", data=cols, get_position=["lon", "lat"], get_elevation="height",
                        elevation_scale=60,  # 1 minute = 60 m tall, so a 2-hour trip is a 7 km column
                        radius=450, get_fill_color="color", pickable=True, auto_highlight=True)]

    fac = facilities[facilities["obstetric_level"].isin(shown_levels)].copy()
    fac["color"] = fac["obstetric_level"].map(lambda l: rgb(ICON_HEX[LEVEL_ICON[l]], 255))
    fac["municipality"] = fac["obstetric_level"].map(PIN_NAME)
    fac["trip"], fac["nearest"], fac["people"] = "", "", ""
    fac = fac.rename(columns={"facility_name": "barangay"})
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=fac[["longitude", "latitude", "color", "barangay", "municipality", "trip", "nearest", "people"]],
        get_position=["longitude", "latitude"], get_fill_color="color", get_radius=700,
        radius_min_pixels=5, stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=2,
        pickable=True))
    if upgrades:
        up = candidates[candidates["nhfr_code"].isin(upgrades)]
        layers.append(pdk.Layer("ScatterplotLayer", data=up[["longitude", "latitude"]],
                                get_position=["longitude", "latitude"],
                                get_fill_color=rgb(ICON_HEX["orange"], 255), get_radius=900, radius_min_pixels=6))
    for rt in routes:
        path = [[p[1], p[0]] for p in [rt["from"]] + rt["points"] + [rt["to"]]]  # (lon, lat)
        layers.append(pdk.Layer("PathLayer", data=[{"path": path}], get_path="path",
                                get_color=rgb(rt["color"], 255), width_min_pixels=4))
    if routes:
        # "Start" marker at the barangay (white dot with a colored ring)
        start_pos = [routes[0]["from"][1], routes[0]["from"][0]]
        layers.append(pdk.Layer("ScatterplotLayer", data=[{"pos": start_pos}], get_position="pos",
                                get_fill_color=[255, 255, 255, 255], get_line_color=rgb(routes[0]["color"], 255),
                                stroked=True, line_width_min_pixels=3, get_radius=500, radius_min_pixels=7))

    # Start tilted, looking at the selected area (or the route)
    start = pdk.data_utils.compute_view([[p[1], p[0]] for p in zoom_to], view_proportion=0.95)
    start.zoom = min(start.zoom + 0.6, 13)  # compute_view leaves a wide margin; come a bit closer
    start.pitch, start.bearing = 50, -15
    st.pydeck_chart(pdk.Deck(
        layers=layers, initial_view_state=start, map_style=pdk.map_styles.CARTO_LIGHT,
        tooltip={"html": "<b>{barangay}</b><br>{municipality}<br>{trip}<br>{nearest}<br>{people}",
                 "style": {"fontSize": "12px"}},
    ), height=MAP_HEIGHT)


draw_numbers()
if map_mode == "3D":
    draw_3d()
else:
    draw_2d()

# Small notes under the map (only when they apply)
if map_mode == "3D":
    dot3 = ("<span style='display:inline-block;width:11px;height:11px;border-radius:50%;"
            "background:{};vertical-align:middle'></span> {}")
    bands = " &nbsp; ".join(dot3.format(c, BAND_LABELS[b]) for b, c in helpers.BAND_COLORS.items())
    pins = " &nbsp; ".join(dot3.format(ICON_HEX[LEVEL_ICON[l]], SHORT_PIN[l]) for l in shown_levels)
    st.markdown(f"<span style='font-size:0.85rem'>**Trip to care** (taller = longer): {bands}"
                f" &nbsp;|&nbsp; {pins}</span>", unsafe_allow_html=True)
for i, rt in enumerate(routes):
    swatch = (f"<span style='display:inline-block;width:16px;border-top:4px solid {rt['color']};"
              f"vertical-align:middle;margin-right:4px'></span>")
    st.markdown(f"<span style='font-size:0.88rem'>{swatch}<b>Route {i + 1} ({rt['color_name']}):</b> "
                f"{html.escape(rt['text'])}</span>", unsafe_allow_html=True)
if routes:
    st.caption("Lines follow the fastest roads in the model; dashed parts are walking between the road "
               "and the barangay center or facility. Times are estimates, not measured trips.")
if route_note:
    st.caption(route_note)

# Context and the main caveat, in one quiet note under the map
context = ([month_name] if month_name else []) + [f"{season} travel times"]
if weather is not None:
    context.append(f"{weather['rain_mm']:.0f} mm normal rain")
demand = helpers.seasonal_demand(births, month) if births is not None and month else None
if demand is not None:
    busier = " (historically busier: plan a second facility)" if demand["pct_vs_average"] > 0 else ""
    context.append(f"births {demand['pct_vs_average']:+.0f}% vs. average month{busier}")
caveat = ("Travel times are model estimates from OpenStreetMap roads and assumed speeds, not measured trips: "
          "use them to compare places, not to promise a time to a patient.")
if "level_basis" in facilities.columns and (facilities["level_basis"] != "confirmed").any():
    caveat += " Care levels are assumed from the DOH facility type (see About the data)."
st.caption(" · ".join(context) + ". " + caveat)

# ---------------------------------------------------------------
# Below the map: tabs, so each planner table is one click away (instead of folded and easy to miss)
# ---------------------------------------------------------------
show = view.copy()
show["beyond_limit"] = (~show["within"]) * show[weight_col].fillna(0)
show = show.sort_values(["beyond_limit", "minutes"], ascending=False)
ids_in_order = [int(i) for i in show["barangay_id"]]  # remember which row is which barangay
show = show[["barangay", "municipality", "beyond_limit", "minutes", "nearest_facility", weight_col]]
show = show.rename(columns={"beyond_limit": f"{weight_label} beyond limit",
                            "minutes": f"minutes to nearest {facility_one}", weight_col: weight_label})

people_word = weight_label.split(" (")[0]  # "people"

# Table number styles: people with thousands separators (38,140), minutes as "60 min",
# and the 2-hour shares as small bars so the worst towns stand out at a glance
PEOPLE_COL = st.column_config.NumberColumn(format="localized")
MIN_COL = st.column_config.NumberColumn(format="%.0f min")
PCT_COL = st.column_config.NumberColumn(format="%.0f%%")
BAR_COL = st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100)
area_note = " (selected area)" if filtered else ""
tab_towns, tab_upgrade, tab_brgy, tab_fac, tab_noroad, tab_about = st.tabs([
    "Cities & municipalities", "Where to upgrade", "Barangays", "Existing facilities",
    f"No road ({len(no_road)})", "About the data"])

with tab_noroad:
    st.markdown(f"**{len(no_road)} barangay(s) our road map does not reach{area_note}**")
    if len(no_road) == 0:
        st.caption("Every barangay here has a road connection in our model.")
    else:
        st.caption("These barangays have no road connection in our model, so no travel time could be "
                   "estimated. Some are islands that need a boat; others may have roads that are missing "
                   "on OpenStreetMap. Check each one locally: they need a boat or transport plan, not "
                   "necessarily a new facility.")
        st.dataframe(no_road[["barangay", "municipality", weight_col]].sort_values(weight_col, ascending=False)
                     .rename(columns={weight_col: weight_label}), hide_index=True, width="stretch",
                     column_config={weight_label: PEOPLE_COL})
with tab_towns:
    st.markdown(f"**Share of {people_word} within 1 and 2 hours, by city and municipality{area_note}**")
    st.caption(f"Travel time to the nearest {facility_one}, in both seasons. Fixed 1-hour and 2-hour "
               f"limits (the time-limit slider does not change this table), worst first. Median = the "
               f"middle barangay's travel time. Barangays with no road connection count as beyond."
               + (" What-if upgrades are included." if upgrades else ""))
    t_dry, t_rainy = (table, table_other) if season == "Dry season" else (table_other, table)
    town_tbl = helpers.town_summary(t_dry[t_dry["barangay_id"].isin(shown_ids)],
                                    t_rainy[t_rainy["barangay_id"].isin(shown_ids)], weight_col)
    # towns next to Negros Occidental: people there may use hospitals across the border (not in our model)
    town_tbl["border"] = ["Yes" if m in border_towns else "" for m in town_tbl["municipality"]]

    # Dry vs rainy chart ("dumbbell"): one row per town, an orange dot for the dry season and a
    # teal dot for the rainy season, joined by a line. A long line = rain makes a big difference.
    hours = st.radio("Chart: share of people within", [1, 2], horizontal=True,
                     format_func=lambda h: f"{h} hour{'s' if h > 1 else ''}",
                     help="Within 1 hour shows the effect of rain best. Within 2 hours is the global "
                          "benchmark for reaching C-section care (most towns are close to 100%).")
    dry_col, rainy_col = f"pct_{hours}h_dry", f"pct_{hours}h_rainy"
    limit_words = f"{hours} hour{'s' if hours > 1 else ''}"   # "2 hours"
    limit_adj = f"{hours}-hour"                                  # "2-hour access"

    # Takeaway title: the towns where rain cuts access the most (worked out from the data)
    drop = (town_tbl[dry_col] - town_tbl[rainy_col]).round(0)
    biggest = town_tbl.assign(drop=drop).query("drop >= 1").nlargest(3, "drop")
    if len(biggest) > 0:
        names_list = list(biggest["municipality"])
        names_text = names_list[0] if len(names_list) == 1 else ", ".join(names_list[:-1]) + " and " + names_list[-1]
        drops_text = ", ".join(f"{d:.0f}" for d in biggest["drop"])
        st.markdown(f"**Rain cuts {limit_adj} access most in {names_text}** "
                    f"(down {drops_text} percentage points from the dry season).")
    else:
        st.markdown(f"**Rain does not change {limit_adj} access in this area.**")
    st.caption("1 hour is shown first because it shows the effect of rain most clearly; 2 hours is the "
               "global benchmark for timely C-section care. Orange = dry season, teal = rainy season; "
               "where they are the same, the two dots overlap (hover over a dot to see both values).")

    order = town_tbl.sort_values(rainy_col)["municipality"].tolist()   # worst (rainy) at the top
    y = alt.Y("municipality:N", sort=order, title=None, axis=alt.Axis(labelOverlap=False, labelLimit=160))
    lines = alt.Chart(town_tbl).mark_rule(color="#b9c4c4", strokeWidth=3).encode(
        y=y, x=alt.X(f"{dry_col}:Q"), x2=alt.X2(f"{rainy_col}:Q"))
    dots_data = town_tbl.melt(id_vars=["municipality", "people"], value_vars=[dry_col, rainy_col],
                              var_name="season", value_name="pct")
    dots_data["season"] = dots_data["season"].map({dry_col: "Dry season", rainy_col: "Rainy season"})
    dots_data["within"] = (dots_data["pct"] / 100 * dots_data["people"]).round(-1)   # people, to the nearest 10
    # Same size and solid color for both seasons (size would wrongly suggest "more"), centered exactly
    # on the town's line. Where dry and rainy are equal the dots overlap (the hover card shows both).
    seasons = ["Dry season", "Rainy season"]
    dots = alt.Chart(dots_data).mark_circle(size=110, opacity=1, stroke="#ffffff", strokeWidth=1).encode(
        y=y,
        x=alt.X("pct:Q", title=f"% of {people_word} within {limit_words} of the nearest {facility_one}",
                scale=alt.Scale(domain=[0, 100]),
                axis=alt.Axis(values=list(range(0, 101, 10)), gridOpacity=0.5)),   # a tick every 10%
        color=alt.Color("season:N", scale=alt.Scale(domain=seasons, range=["#c2491d", "#047878"]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=[alt.Tooltip("municipality:N", title="City / municipality"),
                 alt.Tooltip("season:N", title="Season"),
                 alt.Tooltip("pct:Q", title=f"% within {limit_words}", format=".0f"),
                 alt.Tooltip("within:Q", title=f"{people_word.capitalize()} within {limit_words} (about)", format=",.0f"),
                 alt.Tooltip("people:Q", title=f"{people_word.capitalize()} in the town", format=",.0f")])
    # about 22 px per town, so every town name fits (otherwise the chart hides every other label)
    chart_height = max(200, 22 * len(order))
    st.altair_chart((lines + dots).properties(height=chart_height), width="stretch", height=chart_height + 70,
                    alt=f"Share of people within {limit_words} of care, dry vs rainy season, by town")
    near_border = [m for m in order if m in border_towns]
    if near_border:
        st.caption(f"Towns that border Negros Occidental: {', '.join(near_border)}. Our roads stop at the "
                   f"province border, so hospitals across it are left out: these towns may look farther "
                   f"from care than they are.")
    town_tbl = town_tbl[["municipality", "beyond_2h_rainy", "pct_2h_rainy", "pct_2h_dry", "pct_1h_rainy",
                         "pct_1h_dry", "median_min_rainy", "median_min_dry", "people", "border"]].rename(columns={
        "municipality": "city / municipality", "beyond_2h_rainy": f"{people_word} beyond 2 h (rainy)",
        "pct_2h_rainy": "% within 2 h (rainy)", "pct_2h_dry": "% within 2 h (dry)",
        "pct_1h_rainy": "% within 1 h (rainy)", "pct_1h_dry": "% within 1 h (dry)",
        "median_min_rainy": "median minutes (rainy)", "median_min_dry": "median minutes (dry)",
        "people": weight_label, "border": "borders Negros Occidental"})
    st.dataframe(town_tbl, hide_index=True, width="stretch", column_config={
        f"{people_word} beyond 2 h (rainy)": PEOPLE_COL, weight_label: PEOPLE_COL,
        "% within 2 h (rainy)": BAR_COL, "% within 2 h (dry)": BAR_COL,
        "% within 1 h (rainy)": PCT_COL, "% within 1 h (dry)": PCT_COL,
        "median minutes (rainy)": MIN_COL, "median minutes (dry)": MIN_COL})
    st.download_button("Download this table (CSV)", town_tbl.to_csv(index=False), "nanay_towns.csv")

with tab_upgrade:
    st.markdown(f"**The best 1, 2 or 3 facilities to upgrade ({season.lower()}){area_note}**")
    st.caption(f"Which rural health units, birthing homes or infirmaries, if upgraded to {facility_one}, "
               f"would bring the most {weight_label} within {threshold} min (Maximal Covering Location "
               f"Problem). Each row is the best set of that size, so a site in row 1 may be swapped out in "
               f"row 2. Press a button below the table to see that set on the map. "
               f"It shows where added capacity would help most, not a costed plan: the staff (e.g. an obstetrician and an anesthesiologist), operating room, blood supply and cost are not modelled.")
    best = best_sites_cached(level, threshold, season, level_scenario, tuple(shown_ids), weight_col)
    if all(b["gain"] == 0 for b in best):
        st.info(f"No upgrade of a single candidate brings more {weight_label} within {threshold} min here.")
    else:
        best_tbl = pd.DataFrame([{
            "sites": b["n"],
            f"more {people_word} within {threshold} min": b["gain"],
            "within the limit: now → after": f"{b['before']:.1f}% → {b['after']:.1f}%",
            "upgrade these facilities": "; ".join(place_label(c) for c in b["sites"]) or "-",
        } for b in best])
        st.dataframe(best_tbl, hide_index=True, width="stretch",
                     column_config={f"more {people_word} within {threshold} min": PEOPLE_COL})
        # one button per set: show it on the map as a what-if upgrade
        for col, b in zip(st.columns(len(best)), best):
            if b["gain"] > 0:
                col.button(f"⭐ Show the best {b['n']} on the map", key=f"show_set_{b['n']}", width="stretch",
                           on_click=show_upgrade_set, args=(b["sites"], b["gain"]))
        st.download_button("Download this table (CSV)", best_tbl.to_csv(index=False), "nanay_best_upgrades.csv")

with tab_brgy:
    st.markdown(f"**Barangay ranking: most {weight_label} beyond {threshold} min{area_note}**")
    st.caption("Select a row to make its birth-plan sheet.")
    picked = st.dataframe(show, hide_index=True, width="stretch", height=380,
                          on_select="rerun", selection_mode="single-row", column_config={
                              f"{weight_label} beyond limit": PEOPLE_COL, weight_label: PEOPLE_COL,
                              f"minutes to nearest {facility_one}": MIN_COL})
    if picked.selection.rows:
        b_id = ids_in_order[picked.selection.rows[0]]
        b = barangays[barangays["barangay_id"] == b_id].iloc[0]
        st.session_state["dash_place"] = (b["municipality"], b_id)  # the birth-plan page opens it
        st.page_link("app_pages/birth_plan.py", icon=":material/description:",
                     label=f"Open the birth-plan sheet for {b['barangay']}, {b['municipality']}")
    st.download_button("Download this table (CSV)", show.to_csv(index=False), "nanay_barangay_ranking.csv")

with tab_fac:
    st.markdown(f"**Who would lose access if one facility closed?{area_note}**")
    st.caption(f"For each {facility_one}: how many {weight_label} would no longer have one within "
               f"{threshold} min ({season.lower()}) if this facility closed. A high number means "
               f"there is no nearby backup. What-if upgrades are not included.")
    crit = crit_raw.copy()  # already calculated (and remembered) for the line under the cards
    crit = crit.merge(facilities[["nhfr_code", "facility_name", "city_municipality", "obstetric_level"]],
                      on="nhfr_code", how="left")
    crit["obstetric_level"] = crit["obstetric_level"].map(PIN_NAME)
    # ◆ = the province's own CEmONC sites (Bayawan and Guihulngan, see config.py)
    is_province_site = crit["facility_name"].isin(config.PROVINCE_CEMONC_SITES)
    crit.loc[is_province_site, "facility_name"] = crit.loc[is_province_site, "facility_name"] + " ◆"
    if is_province_site.any():
        st.caption("◆ = the province's own CEmONC sites (Bayawan and Guihulngan district hospitals). "
                   "Their numbers show how many people each siting choice keeps within reach.")
    crit["city_municipality"] = crit["city_municipality"].map(helpers.town_name)  # "CITY OF BAIS" -> "Bais City"
    # the number first (right after the name) so it is never cut off on narrow screens
    crit = crit[["facility_name", "people_losing_access", "city_municipality", "obstetric_level"]].rename(
        columns={"facility_name": "facility", "city_municipality": "city / municipality",
                 "obstetric_level": "level of care",
                 "people_losing_access": f"{weight_label} who would lose access"})
    st.dataframe(crit, hide_index=True, width="stretch",
                 column_config={f"{weight_label} who would lose access": PEOPLE_COL})
    st.download_button("Download this table (CSV)", crit.to_csv(index=False), "nanay_critical_facilities.csv")

with tab_about:
    n_assumed = int((facilities["level_basis"] != "confirmed").sum()) if "level_basis" in facilities.columns else 0
    n_rhu = int((candidates["facility_type"] == "Rural Health Unit").sum())
    st.markdown(f"""
**What the map shows:** each colored area is a barangay. Its color is the estimated travel time
from the barangay center to the nearest facility at the selected level, along OpenStreetMap roads,
compared with the time limit you chose: up to half the limit, up to the limit, over the limit,
or no road connection. Hover over an area to see its population. Pins are facilities; an orange
star is a what-if upgrade.

**Assumptions (change them in `config.py`):**
- Speeds by road type (dry): {config.DRY_SPEEDS_KMH}
- Rainy season slows each road type by a factor; dirt roads slow down more.
- Walking speed from barangay center to the nearest road: {config.WALK_SPEED_KMH} km/h.
- A month with {config.RAINY_MONTH_MM_THRESHOLD} mm or more normal rainfall uses rainy-season times.
- Counting: **{weight_label}**.
- Care levels: {len(facilities) - n_assumed} of {len(facilities)} facility levels are confirmed; the rest are
  assumed from the DOH facility type: {config.LEVEL_BY_TYPE}; other types count as 'none'. Hospitals must have a surgery room,
  maternity care and a blood station under DOH AO 2012-0012. The 'Strict' scenario (More options)
  counts private hospitals as {config.STRICT_PRIVATE_HOSPITAL_LEVEL} instead.
  With the current settings, the other scenario gives **{s_scenario['not_covered']:,.0f}** {weight_label}
  beyond the limit (this scenario: {s1['not_covered']:,.0f}){": the same, so this result does not depend on how private hospitals are counted" if s_scenario['not_covered'] == s1['not_covered'] else ""}.
- Best facility to upgrade: Maximal Covering Location Problem (Church & ReVelle, 1974): picks the
  site(s) that bring the most people currently beyond the time limit within it.
- Sensitivity check: the headline is counted again with every speed
  {round(config.SENSITIVITY_SPEED_CHANGE * 100)}% slower and faster (the "Range" line in the first tile).

**Not in this version** (no data for it yet): women aged 15-49 (we count all people), travel
off the roads over terrain, boat trips to islands, ambulance staging, and a check against real trips.

**Known limits:**
- Care levels of {n_assumed} of {len(facilities)} facilities are ASSUMED from facility type, not an official DOH designation.
- Roads stop at the province border, so hospitals in Negros Occidental are left out. Gaps in the
  {len(border_towns)} border towns ({", ".join(sorted(border_towns))}) may be overstated.
- Rural health units: the {n_rhu} on our list are only upgrade candidates; they count as a place to
  give birth only if they also hold a separate birthing-home licence in the DOH registry. Many rural
  health units are part of the BEmONC network, so gaps for basic emergency care and for any place to
  give birth may be overstated.
- Facilities may not be staffed or open 24 hours.
- Islands that need a boat are shown as "no road connection".
- Results describe areas, not individual women.

**AI assistance:** this app was developed with help from Claude, an AI assistant made by Anthropic,
which helped write and test the code, the data-processing scripts and the documentation. The team
defined the project and its users, collected and checked the data, made the design decisions and
reviewed the results.
""")
    # Month context: only describe the optional files that are actually loaded
    month_notes = [note for note, data in [
        ("Births: PSA registered live births by month (historical averages, not real-time). We have "
         "no data on facility capacity, so the app never says a facility is full.", births),
        ("Weather: PAGASA climatological normals for the station nearest to Negros Oriental.", rainfall),
        ("Equity gap: PSA small-area poverty estimates at city/municipality level. It compares "
         "municipalities, not barangays or individual families.", poverty)] if data is not None]
    if month_notes:
        st.markdown("**Month context:**\n" + "\n".join(f"- {n}" for n in month_notes))

# ---------------------------------------------------------------
# Data sources, with dates (always visible at the very bottom)
# ---------------------------------------------------------------
st.caption("**Data:** facilities from the DOH National Health Facility Registry (Oct 15, 2026), "
           "locations checked by our team · roads from OpenStreetMap via Geofabrik (Oct 18, 2026) · "
           "barangay boundaries from NAMRIA/PSA via HDX (v03, 2025) · population from the PSA 2020 Census. "
           "Map tiles © OpenStreetMap contributors" + (", © CARTO." if map_mode == "3D" else "."))
