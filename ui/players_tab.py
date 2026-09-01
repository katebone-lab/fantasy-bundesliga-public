from __future__ import annotations

import pandas as pd
import streamlit as st

from app_constants import AVAILABILITY_LABELS, POSITION_LABELS
from ui.components import display_player_detail, display_player_table


def render_players_tab(
    fantasy: pd.DataFrame, combined: pd.DataFrame, season: int, matchday: int
) -> None:
    st.subheader("Player explorer")
    if fantasy.empty:
        st.info(f"No official Fantasy Bundesliga player snapshot is available for Matchday {matchday}.")
        return
    context_key = f"{season}_{matchday}"
    f1, f2, f3, f4 = st.columns([1.4, 1.4, 1.4, 1.2])
    search = f1.text_input("Search", placeholder="Player or club", key=f"player_search_{context_key}")
    selected_positions = f2.multiselect(
        "Position", options=list(POSITION_LABELS), default=list(POSITION_LABELS),
        format_func=lambda value: POSITION_LABELS[value], key=f"player_positions_{context_key}",
    )
    selected_availability = f3.multiselect(
        "Availability", options=sorted(fantasy["availability"].dropna().unique()),
        default=sorted(fantasy["availability"].dropna().unique()),
        format_func=lambda value: AVAILABILITY_LABELS.get(value, value.title()),
        key=f"player_availability_{context_key}",
    )
    selected_clubs = f4.multiselect(
        "Club", options=sorted(fantasy["club"].dropna().unique()), default=[], placeholder="All clubs",
        key=f"player_clubs_{context_key}",
    )
    s1, s2, s3 = st.columns([1.4, 1.4, 1])
    sort_by = s1.selectbox(
        "Sort by", options=["Matchday points", "Points per £m", "Price", "Player"],
        key=f"player_sort_{context_key}",
    )
    descending = s2.toggle("Highest first", value=True, key=f"player_descending_{context_key}")
    known_points_only = s3.toggle("Known points only", value=False, key=f"known_points_{context_key}")

    filtered = fantasy.copy()
    if search.strip():
        query = search.strip().casefold()
        filtered = filtered[
            filtered["player"].str.casefold().str.contains(query, regex=False)
            | filtered["club"].str.casefold().str.contains(query, regex=False)
        ]
    if selected_positions:
        filtered = filtered[filtered["fantasy_position"].isin(selected_positions)]
    else:
        filtered = filtered.iloc[0:0]
    if selected_availability:
        filtered = filtered[filtered["availability"].isin(selected_availability)]
    else:
        filtered = filtered.iloc[0:0]
    if selected_clubs:
        filtered = filtered[filtered["club"].isin(selected_clubs)]
    if known_points_only:
        filtered = filtered[filtered["matchday_points"].notna()]
    sort_map = {
        "Matchday points": "matchday_points", "Points per £m": "points_per_m",
        "Price": "price_m", "Player": "player",
    }
    filtered = filtered.sort_values(sort_map[sort_by], ascending=not descending, na_position="last")
    st.caption(f"Showing {len(filtered)} of {len(fantasy)} players")
    display_player_table(filtered)

    st.markdown("### Player detail")
    detail_options = filtered.index.tolist()
    if detail_options:
        detail_index = st.selectbox(
            "Open player", options=detail_options,
            format_func=lambda index: f"{fantasy.loc[index, 'player']} · {fantasy.loc[index, 'club']}",
            key=f"open_player_{context_key}",
        )
        detail_rows = combined[
            (combined["player"] == fantasy.loc[detail_index, "player"])
            & (combined["club"] == fantasy.loc[detail_index, "club"])
        ]
        if not detail_rows.empty:
            display_player_detail(detail_rows.iloc[0])
    else:
        st.info("No player matches the current filters.")
    st.download_button(
        "Download filtered CSV",
        filtered[[
            "player", "club", "fantasy_position", "price_m", "matchday_points",
            "availability", "matchday", "notes", "points_per_m",
        ]].to_csv(index=False).encode("utf-8"),
        file_name="fantasy_bundesliga_filtered.csv", mime="text/csv",
    )
