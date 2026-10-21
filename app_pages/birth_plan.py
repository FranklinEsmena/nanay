# app_pages/birth_plan.py
# Page 2 of the app: printable birth-plan sheets for barangay health stations.
# For midwives and barangay health workers, so it is kept separate from the
# planning dashboard. Opens the barangay picked on the dashboard, if any.

import datetime
import html

import pandas as pd
import streamlit as st
from fpdf import FPDF

import app_data
import config
import helpers

barangays, facilities, candidates, matrices, names = app_data.load_or_stop()

# Header in the same style as the dashboard
logo_col, title_col = st.columns([1, 9], vertical_alignment="center")
logo_col.image(str(app_data.LOGO), width=76)
title_col.markdown(
    "<div><span class='brand-title' style='font-size:1.35rem;font-weight:700'>Birth-Plan Sheets · Negros Oriental"
    "</span><br>"
    "<span style='font-size:0.9rem;color:#3d4d4d'><b>For midwives and barangay health workers:</b> a one-page "
    "sheet to fill in a mother's birth plan: the nearest facility for each level of care, its phone number, and "
    "travel times in the dry and rainy seasons. Print one barangay, or a whole town at once.</span></div>",
    unsafe_allow_html=True)
app_data.demo_banner()


NO_ROAD = "No road connection"


def facility_for_sheet(barangay_id, lvl, rank=0):
    """The nearest (rank 0) or second-nearest (rank 1) CURRENT facility at a level, with dry and
    rainy minutes (no what-if upgrades), whether its care level is only assumed, and its phone.
    No road at all -> the "No road connection" row; no second facility -> None."""
    codes = [c for c in helpers.facilities_serving(facilities, lvl) if c in matrices["Dry season"].columns]
    times = matrices["Dry season"].loc[barangay_id, codes].dropna().sort_values()
    if len(times) <= rank:
        return (NO_ROAD, None, None, False, "") if rank == 0 else None
    code = times.index[rank]
    dry = matrices["Dry season"].loc[barangay_id, code]
    rainy = matrices["Rainy season"].loc[barangay_id, code]
    row = facilities[facilities["nhfr_code"] == code].iloc[0]
    assumed = "level_basis" in facilities.columns and row["level_basis"] != "confirmed"
    phone = row["phone"] if "phone" in facilities.columns and pd.notna(row["phone"]) else ""
    return names.get(code, code), dry, rainy, assumed, str(phone).strip()


def round5(x):
    return "-" if x is None or pd.isna(x) else f"about {int(5 * round(x / 5))} min"


# Two-step picker, like the dashboard: city/municipality first, then its barangays.
# It opens the place picked on the planning dashboard (dash_place = town, barangay), but only
# when that pick CHANGES: a barangay chosen here stays when you come back from the dashboard
# without changing anything there. (app.py keeps bp_town / bp_brgy between pages.)
towns = sorted(barangays["municipality"].unique())
dash_town, dash_brgy = st.session_state.get("dash_place", (None, None))
from_dashboard = False
if st.session_state.get("_bp_applied") != (dash_town, dash_brgy):
    st.session_state["_bp_applied"] = (dash_town, dash_brgy)
    if dash_town is not None:
        st.session_state["bp_town"] = dash_town
        if dash_brgy is not None:
            st.session_state["bp_brgy"] = dash_brgy
        from_dashboard = True
if st.session_state.get("bp_town") not in towns:
    st.session_state["bp_town"] = towns[0]

town_col, brgy_col = st.columns(2)
town = town_col.selectbox("City / municipality", towns, key="bp_town")
in_town = barangays[barangays["municipality"] == town].sort_values("barangay")
brgy_ids = [int(i) for i in in_town["barangay_id"]]
brgy_label = dict(zip(brgy_ids, in_town["barangay"]))
if st.session_state.get("bp_brgy") not in brgy_ids:  # a new town: start at its first barangay
    st.session_state["bp_brgy"] = brgy_ids[0]
b_id = brgy_col.selectbox("Barangay", brgy_ids, format_func=brgy_label.get, key="bp_brgy")
if from_dashboard:
    st.caption("Opened on the place you picked on the planning dashboard.")

b_row = barangays[barangays["barangay_id"] == b_id].iloc[0]
brgy_name, muni = b_row["barangay"], b_row["municipality"]

# Binisaya labels: checked by a native speaker on the team. Lines without Binisaya are English only.
LEVELS = [("birthing", "Birthing facility / Paanakan"),
          ("BEmONC", "Basic emergency care (BEmONC)"),
          ("CEmONC", "Caesarean & blood transfusion (CEmONC)")]
BACKUP_LABEL = "Backup for caesarean & blood, if the nearest is full or the road is closed"


