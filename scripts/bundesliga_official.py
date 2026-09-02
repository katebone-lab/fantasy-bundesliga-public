from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Iterable

import requests

BASE_URL = "https://www.bundesliga.com/en/bundesliga/matchday/2026-2027/{matchday}/"
USER_AGENT = "FantasyBundesligaLab/1.0 (+read-only results sync)"

ALIASES = {
    "Bayern Munich": "FC Bayern München",
    "Bayern München": "FC Bayern München",
    "Borussia Monchengladbach": "Borussia Mönchengladbach",
    "Borussia M'gladbach": "Borussia Mönchengladbach",
    "Mainz 05": "1. FSV Mainz 05",
    "Union Berlin": "1. FC Union Berlin",
    "Koln": "1. FC Köln",
    "Köln": "1. FC Köln",
    "Werder Bremen": "SV Werder Bremen",
    "Paderborn": "SC Paderborn 07",
    "Schalke": "FC Schalke 04",
    "Leverkusen": "Bayer 04 Leverkusen",
    "Hoffenheim": "TSG Hoffenheim",
    "Frankfurt": "Eintracht Frankfurt",
    "Augsburg": "FC Augsburg",
    "Freiburg": "SC Freiburg",
    "Stuttgart": "VfB Stuttgart",
    "Dortmund": "Borussia Dortmund",
    "Hamburg": "Hamburger SV",
    "Elversberg": "SV Elversberg",
    "RB Leipzig": "RB Leipzig",
}


@dataclass(frozen=True)
class MatchEvent:
    home_club: str
    away_club: str
    home_goals: int | None = None
    away_goals: int | None = None
    kickoff: str | None = None
    status: str | None = None


class ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_script = False
        self.current: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self.in_script = True
            self.current = []

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self.in_script:
            text = "".join(self.current).strip()
            if text:
                self.scripts.append(text)
            self.in_script = False
            self.current = []


def normalise_club(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("name", "clubName", "teamName", "fullName", "title"):
            if value.get(key):
                return normalise_club(value[key])
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return ALIASES.get(text, text) if text else None


def _first(obj: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return None


def _score(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        value = _first(value, ("score", "goals", "value", "current"))
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def event_from_dict(obj: dict[str, Any]) -> MatchEvent | None:
    home = _first(obj, ("homeTeam", "home", "team1", "homeClub"))
    away = _first(obj, ("awayTeam", "away", "team2", "awayClub"))
    home_name = normalise_club(home)
    away_name = normalise_club(away)
    if not home_name or not away_name or home_name == away_name:
        return None

    home_score = _score(_first(obj, ("homeScore", "homeGoals", "scoreHome", "team1Score")))
    away_score = _score(_first(obj, ("awayScore", "awayGoals", "scoreAway", "team2Score")))
    score_obj = obj.get("score")
    if isinstance(score_obj, dict):
        home_score = home_score if home_score is not None else _score(
            _first(score_obj, ("home", "homeScore", "homeGoals"))
        )
        away_score = away_score if away_score is not None else _score(
            _first(score_obj, ("away", "awayScore", "awayGoals"))
        )

    kickoff = _first(obj, ("startDate", "kickoff", "kickOff", "dateTime", "datetime"))
    status = _first(obj, ("eventStatus", "status", "matchStatus", "state"))
    return MatchEvent(
        home_club=home_name,
        away_club=away_name,
        home_goals=home_score,
        away_goals=away_score,
        kickoff=str(kickoff) if kickoff else None,
        status=str(status) if status else None,
    )


def walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def parse_events(html: str) -> list[MatchEvent]:
    parser = ScriptCollector()
    parser.feed(html)
    found: dict[tuple[str, str], MatchEvent] = {}

    for script in parser.scripts:
        candidates: list[Any] = []
        stripped = script.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                candidates.append(json.loads(stripped))
            except json.JSONDecodeError:
                pass
        for match in re.finditer(r"(?:__NEXT_DATA__|applicationState)\s*=\s*({.*?})\s*;?\s*$", stripped, re.S):
            try:
                candidates.append(json.loads(match.group(1)))
            except json.JSONDecodeError:
                pass

        for candidate in candidates:
            for obj in walk_json(candidate):
                event = event_from_dict(obj)
                if not event:
                    continue
                key = (event.home_club, event.away_club)
                previous = found.get(key)
                # Prefer the richer representation when the same fixture appears repeatedly.
                if previous is None or (
                    previous.home_goals is None and event.home_goals is not None
                ) or (previous.kickoff is None and event.kickoff is not None):
                    found[key] = event

    return list(found.values())


def fetch_matchday(matchday: int, timeout: int = 30) -> tuple[str, list[MatchEvent]]:
    url = BASE_URL.format(matchday=int(matchday))
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9"},
        timeout=timeout,
    )
    response.raise_for_status()
    return url, parse_events(response.text)
