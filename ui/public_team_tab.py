from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from app_matching import merge_with_stats
from data_repository import FantasyRepository


PUBLIC_TEAM_ROOT = Path(__file__).resolve().parents[1] / "data" / "public_team"
POSITION_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FOR": 3}


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


def _build_candidate_pool(
    repository: FantasyRepository,
    season: int,
    matchday: int,
) -> pd.DataFrame:
    """Build a read-only transfer candidate pool from published temporal facts."""
    planning = repository.get_planning_players(season, matchday).copy()
    if planning.empty:
        return planning

    performance_matchday = max(matchday - 1, 1)
    performance = repository.get_fantasy_players(season, performance_matchday)
    stats = repository.get_match_stats(season, performance_matchday).data
    name_map = repository.get_approved_name_map(season, performance_matchday)
    manual_only = repository.get_manual_only_players(season, performance_matchday)
    combined = merge_with_stats(performance, stats, name_map, manual_only)

    context_columns = [
        column
        for column in ["player", "club", "minutes", "rating"]
        if column in combined.columns
    ]
    if context_columns:
        api_context = combined[context_columns].drop_duplicates(
            subset=["player", "club"], keep="first"
        )
        planning = planning.merge(
            api_context, on=["player", "club"], how="left", suffixes=("", "_api")
        )

    prior_prices = repository.get_effective_prices(season, performance_matchday).copy()
    if not prior_prices.empty and {"player", "price_m"}.issubset(prior_prices.columns):
        prior_prices = prior_prices[["player", "price_m"]].drop_duplicates(
            subset=["player"], keep="first"
        )
        prior_prices = prior_prices.rename(columns={"price_m": "prior_price_m"})
        planning = planning.merge(prior_prices, on="player", how="left")
    else:
        planning["prior_price_m"] = pd.NA

    planning["price_m"] = pd.to_numeric(planning["price_m"], errors="coerce")
    planning["prior_price_m"] = pd.to_numeric(
        planning["prior_price_m"], errors="coerce"
    )
    planning["matchday_points"] = pd.to_numeric(
        planning["matchday_points"], errors="coerce"
    )
    planning["minutes"] = pd.to_numeric(planning.get("minutes"), errors="coerce")
    planning["rating"] = pd.to_numeric(planning.get("rating"), errors="coerce")
    planning["points_per_m"] = planning["matchday_points"].div(
        planning["price_m"].where(planning["price_m"] > 0)
    )
    planning["points_per_minute"] = planning["matchday_points"].div(
        planning["minutes"].where(planning["minutes"] > 0)
    )
    planning["week_price_change_m"] = planning["price_m"] - planning["prior_price_m"]
    planning["week_price_change_pct"] = planning["week_price_change_m"].div(
        planning["prior_price_m"].where(planning["prior_price_m"] > 0)
    ) * 100
    return planning


def _candidate_label(row: pd.Series) -> str:
    points = "—" if pd.isna(row.get("matchday_points")) else f"{row['matchday_points']:.0f} pts"
    minutes = "—" if pd.isna(row.get("minutes")) else f"{row['minutes']:.0f} min"
    return f"{row['player']} · {row['club']} · £{row['price_m']:.2f}m · {points} · {minutes}"


