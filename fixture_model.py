from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data" / "fixture_model"
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


def _complete_current_results() -> tuple[pd.DataFrame, int]:
    """Return only fully completed matchdays from the normalized results history.

    Sunday/provisional results may be stored without making the strength model jump during
    the weekend. A matchday enters the model only when all nine Bundesliga fixtures exist.
    """
    path = DATA_ROOT / "2026_results.csv"
    if not path.exists():
        legacy = _read("2026_md01_results.csv")
        return legacy, 1

    results = pd.read_csv(path)
    if results.empty:
        return results, 0
    if "status" in results.columns:
        results = results[results["status"].astype(str).str.lower().eq("final")].copy()
    complete_mds = [
        int(md)
        for md, group in results.groupby("matchday")
        if len(group) == 9
    ]
    if not complete_mds:
        return results.iloc[0:0].copy(), 0
    return results[results["matchday"].isin(complete_mds)].copy(), max(complete_mds)


def season_evidence_weights(completed_matchdays: int) -> tuple[float, float]:
    """Increase current-season authority gradually as evidence accumulates.

    MD1 = 30% current, MD3 = 40%, MD5 = 50%, MD10 = 75%; capped at 85% current.
    """
    current_weight = min(0.85, 0.25 + 0.05 * max(int(completed_matchdays), 1))
    return 1.0 - current_weight, current_weight


def build_team_strengths() -> pd.DataFrame:
    """Return attack/defence strengths centred around 1.0.

    Prior-season evidence and current Bundesliga results remain separate. Promoted clubs
    receive an explicit adjustment to their 2. Bundesliga prior. Current-season evidence
    only includes complete matchdays and gains weight gradually through the season.
    """
    prior = _read("2025_26_prior.csv")
    results, completed_matchdays = _complete_current_results()
    prior_weight, current_weight = season_evidence_weights(completed_matchdays)

    retained = prior[prior["source_league"] == "Bundesliga"].copy()
    avg_prior_goals = (retained["goals_for"] / retained["played"]).mean()
    avg_prior_against = (retained["goals_against"] / retained["played"]).mean()

    prior["prior_attack"] = (prior["goals_for"] / prior["played"]) / avg_prior_goals
    prior["prior_defence"] = avg_prior_against / (prior["goals_against"] / prior["played"])
    promoted = prior["source_league"] != "Bundesliga"
    prior.loc[promoted, "prior_attack"] *= PROMOTED_ATTACK_FACTOR
    prior.loc[promoted, "prior_defence"] *= PROMOTED_DEFENCE_FACTOR

    if results.empty:
        current = prior[["club"]].copy()
        current["current_attack"] = 1.0
        current["current_defence"] = 1.0
    else:
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

    strength = prior.merge(
        current[["club", "current_attack", "current_defence"]],
        on="club",
        how="left",
        validate="one_to_one",
    )
    strength["current_attack"] = strength["current_attack"].fillna(1.0)
    strength["current_defence"] = strength["current_defence"].fillna(1.0)
    strength["attack_strength"] = (
        prior_weight * strength["prior_attack"] + current_weight * strength["current_attack"]
    )
    strength["defence_strength"] = (
        prior_weight * strength["prior_defence"] + current_weight * strength["current_defence"]
    )
    strength["overall_strength"] = np.sqrt(
        strength["attack_strength"] * strength["defence_strength"]
    )
    strength["attack_strength_pct"] = strength["attack_strength"].rank(pct=True) * 100
    strength["defence_strength_pct"] = strength["defence_strength"].rank(pct=True) * 100
    strength["prior_weight"] = prior_weight
    strength["current_weight"] = current_weight
    strength["completed_matchdays"] = completed_matchdays
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
            "attack_strength_pct",
            "defence_strength_pct",
            "prior_weight",
            "current_weight",
            "completed_matchdays",
        ]
    ].sort_values("overall_strength", ascending=False)


def build_fixture_ratings(matchday: int = 2) -> pd.DataFrame:
    """Return one row per club with opponent and position-neutral fixture components."""
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
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    fixtures = build_fixture_ratings(matchday)
    out = out.merge(fixtures, on="club", how="left", validate="many_to_one")
    strengths = build_team_strengths()[
        ["club", "attack_strength_pct", "defence_strength_pct"]
    ]
    out = out.merge(strengths, on="club", how="left", validate="many_to_one")

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
    out["performance_component"] = points_pct.fillna(50.0)
    out["value_component"] = value_pct.fillna(50.0)
    out["planning_score"] = (
        0.30 * out["performance_component"]
        + 0.15 * out["value_component"]
        + 0.30 * out["fixture_ease"].fillna(50.0)
        + 0.25 * out["lineup_likelihood"].fillna(20.0)
    )

    def _team_component(row: pd.Series) -> float:
        position = str(row.get("fantasy_position"))
        attack = row.get("attack_strength_pct")
        defence = row.get("defence_strength_pct")
        attack = 50.0 if pd.isna(attack) else float(attack)
        defence = 50.0 if pd.isna(defence) else float(defence)
        if position in {"GK", "DEF"}:
            return defence
        if position == "FOR":
            return attack
        return 0.55 * attack + 0.45 * defence

    out["team_strength_component"] = out.apply(_team_component, axis=1)
    out["next_md_score"] = (
        0.35 * out["fixture_ease"].fillna(50.0)
        + 0.30 * out["lineup_likelihood"].fillna(20.0)
        + 0.20 * out["team_strength_component"].fillna(50.0)
        + 0.10 * out["performance_component"]
        + 0.05 * out["value_component"]
    )
    return out
