from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from fixture_model import build_team_strengths, fixture_label


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data" / "fixture_model"
SCHEDULE = DATA_ROOT / "2026_fixtures_md02_md08.csv"

ABBR = {
    "FC Bayern München": "FCB", "Borussia Dortmund": "BVB", "RB Leipzig": "RBL",
    "Bayer 04 Leverkusen": "B04", "VfB Stuttgart": "VFB", "TSG Hoffenheim": "TSG",
    "Eintracht Frankfurt": "SGE", "SC Freiburg": "SCF", "1. FC Köln": "KOE",
    "Borussia Mönchengladbach": "BMG", "FC Augsburg": "FCA", "1. FSV Mainz 05": "M05",
    "1. FC Union Berlin": "FCU", "SV Werder Bremen": "SVW", "Hamburger SV": "HSV",
    "FC Schalke 04": "S04", "SC Paderborn 07": "SCP", "SV Elversberg": "ELV",
}


def _results() -> pd.DataFrame:
    frames = []
    for path in sorted(DATA_ROOT.glob("2026_md*_results.csv")):
        frame = pd.read_csv(path)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["matchday", "home_club", "away_club", "home_goals", "away_goals"])
    return pd.concat(frames, ignore_index=True).drop_duplicates(
        subset=["matchday", "home_club", "away_club"], keep="last"
    )


def _schedule() -> pd.DataFrame:
    return pd.read_csv(SCHEDULE)


def _fixture_rows() -> pd.DataFrame:
    results = _results().copy()
    results["date_window"] = "Played"
    results["status"] = "Result"
    results["score"] = results.apply(
        lambda r: f"{int(r.home_goals)}–{int(r.away_goals)}", axis=1
    )
    played = results[["matchday", "home_club", "away_club", "date_window", "status", "score"]]

    future = _schedule().copy()
    future["status"] = "Fixture"
    future["score"] = "—"
    keys = set(zip(results["matchday"], results["home_club"], results["away_club"]))
    future = future[
        ~future.apply(lambda r: (r.matchday, r.home_club, r.away_club) in keys, axis=1)
    ]
    return pd.concat(
        [played, future[["matchday", "home_club", "away_club", "date_window", "status", "score"]]],
        ignore_index=True,
    ).sort_values(["matchday", "date_window", "home_club"])


def _fixture_matrix() -> pd.DataFrame:
    fixtures = _schedule()
    strengths = build_team_strengths().set_index("club")
    rows = []
    for f in fixtures.itertuples(index=False):
        for club, opponent, venue in (
            (f.home_club, f.away_club, "H"),
            (f.away_club, f.home_club, "A"),
        ):
            own = strengths.loc[club]
            opp = strengths.loc[opponent]
            attack_location = 1.06 if venue == "H" else 0.97
            defence_location = 1.04 if venue == "H" else 0.98
            attack_raw = own.attack_strength / opp.defence_strength * attack_location
            defence_raw = own.defence_strength / opp.attack_strength * defence_location
            rows.append({
                "matchday": int(f.matchday), "club": club, "opponent": opponent, "venue": venue,
                "raw": float((attack_raw + defence_raw) / 2),
            })
    frame = pd.DataFrame(rows)
    frame["ease"] = frame.groupby("matchday")["raw"].rank(pct=True) * 100
    frame["label"] = frame["ease"].map(fixture_label)
    return frame


def _fdr_style(value: str) -> str:
    if "Very favourable" in value:
        return "background-color:#159947;color:white;font-weight:600"
    if "Favourable" in value:
        return "background-color:#7cbf35;color:#15210b;font-weight:600"
    if "Neutral" in value:
        return "background-color:#edbf00;color:#2c2600;font-weight:600"
    if "Very tough" in value:
        return "background-color:#e6002d;color:white;font-weight:600"
    if "Tough" in value:
        return "background-color:#f47a0b;color:#2b1500;font-weight:600"
    return ""


