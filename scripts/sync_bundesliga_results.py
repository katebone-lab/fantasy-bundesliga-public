from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from bundesliga_official import fetch_matchday

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "fixture_model"
RESULTS_PATH = DATA / "2026_results.csv"
SCHEDULE_PATH = DATA / "2026_fixtures_md02_md08.csv"


def load_expected(matchday: int) -> pd.DataFrame:
    schedule = pd.read_csv(SCHEDULE_PATH)
    expected = schedule[schedule["matchday"] == matchday][["home_club", "away_club"]].copy()
    if len(expected) != 9:
        raise SystemExit(f"Expected 9 scheduled fixtures for MD{matchday}, found {len(expected)}")
    if expected.duplicated().any():
        raise SystemExit(f"Duplicate scheduled fixture in MD{matchday}")
    return expected


def next_incomplete_matchday() -> int:
    results = pd.read_csv(RESULTS_PATH)
    schedule = pd.read_csv(SCHEDULE_PATH)
    for md in sorted(schedule["matchday"].unique()):
        played = results[results["matchday"] == md]
        if len(played) < 9:
            return int(md)
    return int(schedule["matchday"].max())


def fetch_and_validate(matchday: int) -> tuple[pd.DataFrame, dict]:
    expected = load_expected(matchday)
    source_url, events = fetch_matchday(matchday)
    expected_pairs = set(map(tuple, expected[["home_club", "away_club"]].itertuples(index=False, name=None)))

    observed = []
    unexpected = []
    for event in events:
        pair = (event.home_club, event.away_club)
        if pair not in expected_pairs:
            unexpected.append(pair)
            continue
        if event.home_goals is None or event.away_goals is None:
            continue
        if event.home_goals < 0 or event.away_goals < 0:
            raise SystemExit(f"Negative score returned for {pair}")
        observed.append(
            {
                "season": 2026,
                "matchday": matchday,
                "home_club": event.home_club,
                "away_club": event.away_club,
                "home_goals": int(event.home_goals),
                "away_goals": int(event.away_goals),
                "status": "final",
                "played_at": event.kickoff or "",
                "source": source_url,
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )

    frame = pd.DataFrame(observed)
    if frame.empty:
        frame = pd.DataFrame(columns=[
            "season", "matchday", "home_club", "away_club", "home_goals", "away_goals",
            "status", "played_at", "source", "captured_at"
        ])
    if frame.duplicated(["home_club", "away_club"]).any():
        raise SystemExit(f"Duplicate observed fixture in MD{matchday}")

    observed_pairs = set(map(tuple, frame[["home_club", "away_club"]].itertuples(index=False, name=None)))
    summary = {
        "matchday": matchday,
        "source": source_url,
        "expected_fixtures": 9,
        "completed_results_found": len(frame),
        "matchday_complete": len(frame) == 9,
        "missing_fixtures": [list(pair) for pair in sorted(expected_pairs - observed_pairs)],
        "unexpected_page_pairs_ignored": [list(pair) for pair in sorted(set(unexpected))],
    }
    return frame, summary


def check_conflicts(proposed: pd.DataFrame) -> None:
    existing = pd.read_csv(RESULTS_PATH)
    if proposed.empty:
        return
    merged = proposed.merge(
        existing,
        on=["season", "matchday", "home_club", "away_club"],
        how="inner",
        suffixes=("_new", "_old"),
    )
    conflicts = merged[
        (merged["home_goals_new"] != merged["home_goals_old"])
        | (merged["away_goals_new"] != merged["away_goals_old"])
    ]
    if not conflicts.empty:
        rows = conflicts[["home_club", "away_club", "home_goals_old", "away_goals_old", "home_goals_new", "away_goals_new"]]
        raise SystemExit("Published score conflict; manual review required:\n" + rows.to_string(index=False))


def merge_results(proposed: pd.DataFrame) -> int:
    existing = pd.read_csv(RESULTS_PATH)
    check_conflicts(proposed)
    keys = ["season", "matchday", "home_club", "away_club"]
    existing_keys = set(map(tuple, existing[keys].itertuples(index=False, name=None)))
    new_rows = proposed[~proposed[keys].apply(tuple, axis=1).isin(existing_keys)].copy()
    if new_rows.empty:
        return 0
    combined = pd.concat([existing, new_rows], ignore_index=True)
    combined = combined.sort_values(["matchday", "played_at", "home_club"], na_position="last")
    combined.to_csv(RESULTS_PATH, index=False)
    return len(new_rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matchday", type=int)
    parser.add_argument("--write", action="store_true", help="Append validated new results to 2026_results.csv")
    parser.add_argument("--review-dir", default="artifacts/bundesliga_sync")
    args = parser.parse_args()

    matchday = args.matchday or next_incomplete_matchday()
    proposed, summary = fetch_and_validate(matchday)
    check_conflicts(proposed)

    review_dir = ROOT / args.review_dir
    review_dir.mkdir(parents=True, exist_ok=True)
    proposed.to_csv(review_dir / f"md{matchday:02d}_proposed_results.csv", index=False)
    (review_dir / f"md{matchday:02d}_results_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    inserted = merge_results(proposed) if args.write else 0
    summary["write_mode"] = bool(args.write)
    summary["rows_inserted"] = inserted
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
