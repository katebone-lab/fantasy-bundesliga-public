from __future__ import annotations

import pandas as pd
import streamlit as st

from app_constants import POSITION_LABELS
from ui.components import display_player_table


def render_leaders_tab(fantasy: pd.DataFrame, season: int, matchday: int) -> None:
    st.subheader("Position leaders")
    if fantasy.empty:
        st.info(f"No official Fantasy Bundesliga player snapshot is available for Matchday {matchday}.")
        return
    st.caption(f"Top players from the manual Matchday {matchday} snapshot. Players with obscured point totals remain blank rather than guessed.")
    context_key = f"{season}_{matchday}"
    top_n = st.slider(
        "Players per position", min_value=3, max_value=20, value=10,
        key=f"leaders_count_{context_key}",
    )
    leader_sort = st.radio(
        "Rank by", ["Matchday points", "Points per £m"], horizontal=True,
        key=f"leaders_rank_{context_key}",
    )
    leader_column = "matchday_points" if leader_sort == "Matchday points" else "points_per_m"
    for position in POSITION_LABELS:
        st.markdown(f"#### {POSITION_LABELS[position]}s")
        block = fantasy[fantasy["fantasy_position"] == position].sort_values(
            leader_column, ascending=False, na_position="last"
        ).head(top_n)
        display_player_table(block)
