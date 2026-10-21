# 05_optimize.py
# Step 5: where would upgrading 1, 2 or 3 facilities cover the most people?
# Also: how much does each EXISTING top-level facility contribute? (tests past siting decisions)
#
# Inputs : data/processed/*.csv from steps 1-4
# Outputs: outputs/optimization_results.csv
#          outputs/existing_facility_contribution.csv
#
# Run from the project folder:  python scripts/05_optimize.py

import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
import helpers

barangays = pd.read_csv(config.PROCESSED / "barangays.csv")
all_facilities = pd.read_csv(config.PROCESSED / "facilities.csv", dtype={"nhfr_code": str})
candidates = pd.read_csv(config.PROCESSED / "candidates.csv", dtype={"nhfr_code": str})
weight_col, weight_label = helpers.weight_column(barangays)
names = dict(zip(pd.concat([all_facilities, candidates])["nhfr_code"],
                 pd.concat([all_facilities, candidates])["facility_name"]))

level = "CEmONC"
T = config.THRESHOLD_MIN
rows = []

matrices = {s: pd.read_csv(config.PROCESSED / f"time_matrix_{s}.csv", index_col=0) for s in ["dry", "rainy"]}

# Two care-level scenarios: "type" = main assumption, "strict" = only government hospitals are CEmONC
scenario_runs = [(sc, se) for sc in ["type", "strict"] for se in ["dry", "rainy"]]
for scenario, season in scenario_runs:
    facilities = helpers.use_scenario(all_facilities, scenario)
    matrix = matrices[season]
    table = helpers.access_table(barangays, facilities, matrix, level, T)
    base = helpers.coverage_summary(table, weight_col)
    print(f"\n[{scenario} / {season}] Now: {base['pct_covered']:.1f}% of {weight_label} within {T} min of {level}")

    # candidates = facilities that are not already at this level
    already = helpers.facilities_serving(facilities, level)
    cand_codes = [c for c in candidates["nhfr_code"] if c not in already]

    for n in range(1, config.MAX_NEW_SITES + 1):
        chosen, gain = helpers.best_sites(table, matrix, cand_codes, T, n, weight_col)
        new_pct = 100 * (base["covered"] + gain) / base["total"]
        if gain == 0:
            site_text = "(no candidate site improves coverage)"
        else:
            site_text = "; ".join(names.get(c, c) for c in chosen)
        print(f"  Upgrade {n}: +{gain:,.0f} {weight_label} -> {new_pct:.1f}%  | {site_text}")
        rows.append({
            "level_scenario": scenario, "season": season, "level": level, "threshold_min": T,
            "sites_added": n, "chosen_sites": site_text,
            "newly_covered": gain, "coverage_before_pct": round(base["pct_covered"], 1),
            "coverage_after_pct": round(new_pct, 1),
        })

config.OUTPUTS.mkdir(parents=True, exist_ok=True)
pd.DataFrame(rows).to_csv(config.OUTPUTS / "optimization_results.csv", index=False)

# ---- How much does each existing CEmONC facility matter? (remove it and see who loses access) ----
# (main scenario, dry season)
facilities = helpers.use_scenario(all_facilities, "type")
matrix = matrices["dry"]
table_all = helpers.access_table(barangays, facilities, matrix, level, T)
contrib = []
for code in helpers.facilities_serving(facilities, level):
    without = facilities[facilities["nhfr_code"] != code]
    t = helpers.access_table(barangays, without, matrix, level, T)
    lost = table_all.loc[table_all["within"] & ~t["within"], weight_col].sum()
    contrib.append({"facility": names.get(code, code), "people_who_would_lose_2h_access": lost})
pd.DataFrame(contrib).to_csv(config.OUTPUTS / "existing_facility_contribution.csv", index=False)
print("\nSaved outputs/optimization_results.csv and outputs/existing_facility_contribution.csv")
