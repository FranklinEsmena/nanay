# app.py
# NANAY app: the starting file. It only sets up the two pages and the links
# between them (at the top of the screen). The pages themselves are in app_pages/.
#   - Planning dashboard (for provincial and city health offices: coverage, map, upgrades)
#   - Birth-plan sheets  (for midwives and barangay health workers: printable sheets)
# Shared data loading is in app_data.py.
#
# Run from the project folder:  streamlit run app.py
#
# The app does NOT do heavy map routing. It only reads the travel-time tables
# made by scripts 01-04, so it stays fast during the live demo.

import streamlit as st

import app_data

st.set_page_config(page_title="NANAY", page_icon=str(app_data.ICON), layout="wide")

# ---------------------------------------------------------------
# Brand colors from the NANAY logo (used by BOTH pages; the map keeps its own colors)
#   teal   #047878  controls, headings, the upgrade number (a darker shade of the logo's
#                   #28acab so text on white stays readable: contrast 5.1 : 1)
#   orange #c2491d  the main action buttons and the line under titles (a darker shade of
#                   the wordmark's #f06b3a: white text on it has contrast 4.7 : 1)
# (The result tiles above the map are styled in app_pages/dashboard.py.)
# Background: a soft "sunrise" fade, orange-pink at the top and teal at the bottom,
# plain off-white in the middle where the map is.
# ---------------------------------------------------------------
st.html("""
<style>
  .stApp {
    background: linear-gradient(180deg, #fde0cf 0%, #fdeeec 9%, #f9fafa 22%,
                                #f9fafa 82%, #d9f0ef 100%);
  }
  /* top bar (page links + menu): a soft peach that matches the top of the page, slightly see-through
     and blurred, so content scrolling underneath never shows through as overlapping text */
  [data-testid="stHeader"] {
    background: rgba(253, 228, 214, 0.86); backdrop-filter: blur(6px);
    box-shadow: 0 1px 0 rgba(30, 43, 43, 0.06);
  }
  .brand-title { border-bottom: 3px solid #f06b3a; padding-bottom: 2px; display: inline-block; }
  .brand-heading { color: #047878; font-weight: 700; }
  /* the main action buttons (given key="main_action...") in brand orange */
  [class*="st-key-main_action"] button {
    background: #c2491d; color: #ffffff; border: 1px solid #c2491d;
  }
  [class*="st-key-main_action"] button:hover { background: #a63d17; border-color: #a63d17; color: #ffffff; }
  [class*="st-key-main_action"] button p { color: #ffffff; }
  /* an opened folded section gets a teal edge, so you can see which one you are in */
  [data-testid="stExpander"] details[open] { border-left: 3px solid #047878; }
</style>
""")

# Streamlit forgets a page's widget values when you switch to the other page. Saving them
# again here (this file runs on every page, every time) keeps your choices, so the dashboard
# is still the same when you come back. Names = the widget keys in app_pages/.
KEEP = ["level", "season_choice", "threshold", "towns", "brgy_filter", "route_from", "map_mode",
        "level_scenario", "n_suggest", "upgrades", "bp_town", "bp_brgy"]
for k in KEEP:
    if k in st.session_state:
        st.session_state[k] = st.session_state[k]

pages = [
    st.Page("app_pages/dashboard.py", title="Planning dashboard", icon=":material/map:", default=True),
    st.Page("app_pages/birth_plan.py", title="Birth-plan sheets", icon=":material/description:"),
]
st.navigation(pages, position="top").run()
