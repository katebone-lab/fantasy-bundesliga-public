from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st


def render_stats_tab(
    stats: pd.DataFrame,
    stats_path: Path | None,
    combined: pd.DataFrame,
    matchday: int,
    has_fantasy_data: bool,
) -> None:
    st.subheader("Fantasy ↔ match-stat matching")
    if stats.empty:
        st.info(f"No Matchday {matchday} API match statistics are available.")
        return
    season_folder = stats_path.parent.name if stats_path else "unknown"
    st.caption(f"Using `{season_folder}/player_match_stats.json`.")
    if not has_fantasy_data:
        st.info(
            f"API match statistics are available for Matchday {matchday}, but no official fantasy snapshot is available to join."
        )
        return
    matched = combined[combined["api_match"]].copy()
    manual_only_players = combined[combined["match_status"] == "Manual-only"].copy()
    unresolved = combined[combined["match_status"] == "Unresolved"].copy()
    coverage = len(matched) / len(combined) if len(combined) else 0
    st.progress(coverage, text=f"{len(matched)} of {len(combined)} fantasy players matched to API stats ({coverage:.1%})")
    if len(manual_only_players):
        st.caption(f"{len(manual_only_players)} player(s) are intentionally kept as manual-only because no valid API record is available for this matchday.")
    query = st.text_input("Find a player in the joined data", key="stats_search")
    joined_view = matched
    if query.strip():
        normalized_query = query.strip().casefold()
        joined_view = joined_view[
            joined_view["player"].str.casefold().str.contains(normalized_query, regex=False)
            | joined_view["club"].str.casefold().str.contains(normalized_query, regex=False)
        ]
    joined_columns = [
        "player", "club", "fantasy_position", "price_m", "matchday_points", "points_per_m",
        "minutes", "rating", "goals", "assists", "shots", "shots_on_target", "key_passes",
        "tackles", "interceptions", "duels_total", "duels_won", "saves", "goals_conceded",
    ]
    joined_columns = [column for column in joined_columns if column in joined_view.columns]
    st.dataframe(joined_view[joined_columns], width="stretch", hide_index=True)
    with st.expander(f"Unresolved players ({len(unresolved)})"):
        st.dataframe(
            unresolved[["player", "club", "fantasy_position", "matchday_points"]],
            width="stretch", hide_index=True,
        )
    if len(manual_only_players):
        with st.expander(f"Manual-only players ({len(manual_only_players)})"):
            st.dataframe(
                manual_only_players[["player", "club", "fantasy_position", "matchday_points"]],
                width="stretch", hide_index=True,
            )
