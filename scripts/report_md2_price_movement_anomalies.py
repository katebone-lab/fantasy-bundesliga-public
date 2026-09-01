from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "fantasy_bundesliga.sqlite"
OUT = ROOT / "data" / "md2_price_movement_anomaly_report.csv"

ABS_WARN_M = 0.50
PCT_WARN = 10.0


def main() -> None:
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT player,
                   LAG(price_m) OVER (PARTITION BY player_id, season ORDER BY effective_matchday) AS md1_price_m,
                   price_m AS md2_price_m,
                   price_movement_hundredths_m/100.0 AS movement_m
            FROM vw_fantasy_price_history
            WHERE season=2026
            """
        ).fetchall()

    report = []
    for r in rows:
        if r["md1_price_m"] is None:
            continue
        pct = (r["movement_m"] / r["md1_price_m"] * 100.0) if r["md1_price_m"] else None
        flagged = abs(r["movement_m"]) >= ABS_WARN_M or (pct is not None and abs(pct) >= PCT_WARN)
        report.append({
            "player": r["player"],
            "md1_price_m": f"{r['md1_price_m']:.2f}",
            "md2_price_m": f"{r['md2_price_m']:.2f}",
            "movement_m": f"{r['movement_m']:+.2f}",
            "movement_pct": f"{pct:+.2f}" if pct is not None else "",
            "flagged": "yes" if flagged else "no",
        })

    report.sort(key=lambda x: abs(float(x["movement_m"])), reverse=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["player","md1_price_m","md2_price_m","movement_m","movement_pct","flagged"])
        w.writeheader()
        w.writerows(report)

    flagged_rows = [r for r in report if r["flagged"] == "yes"]
    print(f"movement_rows={len(report)} flagged={len(flagged_rows)}")
    for r in flagged_rows[:30]:
        print(f"{r['player']}: {r['md1_price_m']} -> {r['md2_price_m']} ({r['movement_m']}m, {r['movement_pct']}%)")


if __name__ == "__main__":
    main()
