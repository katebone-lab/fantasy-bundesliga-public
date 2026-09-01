from __future__ import annotations

import csv
import hashlib
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "fantasy_bundesliga.sqlite"
CSV = ROOT / "data" / "md2_user_confirmed_prices_points.csv"

EXPECTED_OLD_MD2_PRICES = {
    "Kacper Potulski": 3.47,
    "Bambasé Conté": 9.95,
    "Bilal Nadir": 9.45,
    "Maximilian Rohr": 3.36,
    "Rayan Philippe": 3.02,
    "Woo-yeong Jeong": 3.33,
    "Raphael Obermair": 3.74,
}


def hundredths(value: float | str) -> int:
    return int(round(float(value) * 100))


def main() -> None:
    with CSV.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 7:
        raise SystemExit(f"Expected 7 user-confirmed rows, found {len(rows)}")

    digest = hashlib.sha256(CSV.read_bytes()).hexdigest()

    with sqlite3.connect(DB) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row

        md1_id = conn.execute(
            """SELECT md.matchday_id FROM matchdays md JOIN seasons s ON s.season_id=md.season_id
               WHERE s.start_year=2026 AND md.matchday_number=1"""
        ).fetchone()[0]
        md2_id = conn.execute(
            """SELECT md.matchday_id FROM matchdays md JOIN seasons s ON s.season_id=md.season_id
               WHERE s.start_year=2026 AND md.matchday_number=2"""
        ).fetchone()[0]

        existing_source = conn.execute(
            "SELECT source_import_id FROM source_imports WHERE sha256=? AND source_kind='user_confirmed_fantasy_correction'",
            (digest,),
        ).fetchone()
        if existing_source:
            source_import_id = existing_source[0]
        else:
            conn.execute(
                """INSERT INTO source_imports(source_path,source_kind,sha256,row_count)
                   VALUES (?,?,?,?)""",
                (
                    "data/md2_user_confirmed_prices_points.csv",
                    "user_confirmed_fantasy_correction",
                    digest,
                    len(rows),
                ),
            )
            source_import_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        updated = 0
        already_correct = 0
        for row in rows:
            name = row["player"]
            player = conn.execute(
                "SELECT player_id FROM players WHERE canonical_name=?", (name,)
            ).fetchone()
            if player is None:
                raise SystemExit(f"Unresolved player: {name}")
            player_id = player[0]

            # Points are independently supplied by the user. Validate them against the
            # operational MD1 performance fact; do not rewrite performance facts here.
            perf = conn.execute(
                """SELECT matchday_points FROM vw_fantasy_player_matchday
                   WHERE fantasy_player_id=? AND season=2026 AND matchday=1""",
                (player_id,),
            ).fetchone()
            expected_points = int(row["md1_points"])
            if perf is None:
                raise SystemExit(f"No MD1 performance row for {name}")
            if perf["matchday_points"] != expected_points:
                raise SystemExit(
                    f"MD1 points conflict for {name}: database has {perf['matchday_points']}, "
                    f"user confirmed {expected_points}"
                )

            price = conn.execute(
                """SELECT fantasy_player_price_id,price_hundredths_m,observed_after_matchday_id
                   FROM fantasy_player_prices
                   WHERE player_id=? AND effective_matchday_id=?""",
                (player_id, md2_id),
            ).fetchone()
            if price is None:
                raise SystemExit(f"No existing MD2 price row for {name}")

            old_h = hundredths(EXPECTED_OLD_MD2_PRICES[name])
            new_h = hundredths(row["md2_price_m"])
            if price["price_hundredths_m"] == new_h:
                already_correct += 1
                continue
            if price["price_hundredths_m"] != old_h:
                raise SystemExit(
                    f"MD2 price conflict for {name}: database has {price['price_hundredths_m']/100:.2f}, "
                    f"expected old {old_h/100:.2f} or new {new_h/100:.2f}"
                )
            if price["observed_after_matchday_id"] not in (None, md1_id):
                raise SystemExit(f"Unexpected temporal scope for {name}")

            conn.execute(
                """UPDATE fantasy_player_prices
                   SET price_hundredths_m=?, observed_after_matchday_id=?, source_import_id=?
                   WHERE fantasy_player_price_id=?""",
                (new_h, md1_id, source_import_id, price["fantasy_player_price_id"]),
            )
            updated += 1

        md1_count = conn.execute(
            "SELECT COUNT(*) FROM fantasy_player_prices WHERE effective_matchday_id=?", (md1_id,)
        ).fetchone()[0]
        md2_count = conn.execute(
            "SELECT COUNT(*) FROM fantasy_player_prices WHERE effective_matchday_id=?", (md2_id,)
        ).fetchone()[0]
        if md1_count != 255 or md2_count != 222:
            raise SystemExit(f"Unexpected price counts: MD1={md1_count}, MD2={md2_count}")

        # Ensure the seven formerly implausible rows now reproduce movement from the
        # corrected MD1 opening baseline rather than storing an independent movement.
        movements = conn.execute(
            """SELECT player,price_m,price_movement_hundredths_m/100.0 AS movement_m
               FROM vw_fantasy_price_history
               WHERE season=2026 AND effective_matchday=2
                 AND player IN (?,?,?,?,?,?,?) ORDER BY player""",
            tuple(EXPECTED_OLD_MD2_PRICES),
        ).fetchall()
        if len(movements) != 7:
            raise SystemExit(f"Expected 7 movement rows, found {len(movements)}")

        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            raise SystemExit(f"Foreign-key violations: {fk}")

        conn.commit()
        print(f"updated={updated} already_correct={already_correct} md1_prices={md1_count} md2_prices={md2_count}")
        for row in movements:
            print(f"{row['player']}: md2={row['price_m']:.2f} movement={row['movement_m']:+.2f}")


if __name__ == "__main__":
    main()
