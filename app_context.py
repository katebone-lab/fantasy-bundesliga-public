from __future__ import annotations

from data_repository import MatchdayAvailability


def choose_default_matchday(
    available: list[MatchdayAvailability],
) -> MatchdayAvailability:
    if not available:
        raise ValueError("No seasons or matchdays are registered in SQLite")
    with_fantasy = [item for item in available if item.fantasy_player_count > 0]
    candidates = with_fantasy or available
    return max(candidates, key=lambda item: (item.season, item.matchday))


def format_season(season: int) -> str:
    return f"{season}/{str(season + 1)[-2:]}"


def format_matchday_option(item: MatchdayAvailability) -> str:
    state_labels = [state.title() for state in item.squad_states]
    if item.fantasy_player_count and item.api_stat_count:
        data_label = "Fantasy + API"
    elif item.fantasy_player_count:
        data_label = "Fantasy"
    elif item.api_stat_count:
        data_label = "API"
    elif state_labels == ["Draft"]:
        return f"Matchday {item.matchday} · Draft only"
    else:
        data_label = "No imported matchday data"
    details = [data_label, *state_labels]
    return f"Matchday {item.matchday} · " + " · ".join(details)
