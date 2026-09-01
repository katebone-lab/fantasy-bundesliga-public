from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

import pandas as pd

from app_constants import CLUB_ALIASES


def normalise_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalise_club(value: str | None) -> str:
    key = normalise_text(value)
    return CLUB_ALIASES.get(key, key)


def ranked_api_candidates(
    player_key: str, club_key: str, stats: pd.DataFrame
) -> list[tuple[str, float]]:
    """Return same-club API names ranked only as review suggestions."""
    if stats.empty or not {"club_key", "player"}.issubset(stats.columns):
        return []
    same_club_names = (
        stats.loc[stats["club_key"] == club_key, "player"]
        .dropna()
        .astype(str)
        .unique()
    )
    ranked = [
        (api_name, SequenceMatcher(None, player_key, normalise_text(api_name)).ratio())
        for api_name in same_club_names
    ]
    return sorted(ranked, key=lambda item: (-item[1], normalise_text(item[0])))


def apply_name_map(fantasy: pd.DataFrame, name_map: pd.DataFrame) -> pd.DataFrame:
    out = fantasy.copy()
    out["match_player_key"] = out["player_key"]
    if name_map.empty:
        return out
    lookup = {
        (str(row.fantasy_name), str(row.club)): normalise_text(str(row.api_name))
        for row in name_map.itertuples(index=False)
    }
    out["match_player_key"] = [
        lookup.get((str(player), str(club)), player_key)
        for player, club, player_key in zip(out["player"], out["club"], out["player_key"])
    ]
    return out


def merge_with_stats(
    fantasy: pd.DataFrame,
    stats: pd.DataFrame,
    name_map: pd.DataFrame,
    manual_only: pd.DataFrame,
) -> pd.DataFrame:
    fantasy_for_match = apply_name_map(fantasy, name_map)
    manual_only_keys = {
        (str(row.fantasy_name), str(row.club))
        for row in manual_only.itertuples(index=False)
    }
    if stats.empty:
        out = fantasy_for_match.copy()
        out["api_match"] = False
        out["manual_only"] = [
            (str(player), str(club)) in manual_only_keys
            for player, club in zip(out["player"], out["club"])
        ]
        out["match_status"] = out["manual_only"].map(
            {True: "Manual-only", False: "Unresolved"}
        )
        return out

    keep = [
        "player_key", "club_key", "api_player_id", "fixture_id", "date", "status", "team",
        "opponent", "home_team", "away_team", "home_goals", "away_goals", "minutes", "rating",
        "goals", "assists", "shots", "shots_on_target", "key_passes", "tackles",
        "blocks", "interceptions", "duels_total", "duels_won", "dribbles_attempts",
        "dribbles_success", "fouls_drawn", "fouls_committed", "saves", "goals_conceded",
        "yellow_cards", "red_cards", "penalties_won", "penalties_scored",
        "penalties_missed", "penalties_saved", "captain", "substitute",
    ]
    keep = [column for column in keep if column in stats.columns]
    stats_one = stats[keep].drop_duplicates(subset=["player_key", "club_key"], keep="first")
    stats_one = stats_one.rename(columns={"player_key": "match_player_key"})
    out = fantasy_for_match.merge(stats_one, on=["match_player_key", "club_key"], how="left")
    out["api_match"] = out.get("api_player_id").notna() if "api_player_id" in out.columns else False
    out["manual_only"] = [
        (str(player), str(club)) in manual_only_keys
        for player, club in zip(out["player"], out["club"])
    ]
    out["match_status"] = "Unresolved"
    out.loc[out["manual_only"], "match_status"] = "Manual-only"
    out.loc[out["api_match"], "match_status"] = "Matched"
    return out
