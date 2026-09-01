from __future__ import annotations

import py_compile
from pathlib import Path

from fixture_model import build_fixture_ratings, build_team_strengths, lineup_likelihood


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    strengths = build_team_strengths()
    fixtures = build_fixture_ratings(2)

    if len(strengths) != 18 or strengths["club"].nunique() != 18:
        raise SystemExit(f"Expected 18 unique team strengths, found {len(strengths)} rows")
    if len(fixtures) != 18 or fixtures["club"].nunique() != 18:
        raise SystemExit(f"Expected 18 unique MD2 fixture rows, found {len(fixtures)} rows")
    if strengths[["attack_strength", "defence_strength", "overall_strength"]].isna().any().any():
        raise SystemExit("Team strength model contains null ratings")
    if fixtures[["attack_fixture_ease", "defence_fixture_ease", "overall_fixture_ease"]].isna().any().any():
        raise SystemExit("Fixture model contains null ease ratings")
    if not fixtures["overall_fixture_ease"].between(0, 100).all():
        raise SystemExit("Fixture ease must stay between 0 and 100")

    starter, _ = lineup_likelihood(90, False)
    sub, _ = lineup_likelihood(20, True)
    absent, _ = lineup_likelihood(None, None)
    if not starter > sub > absent:
        raise SystemExit("Lineup likelihood ordering is invalid")

    py_compile.compile(str(ROOT / "fixture_model.py"), doraise=True)
    py_compile.compile(str(ROOT / "ui" / "public_team_tab.py"), doraise=True)

    print("fixture_model_validation=ok")
    print(f"team_strength_rows={len(strengths)} fixture_rows={len(fixtures)}")
    print(strengths[["club", "attack_strength", "defence_strength", "overall_strength"]].head(8).to_string(index=False))
    print(fixtures[["club", "opponent", "venue", "overall_fixture_ease"]].sort_values("overall_fixture_ease", ascending=False).head(8).to_string(index=False))


if __name__ == "__main__":
    main()
