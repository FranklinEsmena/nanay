# tests/test_helpers.py
# Small checks that our core calculations do what we think.
# Run from the project folder:  python -m pytest tests

import sys
from pathlib import Path

import networkx as nx
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import helpers


def test_level_rank_order():
    assert helpers.level_rank("birthing") < helpers.level_rank("BEmONC") < helpers.level_rank("CEmONC")
    assert helpers.level_rank("none") == 0


def test_cemonc_also_counts_as_bemonc():
    fac = pd.DataFrame({"nhfr_code": ["A", "B"], "obstetric_level": ["CEmONC", "birthing"]})
    assert helpers.facilities_serving(fac, "BEmONC") == ["A"]
    assert sorted(helpers.facilities_serving(fac, "birthing")) == ["A", "B"]


def test_travel_time_on_a_road():
    # one 30 km primary road at 45 km/h (dry) should take 40 minutes
    G = nx.MultiDiGraph()
    G.add_edge(1, 2, length=30000, highway="primary")
    helpers.add_travel_times(G)
    assert abs(G[1][2][0]["time_dry"] - 40) < 0.01
    assert G[1][2][0]["time_rainy"] > G[1][2][0]["time_dry"]


def test_dirt_road_slower_when_raining():
    G = nx.MultiDiGraph()
    G.add_edge(1, 2, length=10000, highway="track", surface="dirt")
    G.add_edge(3, 4, length=10000, highway="track", surface="paved")
    helpers.add_travel_times(G)
    assert G[1][2][0]["time_rainy"] > G[3][4][0]["time_rainy"]


def test_nearest_facility_picks_fastest_and_handles_no_road():
    matrix = pd.DataFrame({"A": [10.0, None], "B": [5.0, None]}, index=[1, 2])
    near = helpers.nearest_facility(matrix, ["A", "B"])
    assert near.loc[1, "minutes"] == 5.0 and near.loc[1, "nearest_code"] == "B"
    assert pd.isna(near.loc[2, "minutes"])


def test_best_sites_covers_the_bigger_village():
    # Two uncovered barangays; site X reaches the big one, site Y reaches the small one.
    barangays = pd.DataFrame({"barangay_id": [1, 2], "lat": [0, 0], "lon": [0, 0],
                              "municipality": ["M", "M"], "barangay": ["Big", "Small"],
                              "population": [5000, 100]})
    facilities = pd.DataFrame({"nhfr_code": ["H"], "facility_name": ["Hospital"], "obstetric_level": ["CEmONC"]})
    matrix = pd.DataFrame({"H": [300.0, 300.0], "X": [60.0, 400.0], "Y": [400.0, 60.0]}, index=[1, 2])
    table = helpers.access_table(barangays, facilities, matrix, "CEmONC", 120)
    chosen, gain = helpers.best_sites(table, matrix, ["X", "Y"], 120, 1, "population")
    assert chosen == ["X"] and gain == 5000


def test_travel_bands_follow_the_time_limit():
    assert [helpers.travel_band(m, 120) for m in [30, 60, 61, 120, 121]] == ["near", "near", "mid", "mid", "far"]
    assert [helpers.travel_band(m, 90) for m in [45, 46, 91]] == ["near", "mid", "far"]
    assert helpers.travel_band(float("nan"), 90) == "none"
    assert helpers.band_labels(120) == {"near": "under 1 h", "mid": "1 h–2 h", "far": "over 2 h", "none": "no road"}
    assert helpers.band_labels(90)["mid"] == "45 min–90 min"


def test_critical_facilities_counts_people_with_no_other_option():
    # Village 1 (100 people) can reach A (30 min) and B (90 min); village 2 (50) only B (60 min).
    # Closing A: village 1 still has B -> 0 lose access. Closing B: village 2 loses -> 50.
    barangays = pd.DataFrame({"barangay_id": [1, 2], "municipality": ["M", "M"], "barangay": ["V1", "V2"],
                              "lat": [0, 0], "lon": [0, 0], "population": [100, 50]})
    facilities = pd.DataFrame({"nhfr_code": ["A", "B"], "facility_name": ["A", "B"],
                               "obstetric_level": ["CEmONC", "CEmONC"]})
    matrix = pd.DataFrame({"A": [30.0, 300.0], "B": [90.0, 60.0]}, index=[1, 2])
    out = helpers.critical_facilities(barangays, facilities, matrix, "CEmONC", 120, "population")
    assert out["nhfr_code"].tolist() == ["B", "A"]
    assert out["people_losing_access"].tolist() == [50, 0]


