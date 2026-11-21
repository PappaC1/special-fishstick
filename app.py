import re
import numpy as np
import pdfplumber
import pandas as pd
import streamlit as st

st.set_page_config(page_title="SA Punters AI", page_icon="🏇", layout="centered", initial_sidebar_state="collapsed")
st.title("🏇 SA Punters Challenge AI")
st.caption("Universal Racecard Parser • Probable Winner • Value Bet • Danger Horse")

def parse_odds(raw: str) -> float:
    raw = raw.strip().replace("-", "/")
    if "/" in raw:
        num, den = map(float, raw.split("/"))
        return round((num / den) + 1.0, 2) if den > 0 else 10.0
    return round(float(raw), 2)

def parse_any_racing_pdf(uploaded_file) -> tuple[pd.DataFrame, str]:
    pages = []
    with pdfplumber.open(uploaded_file) as pdf:
        for p in pdf.pages:
            pages.append(p.extract_text() or "")
    full_text = "\n".join(pages)

    if len(full_text.strip()) < 100:
        return pd.DataFrame(), "IMAGE_ONLY"

    course = "SA MEETING"
    cm = re.search(r"\b(FAIRVIEW|TURFFONTEIN|GREYVILLE|KENILWORTH|VAAL|SCOTTSVILLE|DURBANVILLE)\b", full_text, re.I)
    if cm:
        course = cm.group(1).upper()

    # Strategy 1: Computaform Page 3 Index (handles dots with or without spaces)
    horse_index = {}
    idx_page = next((p for p in pages if "ALPHABETICAL INDEX" in p.upper()), "")
    for m in re.finditer(r"\bR(\d{1,2})\s+([A-Za-z][A-Za-z\s\'\(\)\-]+?)(?:[\s\.]{2,}|\t)\s*(\d{1,2})\b", idx_page):
        r_num, s_no = int(m.group(1)), int(m.group(3))
        h_name = m.group(2).strip().title()
        h_key = re.sub(r"[^A-Z]", "", h_name.upper())
        if len(h_key) >= 3:
            horse_index[h_key] = (r_num, s_no, h_name)

    runner_stats = {}
    race_dists = {}

    # Scan all pages for race headers, ratings, jockeys & odds
    current_race = 1
    for txt in pages:
        # Detect race number from headers like "RACE 2", "Race 2 - 1400m", or Computaform page votes
        page_clean = re.sub(r"[^A-Z]", "", txt.upper())
        votes = {}
        for h_key, (r_num, _, _) in horse_index.items():
            if len(h_key) >= 5 and h_key in page_clean:
                votes[r_num] = votes.get(r_num, 0) + 1
        if votes:
            current_race = max(votes, key=votes.get)
        else:
            rh = re.search(r"\bRACE\s+(\d{1,2})\b", txt, re.I)
            if rh:
                current_race = int(rh.group(1))

        dm = re.search(r"\b(\d{3,4})\s*m\b", txt, re.I)
        if dm:
            race_dists[current_race] = int(dm.group(1))

        # Extract CFORM & SPEED ratings if present
        fb = re.search(r"CFORM RATINGS(.*?)TIPSTER", txt, re.S | re.I)
        if fb:
            for line in fb.group(1).split("\n"):
                if "TOP %" in line or "BEST WEIGHTED" in line:
                    continue
                for bm in re.finditer(r"\b(\d{1,2})\s+[A-Za-z][A-Za-z\s\'\(\)\-]+?\s+([+-]\d+\.\d+)\b", line):
                    runner_stats.setdefault((current_race, int(bm.group(1))), {})["bva"] = float(bm.group(2))
                for im in re.finditer(r"\b(\d{1,2})\s+[A-Za-z][A-Za-z\s\'\(\)\-]+?\s+(\d{1,3})\b", line):
                    no, val = int(im.group(1)), float(im.group(2))
                    ent = runner_stats.setdefault((current_race, no), {})
                    if "cf" not in ent and val <= 75:
                        ent["cf"] = val
                    elif "sp" not in ent:
                        ent["sp"] = val

        # Extract runner lines from any format (Computaform, Formgrids, Racing Skeem, Winning Form)
        for line in txt.split("\n"):
            # Skip non-runner stats/index lines
            if re.search(r"\b(RIDES|RUNS|STAKES|1ST 3%|WIN%|CLASS|AVERAGE)\b", line, re.I):
                continue
            m = re.search(r"^\s*(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s+(?:[\d▲▼]+\s+)?([A-Z][A-Z\s\'\(\)\-]{2,26}?)\s+.*?\b(\d+[-/]\d+|\d+\.\d{2})\s*$", line)
            if not m:
                continue
            no = int(m.group(1))
            if no > 24:
                continue
            h_name = m.group(2).strip().title()
            h_key = re.sub(r"[^A-Z]", "", h_name.upper())
            if len(h_key) < 3 or any(bad in h_key for bad in ["FAIRVIEW", "TURFFONTEIN", "GREYVILLE", "KENILWORTH", "VAAL", "SCOTTSVILLE", "DURBANVILLE", "MAIDEN", "HANDICAP", "PLATE", "STAKES"]):
                continue

            odds = parse_odds(m.group(3))
            r_target = horse_index[h_key][0] if h_key in horse_index else current_race
            s_target = horse_index[h_key][1] if h_key in horse_index else no
            if h_key not in horse_index:
                horse_index[h_key] = (r_target, s_target, h_name)

            # Extract L3 form & career win rate if present
            rec = re.search(r"\b(\d+)-(\d+)-(\d+)-(\d+)\b", line)
            l3_m = re.search(r"^\s*\d{1,2}\s+(\d{1,3})\s+[A-Z]", line)
            l3_digits = [int(d) if d != "0" else 8 for d in l3_m.group(1)] if l3_m else []
            form_pts = sum((5 - min(d, 5)) * w for d, w in zip(l3_digits, (3, 2, 1)))
            jock_m = re.search(r"\*?([A-Z][a-z]+\s+[A-Za-z\-\']+)\s+(?:[\d\.]+|--)\s*%", line)

            ent = runner_stats.setdefault((r_target, s_target), {})
            ent.setdefault("odds", odds)
            if form_pts:
                ent["form_pts"] = form_pts
            if rec and int(rec.group(1)) > 0:
                ent["win_rate"] = int(rec.group(2)) / int(rec.group(1))
            if jock_m:
                ent["jockey"] = jock_m.group(1).strip()

    rows = []
    for h_key, (r_num, s_no, h_title) in horse_index.items():
        st_data = runner_stats.get((r_num, s_no), {})
        rows.append({
            "course": course, "race_number": r_num, "distance_m": race_dists.get(r_num, 1200),
            "saddle_number": s_no, "horse_name": h_title, "jockey": st_data.get("jockey", "TBC"),
            "odds": st_data.get("odds", 10.0), "cform": st_data.get("cf", np.nan),
            "speed": st_data.get("sp", np.nan), "bva": st_data.get("bva", np.nan),
            "form_pts": st_data.get("form_pts", 0), "win_rate": st_data.get("win_rate", 0.0),
        })
    df = pd.DataFrame(rows)
    return (df.drop_duplicates(subset=["race_number", "saddle_number"]).sort_values(["race_number", "saddle_number"]) if not df.empty else df), "OK"