def render_fixtures_fdr_tab() -> None:
    st.subheader("Fixtures & fixture difficulty")
    st.caption(
        "Our own fixture view, calculated from the same team-strength model used by transfer planning. "
        "It is not copied from an external FDR rating."
    )

    fdr_tab, list_tab = st.tabs(["FDR matrix", "Fixtures & results"])
    with fdr_tab:
        matrix = _fixture_matrix()
        start, end = st.slider("Matchdays", 2, 8, (2, 8))
        view = matrix[matrix["matchday"].between(start, end)].copy()
        view["cell"] = view.apply(
            lambda r: f"{ABBR.get(r.opponent, r.opponent)} ({r.venue}) · {r.label}", axis=1
        )
        pivot = view.pivot(index="club", columns="matchday", values="cell")
        ease = view.groupby("club")["ease"].mean().sort_values(ascending=False)
        pivot = pivot.reindex(ease.index)
        pivot.columns = [f"GW{int(c)}" for c in pivot.columns]
        st.dataframe(pivot.style.map(_fdr_style), width="stretch", height=690)

        with st.expander("Team strength behind the ratings"):
            strength = build_team_strengths().copy()
            strength["Attack"] = strength["attack_strength"].rank(pct=True) * 100
            strength["Defence"] = strength["defence_strength"].rank(pct=True) * 100
            strength["Overall"] = strength["overall_strength"].rank(pct=True) * 100
            st.dataframe(
                strength[["club", "Attack", "Defence", "Overall"]]
                .sort_values("Overall", ascending=False)
                .rename(columns={"club": "Team"}),
                hide_index=True, width="stretch",
                column_config={
                    "Attack": st.column_config.NumberColumn(format="%.0f"),
                    "Defence": st.column_config.NumberColumn(format="%.0f"),
                    "Overall": st.column_config.NumberColumn(format="%.0f"),
                },
            )

    with list_tab:
        fixtures = _fixture_rows()
        selected = st.multiselect(
            "Matchday", sorted(fixtures["matchday"].unique()),
            default=sorted(fixtures["matchday"].unique()),
        )
        shown = fixtures[fixtures["matchday"].isin(selected)].rename(columns={
            "matchday": "GW", "date_window": "Date", "home_club": "Home",
            "away_club": "Away", "score": "Score", "status": "Status",
        })
        st.dataframe(shown[["GW", "Date", "Home", "Score", "Away", "Status"]], hide_index=True, width="stretch")
        st.caption("Completed matchdays come from our results files; future rows come from our stored fixture schedule.")


def _league_table() -> pd.DataFrame:
    results = _results()
    clubs = sorted(set(results["home_club"]) | set(results["away_club"]))
    rows = []
    for club in clubs:
        home = results[results["home_club"] == club]
        away = results[results["away_club"] == club]
        gf = int(home["home_goals"].sum() + away["away_goals"].sum())
        ga = int(home["away_goals"].sum() + away["home_goals"].sum())
        wins = int((home["home_goals"] > home["away_goals"]).sum() + (away["away_goals"] > away["home_goals"]).sum())
        draws = int((home["home_goals"] == home["away_goals"]).sum() + (away["away_goals"] == away["home_goals"]).sum())
        losses = len(home) + len(away) - wins - draws
        rows.append({"Team": club, "P": len(home)+len(away), "W": wins, "D": draws, "L": losses,
                     "GF": gf, "GA": ga, "GD": gf-ga, "Pts": wins*3+draws})
    table = pd.DataFrame(rows).sort_values(["Pts", "GD", "GF"], ascending=[False, False, False]).reset_index(drop=True)
    table.index = table.index + 1
    table.insert(0, "Pos", table.index)
    return table


def render_league_table_tab() -> None:
    st.subheader("Bundesliga table")
    results = _results()
    if results.empty:
        st.info("No results have been captured yet.")
        return
    latest = int(results["matchday"].max())
    st.caption(f"Calculated entirely from our captured Bundesliga results, currently through Matchday {latest}.")
    st.dataframe(_league_table(), hide_index=True, width="stretch", height=690)
