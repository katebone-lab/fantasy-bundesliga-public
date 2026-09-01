from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from data_repository import FantasyRepository


PUBLIC_TEAM_ROOT = Path(__file__).resolve().parents[1] / "data" / "public_team"
POSITION_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FOR": 3}


def _load_public_team_snapshot(season: int, matchday: int) -> dict | None:
    path = PUBLIC_TEAM_ROOT / f"{season}_md{matchday:02d}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _build_public_team_view(
    repository: FantasyRepository,
    team_record: dict,
) -> pd.DataFrame:
    season = int(team_record["season"])
    matchday = int(team_record["matchday"])
    performance_matchday = max(matchday - 1, 1)

    team = pd.DataFrame(team_record.get("players", [])).copy()
    if team.empty:
        return team

    performance = repository.get_fantasy_players(season, performance_matchday)[
        ["player", "matchday_points"]
    ].drop_duplicates(subset=["player"], keep="first")
    prices = repository.get_effective_prices(season, matchday)[
        ["player", "price_m"]
    ].drop_duplicates(subset=["player"], keep="first")

    team = team.merge(performance, on="player", how="left")
    team = team.merge(prices, on="player", how="left")
    team["display_price_m"] = pd.to_numeric(team["price_m"], errors="coerce").combine_first(
        pd.to_numeric(team["last_squad_valuation_m"], errors="coerce")
    )
    team["price_source"] = team["price_m"].notna().map(
        {True: f"MD{matchday} captured price", False: "Last squad valuation"}
    )
    team["star_player"] = team["starred"].map({True: "★", False: ""})
    team["position_order"] = team["position"].map(POSITION_ORDER).fillna(99)
    return team


def _render_team_table(frame: pd.DataFrame, heading: str, points_label: str) -> None:
    st.markdown(f"#### {heading}")
    view = frame.sort_values(["position_order", "player"])[
        [
            "star_player",
            "player",
            "club",
            "position",
            "matchday_points",
            "display_price_m",
            "price_source",
        ]
    ].rename(
        columns={
            "star_player": "Star",
            "player": "Player",
            "club": "Club",
            "position": "Position",
            "matchday_points": points_label,
            "display_price_m": "Planning price (£m)",
            "price_source": "Price basis",
        }
    )
    st.dataframe(
        view,
        width="stretch",
        hide_index=True,
        column_config={
            points_label: st.column_config.NumberColumn(format="%.0f"),
            "Planning price (£m)": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def render_public_team_tab(repository: FantasyRepository) -> None:
    available = sorted(PUBLIC_TEAM_ROOT.glob("*_md*.json"))
    if not available:
        st.info("No public team snapshot is available yet.")
        return

    records = []
    for path in available:
        record = json.loads(path.read_text(encoding="utf-8"))
        records.append((path, record))
    records.sort(key=lambda item: (int(item[1]["season"]), int(item[1]["matchday"])), reverse=True)
    _, team_record = records[0]

    season = int(team_record["season"])
    matchday = int(team_record["matchday"])
    performance_matchday = max(matchday - 1, 1)
    team = _build_public_team_view(repository, team_record)

    st.subheader(f"My Team · Matchday {matchday}")
    st.caption(
        "Read-only planning snapshot. This view contains only the published squad, prior-matchday "
        "performance and captured planning prices; notes, transfer history and editing controls are excluded."
    )

    known_md_price_count = int(team["price_m"].notna().sum()) if not team.empty else 0
    planning_value = float(team["display_price_m"].sum()) if not team.empty else 0.0
    cash_m = float(team_record.get("cash_m", 0.0))

    metric1, metric2, metric3, metric4 = st.columns(4)
    metric1.metric("Formation", team_record.get("formation", "—"))
    metric2.metric("Planning squad value", f"£{planning_value:.2f}m")
    metric3.metric("Cash", f"£{cash_m:.2f}m")
    metric4.metric(f"MD{matchday} prices captured", f"{known_md_price_count}/{len(team)}")

    if known_md_price_count < len(team):
        st.info(
            f"Only {known_md_price_count} of {len(team)} squad members have a captured Matchday {matchday} "
            "price. Missing prices use the last recorded squad valuation and are labelled accordingly."
        )

    points_label = f"MD{performance_matchday} points"
    starters = team[team["slot"] == "starter"].copy()
    bench = team[team["slot"] == "bench"].copy()
    _render_team_table(starters, "Starting XI", points_label)
    _render_team_table(bench, "Bench", points_label)
