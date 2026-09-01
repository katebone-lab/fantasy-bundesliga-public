#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "fantasy_bundesliga.sqlite"
PATCH = ROOT / "data" / "md1_opening_price_supplement.csv"
EXPECTED_TOTAL = 255
EXPECTED_PATCH_ROWS = 14
SOURCE_PATH = "public://md1-opening-price-supplement/2026-09-01"
SOURCE_KIND = "fantasy_price_reconciliation"


def main() -> None:
    rows = list(csv.DictReader(PATCH.open(encoding="utf-8")))
    if len(rows) != EXPECTED_PATCH_ROWS:
        raise SystemExit(f"Expected {EXPECTED_PATCH_ROWS} patch rows, found {len(rows)}")

    patch_sha = hashlib.sha256(PATCH.read_bytes()).hexdigest()

    with sqlite3.connect(DB) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        md1 = conn.execute(
            """
            SELECT md.matchday_id
            FROM matchdays md
            JOIN seasons s ON s.season_id = md.season_id
            WHERE s.start_year = 2026 AND md.matchday_number = 1
            """
        ).fetchone()
        if not md1:
            raise SystemExit("Could not resolve 2026 Matchday 1")
        md1_id = int(md1[0])

        source = conn.execute(
            "SELECT source_import_id FROM source_imports WHERE source_path = ? AND sha256 = ?",
            (SOURCE_PATH, patch_sha),
        ).fetchone()
        if source:
            source_import_id = int(source[0])
        else:
            cur = conn.execute(
                """
                INSERT INTO source_imports (source_path, source_kind, sha256, row_count)
                VALUES (?, ?, ?, ?)
                """,
                (SOURCE_PATH, SOURCE_KIND, patch_sha, len(rows)),
            )
            source_import_id = int(cur.lastrowid)

        inserted = 0
        identical = 0
        for row in rows:
            player = row["player"]
            price_hundredths = int(round(float(row["price_m"]) * 100))
            player_row = conn.execute(
                "SELECT player_id FROM players WHERE canonical_name = ?",
                (player,),
            ).fetchone()
            if not player_row:
                raise SystemExit(f"Unresolved player: {player}")
            player_id = int(player_row[0])

            existing = conn.execute(
                """
                SELECT price_hundredths_m
                FROM fantasy_player_prices
                WHERE player_id = ? AND effective_matchday_id = ?
                """,
                (player_id, md1_id),
            ).fetchone()
            if existing:
                if int(existing[0]) != price_hundredths:
                    raise SystemExit(
                        f"Refusing conflicting MD1 price for {player}: "
                        f"existing={existing[0] / 100:.2f}, proposed={price_hundredths / 100:.2f}"
                    )
                identical += 1
                continue

            conn.execute(
                """
                INSERT INTO fantasy_player_prices
                    (player_id, effective_matchday_id, price_hundredths_m, observed_after_matchday_id, source_import_id)
                VALUES (?, ?, ?, NULL, ?)
                """,
                (player_id, md1_id, price_hundredths, source_import_id),
            )
            inserted += 1

        total = conn.execute(
            "SELECT COUNT(*) FROM fantasy_player_prices WHERE effective_matchday_id = ?",
            (md1_id,),
        ).fetchone()[0]
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        if total != EXPECTED_TOTAL:
            raise SystemExit(f"Expected {EXPECTED_TOTAL} MD1 prices after merge, found {total}")
        if fk:
            raise SystemExit(f"Foreign-key violations: {fk}")
        conn.commit()

    print(f"MD1 opening-price publication complete: inserted={inserted}, identical={identical}, total={total}")


if __name__ == "__main__":
    main()
