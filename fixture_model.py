from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data" / "fixture_model"
PRIOR_WEIGHT = 0.70
CURRENT_WEIGHT = 0.30
PROMOTED_ATTACK_FACTOR = 0.78
PROMOTED_DEFENCE_FACTOR = 0.82
CURRENT_SMOOTHING_MATCHES = 2.0

POSITION_ATTACK_WEIGHT = {
    "GK": 0.15,
    "DEF": 0.25,
    "MID": 0.65,
    "FOR": 0.90,
}


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA_ROOT / name)


def build_team_strengths() -> pd.DataFrame:
    """Return early-season attack/defence strengths centred around 1.0.

    The model intentionally keeps prior-season evidence separate from current results.
    Retained Bundesliga clubs use their 2025/26 goals-for/goals-against rates directly.
    Promoted clubs use their 2. Bundesliga rates with a conservative promotion adjustment.
    Matchday 1 evidence is smoothed with two league-average pseudo-matches before being
    blended 70/30 with the prior, so one result can move a rating without dominating it.
    """
    prior = _read("2025_26_prior.csv")
    results = _read("2026_md01_results.csv")

    retained = prior[prior["source_league"] == "Bundesliga"].copy()
    avg_prior_goals = (retained["goals_for"] / retained["played"]).mean()
    avg_prior_against = (retained["goals_against"] / retained["played"]).mean()

    prior["prior_attack"] = (prior["goals_for"] / prior["played"]) / avg_prior_goals
    prior["prior_defence"] = avg_prior_against / (prior["goals_against"] / prior["played"])
    promoted = prior["source_league"] != "Bundesliga"
    prior.loc[promoted, "prior_attack"] *= PROMOTED_ATTACK_FACTOR
    prior.loc[promoted, "prior_defence"] *= PROMOTED_DEFENCE_FACTOR

    home = results[["home_club", "home_goals", "away_goals"]].rename(
        columns={"home_club": "club", "home_goals": "gf", "away_goals": "ga"}
    )
    away = results[["away_club", "away_goals", "home_goals"]].rename(
        columns={"away_club": "club", "away_goals": "gf", "home_goals": "ga"}
    )
    current = pd.concat([home, away], ignore_index=True).groupby("club", as_index=False).agg(
        games=("gf", "size"), gf=("gf", "sum"), ga=("ga", "sum")
    )
    league_goal_rate = current["gf"].sum() / current["games"].sum()
    smooth = CURRENT_SMOOTHING_MATCHES
    current["smoothed_gf_pg"] = (current["gf"] + smooth * league_goal_rate) / (
        current["games"] + smooth
    )
    current["smoothed_ga_pg"] = (current["ga"] + smooth * league_goal_rate) / (
        current["games"] + smooth
    )
    current["current_attack"] = current["smoothed_gf_pg"] / league_goal_rate
    current["current_defence"] = league_goal_rate / current["smoothed_ga_pg"]

    strength = prior.merge(current, on="club", how="left", validate="one_to_one")
    strength["current_attack"] = strength["current_attack"].fillna(1.0)
    strength["current_defence"] = strength["current_defence"].fillna(1.0)
    strength["attack_strength"] = (
        PRIOR_WEIGHT * strength["prior_attack"] + CURRENT_WEIGHT * strength["current_attack"]
    )
    strength["defence_strength"] = (
        PRIOR_WEIGHT * strength["prior_defence"] + CURRENT_WEIGHT * strength["current_defence"]
    )
    strength["overall_strength"] = np.sqrt(
        strength["attack_strength"] * strength["defence_strength"]
    )
    return strength[
        [
            "club",
            "source_league",
            "prior_attack",
            "prior_defence",
            "current_attack",
            "current_defence",
            "attack_strength",
            "defence_strength",
            "overall_strength",
        ]
    ].sort_values("overall_strength", ascending=False)