def test_route_points_follows_fastest_road_and_curve():
    # Two ways from 1 to 3: a slow direct road, or a fast road through 2 (with a bend stored
    # in the "wrong" direction). The route must go through 2 and follow the bend.
    from shapely.geometry import LineString
    G = nx.MultiGraph()
    G.add_node(1, x=0.0, y=0.0); G.add_node(2, x=1.0, y=0.0); G.add_node(3, x=2.0, y=0.0)
    G.add_edge(1, 3, time_dry=100)
    G.add_edge(1, 2, time_dry=5, geometry=LineString([(1.0, 0.0), (0.5, 0.5), (0.0, 0.0)]))  # stored 2 -> 1
    G.add_edge(2, 3, time_dry=5)
    pts = helpers.route_points(G, 1, 3, "time_dry")
    assert pts == [(0.0, 0.0), (0.5, 0.5), (0.0, 1.0), (0.0, 2.0)]   # (lat, lon) pairs
    G.add_node(9, x=5.0, y=5.0)                                        # not connected
    assert helpers.route_points(G, 1, 9, "time_dry") == []


# ---------------------------------------------------------------
# Care-level assumption and scenarios
# ---------------------------------------------------------------
def test_assign_levels_confirmed_wins_and_types_fill_blanks():
    fac = pd.DataFrame({
        "nhfr_code": ["H1", "H2", "H3", "I1", "B1", "R1"],
        "facility_type": ["Hospital", "Hospital", "Hospital", "Infirmary", "Birthing Home", "Rural Health Unit"],
        "ownership": ["Government", "Private", "Private", "Government", "Private", "Government"],
        "obstetric_level": ["", "", "CEmONC", "", "", "BEmONC"],   # H3 and R1 confirmed by the team
    })
    out = helpers.assign_levels(fac).set_index("nhfr_code")
    assert out["level"].to_dict() == {"H1": "CEmONC", "H2": "CEmONC", "H3": "CEmONC",
                                      "I1": "BEmONC", "B1": "birthing", "R1": "BEmONC"}
    assert out.loc["R1", "level_basis"] == "confirmed" and out.loc["H1", "level_basis"] != "confirmed"
    # strict: only the ASSUMED private hospital (H2) drops a level; confirmed H3 stays CEmONC
    assert out.loc["H2", "level_strict"] == "BEmONC"
    assert out.loc["H3", "level_strict"] == "CEmONC" and out.loc["H1", "level_strict"] == "CEmONC"


def test_use_scenario_switches_level_and_handles_demo_data():
    fac = pd.DataFrame({"nhfr_code": ["A"], "obstetric_level": ["CEmONC"],
                        "level": ["CEmONC"], "level_strict": ["BEmONC"]})
    assert helpers.use_scenario(fac, "strict")["obstetric_level"].iloc[0] == "BEmONC"
    assert helpers.use_scenario(fac, "type")["obstetric_level"].iloc[0] == "CEmONC"
    demo = pd.DataFrame({"nhfr_code": ["A"], "obstetric_level": ["CEmONC"]})   # no scenario columns
    assert helpers.use_scenario(demo, "strict")["obstetric_level"].iloc[0] == "CEmONC"


# ---------------------------------------------------------------
# Context KPIs
# ---------------------------------------------------------------
def test_load_optional_csv_handles_missing_empty_and_wrong_columns(tmp_path):
    cols = ["month", "normal_rainfall_mm", "rainy_days"]
    assert helpers.load_optional_csv(tmp_path / "nope.csv", cols) is None      # missing
    (tmp_path / "empty.csv").write_text("month,normal_rainfall_mm,rainy_days\n")
    assert helpers.load_optional_csv(tmp_path / "empty.csv", cols) is None     # headers only
    (tmp_path / "wrong.csv").write_text("month,rain\n1,50\n")
    assert helpers.load_optional_csv(tmp_path / "wrong.csv", cols) is None     # wrong columns
    (tmp_path / "ok.csv").write_text("month,normal_rainfall_mm,rainy_days\n1,50,6\n")
    assert len(helpers.load_optional_csv(tmp_path / "ok.csv", cols)) == 1


def test_seasonal_demand_compares_month_with_average_month():
    # Two years. Month 1 averages 120 births, month 2 averages 80 -> average month = 100
    births = pd.DataFrame({"year": [2020, 2020, 2021, 2021], "month": [1, 2, 1, 2],
                           "registered_births": [110, 70, 130, 90]})
    d = helpers.seasonal_demand(births, 1)
    assert d["month_avg"] == 120 and d["average_month"] == 100
    assert abs(d["pct_vs_average"] - 20) < 1e-9
    assert helpers.seasonal_demand(births, 7) is None   # no data for July


def test_month_weather_uses_threshold():
    rain = pd.DataFrame({"month": [1, 8], "normal_rainfall_mm": [80.0, 250.0], "rainy_days": [8, 20]})
    assert helpers.month_weather(rain, 1, 200)["is_rainy"] is False
    assert helpers.month_weather(rain, 8, 200)["is_rainy"] is True
    assert helpers.month_weather(rain, 8, 200)["rainy_days"] == 20
    assert helpers.month_weather(rain, 3, 200) is None


