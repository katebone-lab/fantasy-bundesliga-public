from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from fixture_model import build_team_strengths, season_evidence_weights

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "fixture_model"
RESULTS = DATA / "2026_results.csv"


def build_table(results: pd.DataFrame) -> pd.DataFrame:
    clubs = sorted(set(results["home_club"]) | set(results["away_club"]))
    rows = []
    for club in clubs:
        home = results[results["home_club"] == club]
        away = results[results["away_club"] == club]
        gf = int(home["home_goals"].sum() + away["away_goals"].sum())
        ga = int(home["away_goals"].sum() + away["home_goals"].sum())
        wins = int((home["home_goals"] > home["away_goals"]).sum() + (away["away_goals"] > away["home_goals"]).sum())
        draws = int((home["home_goals"] == home["away_goals"]).sum() + (away["away_goals"] == away["home_goals"]).sum())
        played = len(home) + len(away)
        rows.append({
            "club": club, "played": played, "wins": wins, "draws": draws,
            "losses": played - wins - draws, "gf": gf, "ga": ga, "gd": gf - ga,
            "points": wins * 3 + draws,
        })
    return pd.DataFrame(rows).sort_values(["points", "gd", "gf"], ascending=[False, False, False])


def main() -> None:
    results = pd.read_csv(RESULTS)
    keys = ["season", "matchday", "home_club", "away_club"]
    if results.duplicated(keys).any():
        raise SystemExit("Duplicate result keys found")
    if (results[["home_goals", "away_goals"]].dropna() < 0).any().any():
        raise SystemExit("Negative score found")

    complete = {
        int(md): len(group) == 9
        for md, group in results.groupby("matchday")
    }
    latest_complete = max([md for md, ok in complete.items() if ok], default=0)
    prior_weight, current_weight = season_evidence_weights(latest_complete)

    strengths = build_team_strengths()
    if len(strengths) != 18 or strengths["club"].nunique() != 18:
        raise SystemExit("Team-strength model must contain exactly 18 clubs")
    if not strengths[["attack_strength", "defence_strength", "overall_strength"]].notna().all().all():
        raise SystemExit("Missing team-strength values")

    table = build_table(results)
    out = ROOT / "artifacts" / "bundesliga_sync"
    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / "derived_league_table.csv", index=False)
    strengths.to_csv(out / "derived_team_strengths.csv", index=False)
    summary = {
        "result_rows": len(results),
        "latest_complete_matchday": latest_complete,
        "complete_matchdays": [md for md, ok in complete.items() if ok],
        "prior_weight": round(prior_weight, 3),
        "current_weight": round(current_weight, 3),
        "team_strength_rows": len(strengths),
    }
    (out / "model_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