def _cost_saving_label(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    value = float(value)
    if abs(value) < 0.005:
        return "No change"
    if value > 0:
        return f"£{value:.2f}m cost"
    return f"£{abs(value):.2f}m saving"


def _price_movement_label(candidate: pd.Series) -> str:
    change = candidate.get("week_price_change_m")
    pct = candidate.get("week_price_change_pct")
    if pd.isna(change):
        return "—"
    pct_text = "" if pd.isna(pct) else f" ({pct:+.1f}%)"
    return f"{change:+.2f}m{pct_text}"


def _render_candidate_detail(candidate: pd.Series) -> None:
    st.markdown("##### Candidate detail")
    row1 = st.columns(5)
    row1[0].metric("MD2 price", f"£{candidate['price_m']:.2f}m")
    row1[1].metric("Cost / saving", _cost_saving_label(candidate.get("transfer_cost_m")))
    row1[2].metric("Change since MD1", _price_movement_label(candidate))
    row1[3].metric(
        "MD1 points",
        "—" if pd.isna(candidate.get("matchday_points")) else f"{candidate['matchday_points']:.0f}",
    )
    row1[4].metric(
        "API minutes",
        "—" if pd.isna(candidate.get("minutes")) else f"{candidate['minutes']:.0f}",
    )

    row2 = st.columns(2)
    row2[0].metric(
        "Points/min",
        "—" if pd.isna(candidate.get("points_per_minute")) else f"{candidate['points_per_minute']:.2f}",
    )
    row2[1].metric(
        "API rating",
        "—" if pd.isna(candidate.get("rating")) else f"{candidate['rating']:.1f}",
    )
    st.caption(
        "Change since MD1 is shown only where both published MD1 and captured MD2 prices exist. "
        "Points per minute can make short substitute appearances look unusually strong, so minutes are always shown alongside it."
    )


def _render_transfer_analysis(
    repository: FantasyRepository,
    team: pd.DataFrame,
    team_record: dict,
) -> None:
    st.markdown("---")
    st.markdown("### Transfer analysis")
    st.caption(
        "Read-only shortlist using published Matchday 1 performance and captured Matchday 2 prices. "
        "Candidates must be in the same position, affordable with current cash, outside the current squad, "
        "and compatible with the three-player-per-club limit. No transfer is applied from this view."
    )

    if team.empty:
        st.info("No squad is available for transfer analysis.")
        return

    season = int(team_record["season"])
    matchday = int(team_record["matchday"])
    cash_m = float(team_record.get("cash_m", 0.0))
    candidates = _build_candidate_pool(repository, season, matchday)
    if candidates.empty:
        st.info("No published planning candidates are available yet.")
        return

    outgoing_options = team.sort_values(
        ["position_order", "player"]
    )["player"].tolist()
    outgoing_name = st.selectbox(
        "Player to compare for replacement",
        options=outgoing_options,
        key=f"public_transfer_out_{season}_{matchday}",
    )
    outgoing = team.loc[team["player"] == outgoing_name].iloc[0]
    outgoing_price = float(outgoing["display_price_m"])
    available_budget = round(cash_m + outgoing_price, 2)

    squad_names = set(team["player"].astype(str))
    remaining_club_counts = (
        team.loc[team["player"] != outgoing_name, "club"].value_counts().to_dict()
    )

    valid = candidates[
        (candidates["fantasy_position"] == outgoing["position"])
        & (~candidates["player"].isin(squad_names))
        & (candidates["price_m"].notna())
        & (candidates["price_m"] <= available_budget)
    ].copy()
    valid = valid[
        valid["club"].map(lambda club: remaining_club_counts.get(club, 0) < 3)
    ].copy()

    if valid.empty:
        st.warning("No valid replacements are available within this budget.")
        return

    valid["transfer_cost_m"] = valid["price_m"] - outgoing_price
    valid["cost_saving"] = valid["transfer_cost_m"].map(_cost_saving_label)
    valid["points_change"] = valid["matchday_points"] - pd.to_numeric(
        outgoing["matchday_points"], errors="coerce"
    )

    metric1, metric2, metric3 = st.columns(3)
    metric1.metric("Current planning price", f"£{outgoing_price:.2f}m")
    metric2.metric("Cash available", f"£{cash_m:.2f}m")
    metric3.metric("Maximum replacement price", f"£{available_budget:.2f}m")

    st.markdown("#### Explore candidates")
    candidate_rows = valid.sort_values(["player", "club"]).reset_index(drop=True)
    manual_index = st.selectbox(
        "Inspect any valid candidate",
        options=list(candidate_rows.index),
        format_func=lambda index: _candidate_label(candidate_rows.loc[index]),
        key=f"public_transfer_candidate_{season}_{matchday}_{outgoing_name}",
    )
    _render_candidate_detail(candidate_rows.loc[manual_index])

    filter1, filter2 = st.columns(2)
    played_only = filter1.checkbox(
        "Only players who played in MD1",
        value=False,
        key=f"public_transfer_played_{season}_{matchday}",
    )
    known_points_only = filter2.checkbox(
        "Known MD1 points only",
        value=False,
        key=f"public_transfer_known_points_{season}_{matchday}",
    )

    shortlist = valid.copy()
    if played_only:
        shortlist = shortlist[shortlist["minutes"].fillna(0) > 0]
    if known_points_only:
        shortlist = shortlist[shortlist["matchday_points"].notna()]

    rank_label = st.selectbox(
        "Rank shortlist by",
        options=[
            "MD1 points",
            "Points per minute",
            "Points per £m",
            "API rating",
            "Price rise since MD1",
            "Price",
        ],
        key=f"public_transfer_rank_{season}_{matchday}",
    )
    rank_column = {
        "MD1 points": "matchday_points",
        "Points per minute": "points_per_minute",
        "Points per £m": "points_per_m",
        "API rating": "rating",
        "Price rise since MD1": "week_price_change_pct",
        "Price": "price_m",
    }[rank_label]
    ascending = rank_label == "Price"

    if shortlist.empty:
        st.info("No candidates match the optional filters. Clear a filter to see the full valid pool again.")
        return

    ranked = shortlist.sort_values(
        rank_column, ascending=ascending, na_position="last"
    ).head(12)
    view_columns = [
        "player",
        "club",
        "price_m",
        "cost_saving",
        "week_price_change_m",
        "week_price_change_pct",
        "matchday_points",
        "points_per_minute",
        "points_per_m",
        "minutes",
        "rating",
        "points_change",
    ]
    for column in view_columns:
        if column not in ranked.columns:
            ranked[column] = pd.NA
    view = ranked[view_columns].rename(
        columns={
            "player": "Candidate",
            "club": "Club",
            "price_m": "MD2 price (£m)",
            "cost_saving": "Cost / saving",
            "week_price_change_m": "Change since MD1 (£m)",
            "week_price_change_pct": "Change since MD1 (%)",
            "matchday_points": "MD1 points",
            "points_per_minute": "Points/min",
            "points_per_m": "Points per £m",
            "minutes": "API minutes",
            "rating": "API rating",
            "points_change": "MD1 points vs current",
        }
    )
    st.dataframe(
        view,
        width="stretch",
        hide_index=True,
        column_config={
            "MD2 price (£m)": st.column_config.NumberColumn(format="%.2f"),
            "Change since MD1 (£m)": st.column_config.NumberColumn(format="%+.2f"),
            "Change since MD1 (%)": st.column_config.NumberColumn(format="%+.1f%%"),
            "MD1 points": st.column_config.NumberColumn(format="%.0f"),
            "Points/min": st.column_config.NumberColumn(format="%.2f"),
            "Points per £m": st.column_config.NumberColumn(format="%.1f"),
            "API minutes": st.column_config.NumberColumn(format="%.0f"),
            "API rating": st.column_config.NumberColumn(format="%.1f"),
            "MD1 points vs current": st.column_config.NumberColumn(format="%+.0f"),
        },
    )
    st.caption(
        f"{len(valid)} valid replacements in the full pool; {len(shortlist)} match the optional filters; "
        f"showing the top {min(12, len(shortlist))}. Cost / saving compares the candidate with the selected "
        "current player's planning value. Week-on-week price movement is shown only where both genuine MD1 "
        "and captured MD2 prices exist. Points/min is most useful alongside the minutes column, especially "
        "for late substitutes and other small samples. Club and position use the latest published historical "
        "context because explicit Matchday 2 planning context has not yet been captured."
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
    records.sort(
        key=lambda item: (int(item[1]["season"]), int(item[1]["matchday"])),
        reverse=True,
    )
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
    metric4.metric(
        f"MD{matchday} prices captured", f"{known_md_price_count}/{len(team)}"
    )

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
    _render_transfer_analysis(repository, team, team_record)
