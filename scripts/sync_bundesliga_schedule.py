from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from bundesliga_official import fetch_matchday

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "fixture_model"
SCHEDULE_PATH = DATA / "2026_fixtures_md02_md08.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--review-dir", default="artifacts/bundesliga_sync")
    args = parser.parse_args()

    schedule = pd.read_csv(SCHEDULE_PATH)
    if "kickoff_local" not in schedule.columns:
        schedule["kickoff_local"] = ""

    known_pairs = {
        (int(row.matchday), row.home_club, row.away_club)
        for row in schedule.itertuples(index=False)
    }
    updates: list[dict] = []
    unexpected: list[list] = []

    for matchday in sorted(schedule["matchday"].unique()):
        source_url, events = fetch_matchday(int(matchday))
        for event in events:
            key = (int(matchday), event.home_club, event.away_club)
            if key not in known_pairs:
                unexpected.append(list(key))
                continue
            if not event.kickoff:
                continue
            updates.append(
                {
                    "matchday": int(matchday),
                    "home_club": event.home_club,
                    "away_club": event.away_club,
                    "kickoff_local": event.kickoff,
                    "source": source_url,
                }
            )

    update_frame = pd.DataFrame(updates)
    review_dir = ROOT / args.review_dir
    review_dir.mkdir(parents=True, exist_ok=True)
    update_frame.to_csv(review_dir / "proposed_schedule_details.csv", index=False)

    changed = 0
    if not update_frame.empty:
        indexed = schedule.set_index(["matchday", "home_club", "away_club"])
        for row in update_frame.itertuples(index=False):
            key = (row.matchday, row.home_club, row.away_club)
            old = str(indexed.at[key, "kickoff_local"] or "")
            if old != row.kickoff_local:
                changed += 1
                indexed.at[key, "kickoff_local"] = row.kickoff_local
        schedule = indexed.reset_index()

    if args.write and changed:
        schedule.to_csv(SCHEDULE_PATH, index=False)

    summary = {
        "scheduled_fixtures": len(schedule),
        "kickoff_details_found": len(update_frame),
        "kickoff_changes_proposed": changed,
        "write_mode": bool(args.write),
        "unexpected_page_pairs_ignored": unexpected,
    }
    (review_dir / "schedule_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
