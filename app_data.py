from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from app_constants import AVAILABILITY_LABELS, POSITION_LABELS
from app_matching import normalise_club, normalise_text
from data_repository import FantasyRepository, MatchdayAvailability


@st.cache_data(show_spinner=False)
def load_available_matchdays(
    database_cache_token: int, _repository: FantasyRepository
) -> list[MatchdayAvailability]:
    del database_cache_token
    return _repository.get_available_matchdays()


@st.cache_data(show_spinner=False)
def load_fantasy(
    database_cache_token: int,
    season: int,
    matchday: int,
    _repository: FantasyRepository,
) -> pd.DataFrame:
    del database_cache_token
    df = _repository.get_fantasy_players(season, matchday)
    return prepare_fantasy(df)


@st.cache_data(show_spinner=False)
def load_planning_fantasy(database_cache_token: int, season: int, matchday: int,
                          _repository: FantasyRepository) -> pd.DataFrame:
    del database_cache_token
    return prepare_fantasy(_repository.get_planning_players(season, matchday))


def prepare_fantasy(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for column in ["price_m", "matchday_points", "points_per_m", "matchday"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df["position_name"] = df["fantasy_position"].map(POSITION_LABELS).fillna(df["fantasy_position"])
    df["availability_name"] = df["availability"].map(AVAILABILITY_LABELS).fillna(
        df["availability"].str.title()
    )
    df["player_key"] = df["player"].map(normalise_text)
    df["club_key"] = df["club"].map(normalise_club)
    return df


@st.cache_data(show_spinner=False)
def load_match_stats(
    database_cache_token: int,
    season: int,
    matchday: int,
    _repository: FantasyRepository,
) -> tuple[pd.DataFrame, Path | None]:
    del database_cache_token
    result = _repository.get_match_stats(season, matchday)
    stats, path = result.data, result.source_path
    if stats.empty:
        return stats, path
    stats["player_key"] = stats["player"].map(normalise_text)
    stats["club_key"] = stats["team"].map(normalise_club)
    numeric_columns = [
        "minutes", "rating", "shots", "shots_on_target", "goals", "assists",
        "goals_conceded", "saves", "key_passes", "passes_total", "tackles",
        "blocks", "interceptions", "duels_total", "duels_won",
        "dribbles_attempts", "dribbles_success", "fouls_drawn",
        "fouls_committed", "yellow_cards", "red_cards", "penalties_won",
        "penalties_scored", "penalties_missed", "penalties_saved",
    ]
    for column in numeric_columns:
        if column in stats.columns:
            stats[column] = pd.to_numeric(stats[column], errors="coerce")
    return stats, path


def load_name_map(repository: FantasyRepository, season: int, matchday: int) -> pd.DataFrame:
    return repository.get_approved_name_map(season, matchday)


def load_manual_only(repository: FantasyRepository, season: int, matchday: int) -> pd.DataFrame:
    return repository.get_manual_only_players(season, matchday)