def predict_races(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    scored, picks = [], []
    for _, grp in df.groupby("race_number", sort=True):
        grp = grp.copy()
        imp = 1.0 / grp["odds"].clip(lower=1.05)
        mkt_p = imp / imp.sum()
        z = np.zeros(len(grp))
        for col, w in [("cform", 0.35), ("speed", 0.25), ("form_pts", 0.15), ("bva", 0.15), ("win_rate", 0.10)]:
            vals = grp[col].fillna(grp[col].median()).fillna(0).values
            if np.std(vals) > 0:
                z += w * ((vals - np.mean(vals)) / np.std(vals))
        model_p = np.exp(z * 0.55)
        win_p = (0.50 * mkt_p) + (0.50 * (model_p / model_p.sum()))
        grp["win_prob"] = win_p / win_p.sum()
        grp["edge"] = grp["win_prob"] - imp
        grp = grp.sort_values(["win_prob", "odds"], ascending=[False, True]).reset_index(drop=True)
        scored.append(grp)

        rows = [r for _, r in grp.iterrows()]
        pw = next(iter(rows))
        picks.append({**pw, "pick_type": "Probable Winner", "is_top": True})

        val_pool = sorted([r for r in rows[1:] if r["edge"] > 0.02 and r["odds"] >= 2.50], key=lambda x: x["edge"], reverse=True)
        vb = next(iter(val_pool), rows[1] if len(rows) > 1 else pw)
        picks.append({**vb, "pick_type": "Value Bet", "is_top": False})

        used = {pw["horse_name"], vb["horse_name"]}
        dh = next((r for r in rows if r["horse_name"] not in used), rows[-1])
        picks.append({**dh, "pick_type": "Danger Horse", "is_top": False})

    return pd.concat(scored, ignore_index=True), pd.DataFrame(picks)

uploaded_pdf = st.file_uploader("Upload Racecard PDF (Computaform, Winning Form, Formgrids, Racing Skeem)", type=["pdf"])
if not uploaded_pdf:
    st.info("Tap **Browse files** above to upload any South African racecard PDF.")
    st.stop()

with st.spinner("Extracting races, runners, form & betting forecast..."):
    runners_df, status = parse_any_racing_pdf(uploaded_pdf)

if status == "IMAGE_ONLY":
    st.error("This PDF contains scanned images with no selectable text. Please upload a digital text PDF (e.g. Computaform, Winning Form, or Formgrids).")
    st.stop()
if runners_df.empty:
    st.error("No runners detected in this PDF layout.")
    st.stop()

full_df, picks_df = predict_races(runners_df)
course_name = next(iter(full_df["course"]))
tab_card, tab_races = st.tabs(["🏆 Punters Challenge Card", "🔍 Race-by-Race (Top 3)"])

with tab_card:
    st.subheader(f"{course_name} — Punters Card ({full_df['race_number'].nunique()} Races)")
    for _, r in picks_df[picks_df["is_top"]].sort_values("race_number").iterrows():
        with st.container(border=True):
            c1, c2 = st.columns(2)
            c1.markdown(f"**R{int(r['race_number'])}: #{int(r['saddle_number'])} {r['horse_name']}**")
            c1.caption(f"Jockey: {r['jockey']} • Fcst: {r['odds']:.2f} • Edge: {r['edge']:+.1%}")
            c2.metric("Win %", f"{r['win_prob']:.0%}")
    st.download_button("📥 Download Full Selections (CSV)", picks_df.to_csv(index=False), f"{course_name}_punters.csv", "text/csv", use_container_width=True)

with tab_races:
    sel_r = st.selectbox("Select Race", sorted(full_df["race_number"].unique().tolist()), format_func=lambda x: f"Race {int(x)}")
    r_picks = picks_df[picks_df["race_number"] == sel_r]
    r_field = full_df[full_df["race_number"] == sel_r]
    st.subheader(f"Race {int(sel_r)} — {course_name} ({int(next(iter(r_field['distance_m'])))}m)")
    badges = {"Probable Winner": "🥇", "Value Bet": "💎", "Danger Horse": "⚠️"}
    for _, row in r_picks.iterrows():
        with st.container(border=True):
