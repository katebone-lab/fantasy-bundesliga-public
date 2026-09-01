#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "fantasy_bundesliga.sqlite"
PATCH = ROOT / "data" / "md2_additional_confirmed_prices.csv"
SOURCE_PATH = "public://md2-additional-confirmed-prices/2026-09-02"
SOURCE_KIND = "fantasy_screenshot_correction"
EXPECTED_ROWS = 1
EXPECTED_MD1_TOTAL = 255
EXPECTED_MD2_TOTAL = 223


def main() -> None:
    rows = list(csv.DictReader(PATCH.open(encoding="utf-8")))
    if len(rows) != EXPECTED_ROWS:
        raise SystemExit(f"Expected {EXPECTED_ROWS} patch row, found {len(rows)}")
    digest = hashlib.sha256(PATCH.read_bytes()).hexdigest()

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

        source = conn.execute(
            "SELECT source_import_id FROM source_imports WHERE source_path=? AND sha256=?",
            (SOURCE_PATH, digest),
        ).fetchone()
        if source:
            source_import_id = int(source[0])
        else:
            cur = conn.execute(
                "INSERT INTO source_imports(source_path,source_kind,sha256,row_count) VALUES (?,?,?,?)",
                (SOURCE_PATH, SOURCE_KIND, digest, len(rows)),
            )
            source_import_id = int(cur.lastrowid)

        inserted = 0
        identical = 0
        for row in rows:
            player_name = row["player"]
            proposed = int(round(float(row["md2_price_m"]) * 100))
            player = conn.execute(
                "SELECT player_id FROM players WHERE canonical_name=?", (player_name,)
            ).fetchone()
            if player is None:
                raise SystemExit(f"Unresolved player: {player_name}")
            player_id = int(player[0])
            existing = conn.execute(
                "SELECT fantasy_player_price_id,price_hundredths_m FROM fantasy_player_prices WHERE player_id=? AND effective_matchday_id=?",
                (player_id, md2_id),
            ).fetchone()
            if existing:
                if int(existing["price_hundredths_m"]) != proposed:
                    raise SystemExit(
                        f"Refusing conflicting MD2 price for {player_name}: existing={existing['price_hundredths_m']/100:.2f}, proposed={proposed/100:.2f}"
                    )
                identical += 1
                continue
            conn.execute(
                """INSERT INTO fantasy_player_prices
                   (player_id,effective_matchday_id,price_hundredths_m,observed_after_matchday_id,source_import_id)
                   VALUES (?,?,?,?,?)""",
                (player_id, md2_id, proposed, md1_id, source_import_id),
            )
            inserted += 1

        md1_count = conn.execute(
            "SELECT COUNT(*) FROM fantasy_player_prices WHERE effective_matchday_id=?", (md1_id,)
        ).fetchone()[0]
        md2_count = conn.execute(
            "SELECT COUNT(*) FROM fantasy_player_prices WHERE effective_matchday_id=?", (md2_id,)
        ).fetchone()[0]
        bredlow = conn.execute(
            """SELECT price_m,price_movement_hundredths_m/100.0 AS movement_m
               FROM vw_fantasy_price_history
               WHERE player='Fabian Bredlow' AND season=2026 AND effective_matchday=2"""
        ).fetchone()
        if md1_count != EXPECTED_MD1_TOTAL or md2_count != EXPECTED_MD2_TOTAL:
            raise SystemExit(f"Unexpected price counts: md1={md1_count} md2={md2_count}")
        if bredlow is None or round(bredlow["price_m"], 2) != 4.84:
            raise SystemExit(f"Bredlow validation failed: {dict(bredlow) if bredlow else None}")
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            raise SystemExit(f"Foreign-key violations: {fk}")
        conn.commit()

    print(f"inserted={inserted} identical={identical} md1_prices={md1_count} md2_prices={md2_count}")
    print(f"bredlow_md2_price={bredlow['price_m']:.2f} bredlow_movement={bredlow['movement_m']:+.2f}")


if __name__ == "__main__":
    main()