def build_fixture_ratings(matchday: int = 2) -> pd.DataFrame:
    """Return one row per club with opponent and position-neutral fixture components.

    Higher ease scores are better for the player's club. They are percentile ranks among
    the 18 teams on the matchday rather than externally supplied FDR numbers.
    """
    fixtures = _read("2026_md02_fixtures.csv")
    fixtures = fixtures[fixtures["matchday"] == matchday].copy()
    strengths = build_team_strengths().set_index("club")

    rows: list[dict] = []
    for fixture in fixtures.itertuples(index=False):
        for club, opponent, venue in (
            (fixture.home_club, fixture.away_club, "H"),
            (fixture.away_club, fixture.home_club, "A"),
        ):
            own = strengths.loc[club]
            opp = strengths.loc[opponent]
            attack_location = 1.06 if venue == "H" else 0.97
            defence_location = 1.04 if venue == "H" else 0.98
            attack_raw = own.attack_strength / opp.defence_strength * attack_location
            defence_raw = own.defence_strength / opp.attack_strength * defence_location
            rows.append(
                {
                    "club": club,
                    "opponent": opponent,
                    "venue": venue,
                    "kickoff_local": fixture.kickoff_local,
                    "attack_fixture_raw": float(attack_raw),
                    "defence_fixture_raw": float(defence_raw),
                }
            )

    frame = pd.DataFrame(rows)
    frame["attack_fixture_ease"] = frame["attack_fixture_raw"].rank(pct=True) * 100
    frame["defence_fixture_ease"] = frame["defence_fixture_raw"].rank(pct=True) * 100
    frame["overall_fixture_ease"] = (
        frame["attack_fixture_ease"] + frame["defence_fixture_ease"]
    ) / 2
    return frame.sort_values("club").reset_index(drop=True)


def position_fixture_ease(position: str, attack_ease: float, defence_ease: float) -> float:
    attack_weight = POSITION_ATTACK_WEIGHT.get(str(position), 0.5)
    return attack_weight * float(attack_ease) + (1.0 - attack_weight) * float(defence_ease)


def fixture_label(ease: float | int | None) -> str:
    if ease is None or pd.isna(ease):
        return "Unknown"
    ease = float(ease)
    if ease >= 80:
        return "Very favourable"
    if ease >= 60:
        return "Favourable"
    if ease >= 40:
        return "Neutral"
    if ease >= 20:
        return "Tough"
    return "Very tough"


def lineup_likelihood(minutes: float | int | None, substitute: bool | None) -> tuple[float, str]:
    """Convert the MD1 role into a deliberately conservative MD2 lineup proxy.

    This is not a predicted team sheet. It is an auditable role prior that can later be
    overridden by injury/news/probable-lineup evidence closer to the deadline.
    """
    if minutes is None or pd.isna(minutes) or float(minutes) <= 0:
        return 20.0, "Low · no MD1 appearance"
    minutes = float(minutes)
    if substitute is False or substitute == 0:
        if minutes >= 75:
            return 95.0, "Very high · MD1 starter"
        if minutes >= 60:
            return 90.0, "High · MD1 starter"
        if minutes >= 45:
            return 82.0, "High · MD1 starter"
        return 70.0, "Medium-high · MD1 starter"
    if minutes >= 30:
        return 60.0, "Medium · substantial MD1 sub"
    if minutes >= 15:
        return 45.0, "Medium-low · MD1 sub"
    return 30.0, "Low · brief MD1 sub"


def add_planning_components(frame: pd.DataFrame, matchday: int = 2) -> pd.DataFrame:
    """Attach fixture, role and transparent composite planning components to players."""
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    fixtures = build_fixture_ratings(matchday)
    out = out.merge(fixtures, on="club", how="left", validate="many_to_one")

    out["fixture_ease"] = out.apply(
        lambda row: position_fixture_ease(
            row.get("fantasy_position"),
            row.get("attack_fixture_ease"),
            row.get("defence_fixture_ease"),
        )
        if pd.notna(row.get("attack_fixture_ease")) and pd.notna(row.get("defence_fixture_ease"))
        else np.nan,
        axis=1,
    )
    out["fixture_label"] = out["fixture_ease"].map(fixture_label)

    role = out.apply(
        lambda row: lineup_likelihood(row.get("minutes"), row.get("substitute")), axis=1
    )
    out["lineup_likelihood"] = role.map(lambda value: value[0])
    out["lineup_label"] = role.map(lambda value: value[1])

    points = pd.to_numeric(out.get("matchday_points"), errors="coerce")
    value = pd.to_numeric(out.get("points_per_m"), errors="coerce")
    points_pct = points.rank(pct=True) * 100
    value_pct = value.rank(pct=True) * 100

    # Missing MD1 points/value stay neutral rather than being silently treated as zero.
    out["performance_component"] = points_pct.fillna(50.0)
    out["value_component"] = value_pct.fillna(50.0)
    out["planning_score"] = (
        0.30 * out["performance_component"]
        + 0.15 * out["value_component"]
        + 0.30 * out["fixture_ease"].fillna(50.0)
        + 0.25 * out["lineup_likelihood"].fillna(20.0)
    )
    return out
