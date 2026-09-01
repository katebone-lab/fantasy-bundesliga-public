from __future__ import annotations

import streamlit as st

from app_context import choose_default_matchday, format_matchday_option, format_season
from data_repository import MatchdayAvailability


def initialise_active_context(
    available: list[MatchdayAvailability],
) -> MatchdayAvailability:
    default = choose_default_matchday(available)
    seasons = sorted({item.season for item in available}, reverse=True)
    if st.session_state.get("active_season") not in seasons:
        st.session_state["active_season"] = default.season

    selected_season = st.session_state["active_season"]
    season_matchdays = [item for item in available if item.season == selected_season]
    valid_matchdays = {item.matchday for item in season_matchdays}
    if st.session_state.get("active_matchday") not in valid_matchdays:
        st.session_state["active_matchday"] = choose_default_matchday(season_matchdays).matchday
    return next(
        item for item in season_matchdays
        if item.matchday == st.session_state["active_matchday"]
    )


def render_context_selectors(
    available: list[MatchdayAvailability],
) -> MatchdayAvailability:
    initialise_active_context(available)
    seasons = sorted({item.season for item in available}, reverse=True)
    season_column, matchday_column = st.columns([1, 1.6])
    selected_season = season_column.selectbox(
        "Season", options=seasons, format_func=format_season, key="active_season"
    )
    season_matchdays = [item for item in available if item.season == selected_season]
    valid_matchdays = {item.matchday for item in season_matchdays}
    if st.session_state.get("active_matchday") not in valid_matchdays:
        st.session_state["active_matchday"] = choose_default_matchday(season_matchdays).matchday
    selected_matchday = matchday_column.selectbox(
        "Matchday",
        options=[item.matchday for item in season_matchdays],
        format_func=lambda number: format_matchday_option(
            next(item for item in season_matchdays if item.matchday == number)
        ),
        key="active_matchday",
    )
    context = next(
        item for item in season_matchdays if item.matchday == selected_matchday
    )
    current_key = (context.season, context.matchday)
    if st.session_state.get("_active_data_context") != current_key:
        st.session_state.pop("stats_search", None)
        for key in list(st.session_state):
            if key.startswith("api_candidate_") or key.startswith("api_decision_"):
                del st.session_state[key]
        st.session_state["_active_data_context"] = current_key
    return context