def sheet_data(barangay_id):
    """Everything on one barangay's sheet:
    rows        one row per facility (if the same facility is the nearest for several levels,
                common for hospitals, it is listed once with all its levels)
    any_assumed True if any listed care level is only estimated from the facility type
    no_road     True if the barangay has no road connection in our map (islands, missing roads)"""
    rows = {}  # facility name -> row details (dicts keep the order they were added)
    picks = [(lvl, label, 0) for lvl, label in LEVELS] + [("CEmONC", BACKUP_LABEL, 1)]  # 1 = second nearest
    for lvl, label, rank in picks:
        place = facility_for_sheet(barangay_id, lvl, rank)
        if place is None:
            continue
        fname, dry, rainy, assumed, phone = place
        if fname in rows:
            rows[fname]["labels"].append(label)
        else:
            rows[fname] = {"labels": [label], "dry": dry, "rainy": rainy, "assumed": assumed, "phone": phone}
    no_road = NO_ROAD in rows
    return {"rows": rows, "any_assumed": any(r["assumed"] for r in rows.values()), "no_road": no_road}


def sheet_notes(any_assumed):
    """The small print at the bottom of the sheet (same text on screen and in the PDF)."""
    notes = []
    if any_assumed:
        notes.append("* The care level of this facility is estimated from its type of license, not officially "
                     "confirmed. Ask your midwife or Rural Health Unit which facility to go to for your birth plan.")
    notes.append("Travel times are for a vehicle on the road, plus the walk from the barangay center to the "
                 "nearest road. They are estimates from a computer model (NANAY) and can be longer in bad "
                 "weather. In an emergency, go to the nearest facility immediately.")
    notes.append("Facility phone numbers are from the DOH National Health Facility Registry; check them before "
                 "you need them. Write in any missing number.")
    notes.append(f"Data: facilities as of {config.FACILITY_DATA_DATE}, roads as of {config.ROAD_DATA_DATE}. "
                 f"Sheet made {datetime.date.today():%d %b %Y}.")
    return notes


NO_ROAD_TEXT = ("No road connection in our map: this barangay may need a boat or other transport to reach "
                "care. Arrange it in advance with your midwife and barangay.")
FILL_IN_TEXT = "Fill in with your midwife before your due date."
# "My birth plan" write-in lines; two labels on one line share it
MY_PLAN = [("Name", "Due date"), ("Where I will give birth",), ("Transport: who will drive, and their number",),
           ("Companion", "Blood donor (name, number)"), ("Money / PhilHealth",)]


data = sheet_data(b_id)
rows, any_assumed = data["rows"], data["any_assumed"]
rows_html = ""
for fname, row in rows.items():
    star = " *" if row["assumed"] else ""
    # no number in the registry -> a blank line to write it in by hand
    phone_cell = html.escape(row["phone"]) if row["phone"] else "<span class='blank'></span>"
    levels = "<br>".join(html.escape(l) for l in row["labels"])
    rows_html += (f"<tr><td>{levels}</td><td>{html.escape(str(fname))}{star}</td>"
                  f"<td>{phone_cell}</td><td>{round5(row['dry'])}</td><td>{round5(row['rainy'])}</td></tr>")

if any_assumed:
    st.warning("Facilities marked * have an estimated care level (from their facility type), not an "
               "official BEmONC/CEmONC designation. The printed sheet says this too.")

no_road_html = f"<p class='box'><b>{NO_ROAD_TEXT}</b></p>" if data["no_road"] else ""
plan_html = "".join(
    "<div class='pair'>" + "".join(f"<div>{html.escape(label)}:<div class='line'></div></div>" for label in line)
    + "</div>" for line in MY_PLAN)
notes_html = "".join(f"<p class='small'>{html.escape(n)}</p>" for n in sheet_notes(any_assumed))

sheet = f"""
<html><head><meta charset='utf-8'><style>
  body {{ font-family: Arial, sans-serif; margin: 24px; color: #222; }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  h3 {{ margin: 16px 0 4px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
  td, th {{ border: 1px solid #999; padding: 8px; font-size: 14px; text-align: left; }}
  .line {{ border-bottom: 1px solid #555; height: 24px; margin: 2px 0 8px; }}
  .pair {{ display: flex; gap: 24px; }}
  .pair > div {{ flex: 1; }}
  .small {{ font-size: 11px; color: #555; margin: 4px 0; }}
  .hint {{ font-size: 12px; color: #555; margin: 0 0 6px; }}
  .box {{ border: 1px solid #555; padding: 8px; font-size: 13px; }}
  .blank {{ display: inline-block; width: 110px; border-bottom: 1px solid #555; height: 14px; }}
</style></head><body>
  <h1>Birth plan guide / Giya sa plano sa pagpanganak</h1>
  <div>Barangay {html.escape(str(brgy_name))}, {html.escape(str(muni))}</div>
  <table>
    <tr><th>Level of care</th><th>Nearest facility / Pinakaduol nga pasilidad</th>
        <th>Phone / Numero</th><th>Dry season / Ting-init</th><th>Rainy season / Ting-ulan</th></tr>
    {rows_html}
  </table>
  {no_road_html}
  <h3>Emergency numbers / Mga numero sa emerhensya</h3>
  <p class='hint'>{FILL_IN_TEXT}</p>
  <div><b>National emergency hotline: 911</b></div>
  <div class='pair'><div>Ambulance / Ambulansya:<div class='line'></div></div>
                    <div>Midwife / Mananabang:<div class='line'></div></div></div>
  <div>Barangay hall:</div><div class='line'></div>
  <h3>My birth plan</h3>
  <p class='hint'>{FILL_IN_TEXT}</p>
  {plan_html}
  {notes_html}
</body></html>
"""