def test_backup_coverage_counts_only_two_or_more_facilities():
    # Barangay 1 (1000 people) has 2 facilities within 120 min, barangay 2 (3000) has only 1,
    # barangay 3 (1000) has no road -> 1000 / 5000 = 20%
    table = pd.DataFrame({"barangay_id": [1, 2, 3], "population": [1000, 3000, 1000]})
    matrix = pd.DataFrame({"A": [30.0, 60.0, None], "B": [90.0, 200.0, None]}, index=[1, 2, 3])
    assert helpers.backup_coverage(table, matrix, ["A", "B"], 120, "population") == 20


def test_town_name_uses_one_style():
    assert helpers.town_name("City of Bayawan (Tulong)") == "Bayawan City"
    assert helpers.town_name("Dumaguete City (Capital)") == "Dumaguete City"
    assert helpers.town_name("CITY OF DUMAGUETE") == "Dumaguete City"
    assert helpers.town_name("Bais City") == "Bais City"
    assert helpers.town_name("Amlan (Ayuquitan)") == "Amlan"
    assert helpers.town_name("SANTA CATALINA") == "Santa Catalina"


def test_simple_place_name_matches_registry_and_psa_spellings():
    assert helpers.simple_place_name("CITY OF BAIS") == helpers.simple_place_name("Bais City")
    assert helpers.simple_place_name("Sta. Catalina") == "SANTA CATALINA"
    assert helpers.simple_place_name("Dumaguete City (Capital)") == "DUMAGUETE"


def test_equity_gap_poorest_vs_least_poor():
    # 5 towns, 20% groups -> 1 town each. Poorest town (P, 50%) has 0% coverage,
    # least-poor town (R, 5%) has 100% -> gap = 100 points. Town "Lost" is not in the poverty file.
    table = pd.DataFrame({
        "municipality": ["P", "Q", "S", "T", "R", "Lost"],
        "population": [100, 100, 100, 100, 100, 100],
        "within": [False, True, True, False, True, True],
    })
    poverty = pd.DataFrame({
        "municipality": ["P", "Q", "S", "T", "R", "P"],
        "poverty_incidence_pct": [50, 30, 20, 10, 5, 99],
        "year": [2021, 2021, 2021, 2021, 2021, 2018],   # older 2018 row must be ignored
    })
    g = helpers.equity_gap(table, poverty, "population", 0.20)
    assert g["n_each"] == 1 and g["year"] == 2021
    assert g["poorest_pct"] == 0 and g["least_poor_pct"] == 100 and g["gap_pts"] == 100
    assert g["unmatched"] == ["LOST"]


def _two_towns():
    """Three barangays in two towns, one hospital H (travel times in minutes)."""
    barangays = pd.DataFrame({"barangay_id": [1, 2, 3], "lat": [0, 0, 0], "lon": [0, 0, 0],
                              "municipality": ["Near", "Far", "Far"], "barangay": ["A", "B", "C"],
                              "population": [1000, 300, 100]})
    facilities = pd.DataFrame({"nhfr_code": ["H"], "facility_name": ["Hospital"], "obstetric_level": ["CEmONC"]})
    return barangays, facilities


def test_town_summary_shares_and_worst_first():
    barangays, facilities = _two_towns()
    dry = pd.DataFrame({"H": [30.0, 90.0, None]}, index=[1, 2, 3])     # C has no road
    rainy = pd.DataFrame({"H": [50.0, 130.0, None]}, index=[1, 2, 3])
    t_dry = helpers.access_table(barangays, facilities, dry, "CEmONC", 120)
    t_rainy = helpers.access_table(barangays, facilities, rainy, "CEmONC", 120)
    s = helpers.town_summary(t_dry, t_rainy, "population")
    assert list(s["municipality"]) == ["Far", "Near"]          # worst town first
    far = s.iloc[0]
    assert far["pct_2h_dry"] == 75.0 and far["pct_2h_rainy"] == 0.0  # 300 of 400 people in the dry season
    assert far["beyond_2h_rainy"] == 400                        # no-road barangay counts as beyond


def test_sensitivity_slower_speeds_mean_more_people_beyond():
    barangays, facilities = _two_towns()
    matrix = pd.DataFrame({"H": [100.0, 110.0, 200.0]}, index=[1, 2, 3])
    r = helpers.sensitivity_range(barangays, facilities, matrix, "CEmONC", 120, "population", 0.20)
    # 20% slower: 100 -> 125 and 110 -> 137.5 min, so everyone is beyond 2 h
    assert r["slower"] == 1400
    # 20% faster: 200 -> 166.7 min, still beyond; the other two stay within
    assert r["faster"] == 100


def test_facility_name_keeps_short_forms():
    assert helpers.facility_name("MABINAY RHU 1 BIRTHING FACILITY") == "Mabinay RHU 1 Birthing Facility"
    assert helpers.facility_name("ALLIED CARE EXPERTS (ACE) DUMAGUETE DOCTORS, INC.") == \
        "Allied Care Experts (ACE) Dumaguete Doctors, Inc."
    assert helpers.facility_name("SUMC FOUNDATION, INC.") == "SUMC Foundation, Inc."
