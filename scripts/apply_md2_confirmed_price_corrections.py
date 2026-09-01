from __future__ import annotations

import csv
import hashlib
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "fantasy_bundesliga.sqlite"
CSV = ROOT / "data" / "md2_confirmed_price_corrections.csv"


def hundredths(value: str) -> int:
    return int(round(float(value) * 100))


def main() -> None:
    with CSV.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 8:
        raise SystemExit(f"Expected 8 confirmed corrections, found {len(rows)}")

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
            "SELECT source_import_id FROM source_imports WHERE sha256=? AND source_kind='fantasy_screenshot_correction'",
            (digest,),
        ).fetchone()
        if existing_source:
            source_import_id = existing_source[0]
        else:
            conn.execute(
                """INSERT INTO source_imports(source_path,source_kind,sha256,row_count)
                   VALUES (?,?,?,?)""",
                (
                    "data/md2_confirmed_price_corrections.csv",
                    "fantasy_screenshot_correction",
                    digest,
                    len(rows),
                ),
            )
            source_import_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        updated = 0
        already_correct = 0
        for row in rows:
            player = conn.execute(
                "SELECT player_id FROM players WHERE canonical_name=?", (row["player"],)
            ).fetchone()
            if player is None:
                raise SystemExit(f"Unresolved player: {row['player']}")
            player_id = player[0]
            price = conn.execute(
                """SELECT fantasy_player_price_id,price_hundredths_m,observed_after_matchday_id
                   FROM fantasy_player_prices
                   WHERE player_id=? AND effective_matchday_id=?""",
                (player_id, md2_id),
            ).fetchone()
            if price is None:
                raise SystemExit(f"No existing MD2 price row for {row['player']}")

            old_h = hundredths(row["old_price_m"])
            new_h = hundredths(row["new_price_m"])
            if price["price_hundredths_m"] == new_h:
                already_correct += 1
                continue
            if price["price_hundredths_m"] != old_h:
                raise SystemExit(
                    f"Conflict for {row['player']}: database has {price['price_hundredths_m']/100:.2f}, "
                    f"expected old {old_h/100:.2f} or new {new_h/100:.2f}"
                )
            if price["observed_after_matchday_id"] not in (None, md1_id):
                raise SystemExit(f"Unexpected temporal scope for {row['player']}")

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
        if md1_count != 255:
            raise SystemExit(f"Expected 255 MD1 prices, found {md1_count}")
        if md2_count != 222:
            raise SystemExit(f"Expected 222 MD2 prices, found {md2_count}")

        schwabe = conn.execute(
            """SELECT price_m,price_movement_hundredths_m/100.0 AS movement_m
               FROM vw_fantasy_price_history
               WHERE player='Marvin Schwäbe' AND season=2026 AND effective_matchday=2"""
        ).fetchone()
        if schwabe is None or round(schwabe["price_m"], 2) != 8.80 or round(schwabe["movement_m"], 2) != 0.15:
            raise SystemExit(f"Schwäbe validation failed: {dict(schwabe) if schwabe else None}")

        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            raise SystemExit(f"Foreign-key violations: {fk}")

        conn.commit()
        print(f"updated={updated} already_correct={already_correct} md1_prices={md1_count} md2_prices={md2_count}")
        print(f"schwabe_md2_price={schwabe['price_m']:.2f} schwabe_movement={schwabe['movement_m']:+.2f}")


if __name__ == "__main__":
    main()