def safe(text):
    """The PDF's built-in font only knows Western European letters (Ñ is fine);
    replace anything else with '?' instead of crashing."""
    return str(text).encode("latin-1", "replace").decode("latin-1")


def write_in_lines(pdf, lines):
    """Labels with a line to write on; two labels on one line share the page width."""
    full = pdf.w - pdf.l_margin - pdf.r_margin
    for line in lines:
        width = full / len(line)
        for label in line:
            pdf.cell(width - 4, 8, safe(f"{label}:  "), new_x="RIGHT", new_y="TOP")
            pdf.cell(4, 8, "")
        pdf.ln(8)
        for _ in line:  # the line to write on, under each label
            x = pdf.get_x()
            pdf.line(x, pdf.get_y() + 1, x + width - 6, pdf.get_y() + 1)
            pdf.set_x(x + width)
        pdf.set_x(pdf.l_margin)
        pdf.ln(3)


def add_sheet_page(pdf, brgy_name, muni, data):
    """Draw one barangay's sheet on a new A4 page (no app buttons or menus on it)."""
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, safe("Birth plan guide / Giya sa plano sa pagpanganak"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, safe(f"Barangay {brgy_name}, {muni}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 9.5)
    with pdf.table(col_widths=(48, 50, 28, 27, 27), line_height=5.0, text_align="LEFT") as table:
        header = table.row()
        for title in ["Level of care", "Nearest facility / Pinakaduol nga pasilidad", "Phone / Numero",
                      "Dry season / Ting-init", "Rainy season / Ting-ulan"]:
            header.cell(safe(title))
        for fname, row in data["rows"].items():
            line = table.row()
            line.cell(safe("\n".join(row["labels"])))
            line.cell(safe(f"{fname}{' *' if row['assumed'] else ''}"))
            line.cell(safe(row["phone"]) if row["phone"] else "____________")  # write-in line
            line.cell(safe(round5(row["dry"])))
            line.cell(safe(round5(row["rainy"])))

    if data["no_road"]:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 10)
        pdf.multi_cell(0, 5, safe(NO_ROAD_TEXT), border=1, padding=2, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, safe("Emergency numbers / Mga numero sa emerhensya"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 5, safe(FILL_IN_TEXT), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "National emergency hotline: 911", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10.5)
    write_in_lines(pdf, [("Ambulance / Ambulansya", "Midwife / Mananabang"), ("Barangay hall",)])

    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "My birth plan", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 5, safe(FILL_IN_TEXT), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10.5)
    write_in_lines(pdf, MY_PLAN)

    pdf.ln(1)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(85, 85, 85)
    for note in sheet_notes(data["any_assumed"]):
        pdf.multi_cell(0, 4.2, safe(note), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.8)
    pdf.set_text_color(0, 0, 0)  # back to black for the next page


def make_pdf(barangay_ids):
    """A4 PDF with one page per barangay, ready to print."""
    pdf = FPDF(format="A4")
    pdf.set_margins(15, 15, 15)
    for bid in barangay_ids:
        b = barangays[barangays["barangay_id"] == bid].iloc[0]
        add_sheet_page(pdf, b["barangay"], b["municipality"], sheet_data(bid))
    return bytes(pdf.output())


@st.cache_data(show_spinner="Making the sheets for the whole town...")
def town_pdf(town_name):
    """All barangays of one town in one PDF (remembered, so it is only made once per town)."""
    return make_pdf(barangays[barangays["municipality"] == town_name].sort_values("barangay")["barangay_id"])


file_stem = f"birth_plan_{muni}_{brgy_name}".replace(" ", "_")
one_col, town_col_btn = st.columns(2)
one_col.download_button("Download this sheet (PDF)", make_pdf([b_id]), f"{file_stem}.pdf",
                        "application/pdf", key="main_action_pdf", width="stretch")  # brand orange (app.py)
town_col_btn.download_button(f"Download all {len(brgy_ids)} barangays of {muni} (PDF)", town_pdf(muni),
                             f"birth_plans_{muni}.pdf".replace(" ", "_"), "application/pdf",
                             width="stretch", help="One page per barangay, to print for every health station.")
st.caption("Preview:")
with st.container(border=True):
    st.html(sheet)
