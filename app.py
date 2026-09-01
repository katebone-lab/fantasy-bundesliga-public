from pathlib import Path

import streamlit as st

from app_mode import get_application_mode
from app_data import (
    load_available_matchdays,
    load_fantasy,
    load_manual_only,
    load_match_stats,
    load_name_map,
    load_planning_fantasy,
)
from app_matching import merge_with_stats
from data_repository import FantasyRepository
from ui.components import display_summary_metrics, install_page_style
from ui.context_selector import initialise_active_context, render_context_selectors
from ui.leaders_tab import render_leaders_tab
from ui.players_tab import render_players_tab
from ui.stats_tab import render_stats_tab


ROOT = Path(__file__).resolve().parent


st.set_page_config(page_title="Fantasy Bundesliga Lab", page_icon="⚽", layout="wide")
install_page_style()

application_mode = get_application_mode()
if application_mode.allows_writes:
    from fantasy_ingestion.repository import FantasyIngestionRepository
    from ui.ingestion_tab import render_ingestion_tab
    from ui.quality_tab import render_quality_tab
    from ui.team_tab import render_team_tab

repository = FantasyRepository(writable=application_mode.allows_writes)
ingestion_repository = (
    FantasyIngestionRepository(repository.config, writable=True)
    if application_mode.allows_writes else None
)
try:
    database_cache_token = repository.cache_token()
    available_matchdays = load_available_matchdays(database_cache_token, repository)
    initial_context = initialise_active_context(available_matchdays)
except Exception as exc:
    st.error(str(exc))
    st.stop()

st.title("Fantasy Bundesliga Lab")
if application_mode.is_public:
    st.caption("Public read-only deployment")
if initial_context.fantasy_player_count:
    st.caption(
        f"Manual Fantasy Bundesliga Matchday {initial_context.matchday} data, "
        "with optional API-Football match-stat matching."
    )
else:
    st.caption(
        f"Fantasy Bundesliga Matchday {initial_context.matchday}, "
        "with optional API-Football match-stat matching."
    )
active_context = render_context_selectors(available_matchdays)
active_season = active_context.season
active_matchday = active_context.matchday

fantasy = load_fantasy(
    database_cache_token, active_season, active_matchday, repository
)
stats, stats_path = load_match_stats(
    database_cache_token, active_season, active_matchday, repository
)
name_map = load_name_map(repository, active_season, active_matchday)
manual_only = load_manual_only(repository, active_season, active_matchday)
combined = merge_with_stats(fantasy, stats, name_map, manual_only)
fantasy_source_path = repository.get_fantasy_source_path(active_season, active_matchday)

planning_matchday = repository.get_latest_fantasy_matchday_at_or_before(
    active_season, active_matchday
)
if planning_matchday is None:
    planning_fantasy = fantasy
    planning_combined = combined
else:
    planning_fantasy = load_planning_fantasy(
        database_cache_token, active_season, active_matchday, repository
    )
    if planning_fantasy.empty and planning_matchday == active_matchday:
        planning_fantasy = load_fantasy(
            database_cache_token, active_season, planning_matchday, repository
        )
    planning_stats, _ = load_match_stats(
        database_cache_token, active_season, planning_matchday, repository
    )
    planning_name_map = load_name_map(repository, active_season, planning_matchday)
    planning_manual_only = load_manual_only(repository, active_season, planning_matchday)
    planning_combined = merge_with_stats(
        planning_fantasy, planning_stats, planning_name_map, planning_manual_only
    )

if fantasy.empty:
    st.info(
        f"No official Fantasy Bundesliga player snapshot is available for Matchday {active_matchday}. "
        "My Team can still use the latest prior snapshot for transfer planning."
    )

player_count = f"{len(fantasy):,}"
club_count = f"{fantasy['club'].nunique():,}"
known_points_count = f"{fantasy['matchday_points'].notna().sum():,}"
if not stats.empty and not fantasy.empty:
    resolved_count = int((combined["match_status"] != "Unresolved").sum())
    status_label = "Resolved player status"
    status_value = f"{resolved_count}/{len(combined)}"
else:
    status_label = "Matched to API stats"
    status_value = "No API stats"
display_summary_metrics(
    player_count, club_count, known_points_count, status_label, status_value
)

if application_mode.is_public:
    players_tab, leaders_tab, stats_tab = st.tabs(
        ["Players", "Position leaders", "Match stats"]
    )
    team_tab = quality_tab = ingestion_tab = None
else:
    players_tab, team_tab, leaders_tab, stats_tab, quality_tab, ingestion_tab = st.tabs(
        ["Players", "My Team", "Position leaders", "Match stats", "Data quality", "Ingestion"]
    )

with players_tab:
    render_players_tab(fantasy, combined, active_season, active_matchday)

if team_tab is not None:
    with team_tab:
        render_team_tab(
            repository,
            active_season,
            active_matchday,
            planning_fantasy,
            planning_combined,
            planning_matchday,
        )

with leaders_tab:
    render_leaders_tab(fantasy, active_season, active_matchday)

with stats_tab:
    render_stats_tab(
        stats, stats_path, combined, active_matchday, not fantasy.empty
    )

if quality_tab is not None:
    with quality_tab:
        render_quality_tab(
            repository,
            active_season,
            active_matchday,
            fantasy,
            stats,
            combined,
            stats_path,
            fantasy_source_path,
            ROOT,
        )

if ingestion_tab is not None and ingestion_repository is not None:
    with ingestion_tab:
        render_ingestion_tab(
            ingestion_repository,
            active_season,
            active_matchday,
        )
