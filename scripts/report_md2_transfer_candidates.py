from __future__ import annotations

import csv, json, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data' / 'fantasy_bundesliga.sqlite'
TEAM = ROOT / 'data' / 'public_team' / '2026_md02.json'
OUT = ROOT / 'data' / 'md2_transfer_candidate_report.csv'


def main():
    team = json.loads(TEAM.read_text(encoding='utf-8'))
    cash = float(team['cash_m'])
    squad = {p['player']: p for p in team['players']}

    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('''
            SELECT v.player_id,
                   v.player,
                   v.fantasy_position AS position,
                   v.matchday_points AS md1_points,
                   pr1.price_hundredths_m/100.0 AS md1_price_m,
                   pr2.price_hundredths_m/100.0 AS md2_price_m
            FROM vw_fantasy_player_matchday v
            LEFT JOIN fantasy_player_prices pr1 ON pr1.player_id=v.player_id AND pr1.effective_matchday_id=(
                SELECT md1.matchday_id FROM matchdays md1 JOIN seasons s1 ON s1.season_id=md1.season_id
                WHERE s1.start_year=2026 AND md1.matchday_number=1)
            LEFT JOIN fantasy_player_prices pr2 ON pr2.player_id=v.player_id AND pr2.effective_matchday_id=(
                SELECT md2.matchday_id FROM matchdays md2 JOIN seasons s2 ON s2.season_id=md2.season_id
                WHERE s2.start_year=2026 AND md2.matchday_number=2)
            WHERE v.season=2026 AND v.matchday=1
        ''').fetchall()

    by_name = {r['player']: r for r in rows}
    output = []
    for outgoing_name, sp in squad.items():
        pos = sp['position']
        current = by_name.get(outgoing_name)
        outgoing_md2 = current['md2_price_m'] if current and current['md2_price_m'] is not None else float(sp['last_squad_valuation_m'])
        max_price = outgoing_md2 + cash
        outgoing_pts = current['md1_points'] if current else None
        for r in rows:
            if r['player'] in squad or r['position'] != pos or r['md2_price_m'] is None:
                continue
            if r['md2_price_m'] > max_price:
                continue
            ppm = (r['md1_points']/r['md2_price_m']) if r['md1_points'] is not None and r['md2_price_m'] else None
            output.append({
                'outgoing': outgoing_name,
                'outgoing_slot': sp['slot'],
                'position': pos,
                'outgoing_md1_points': outgoing_pts,
                'outgoing_md2_price_m': f'{outgoing_md2:.2f}',
                'cash_before_m': f'{cash:.2f}',
                'max_replacement_price_m': f'{max_price:.2f}',
                'candidate': r['player'],
                'candidate_md1_points': r['md1_points'],
                'candidate_md1_price_m': f"{r['md1_price_m']:.2f}" if r['md1_price_m'] is not None else '',
                'candidate_md2_price_m': f"{r['md2_price_m']:.2f}",
                'candidate_movement_m': f"{(r['md2_price_m']-r['md1_price_m']):+.2f}" if r['md1_price_m'] is not None else '',
                'candidate_points_per_md2_m': f'{ppm:.2f}' if ppm is not None else '',
                'cash_after_m': f'{max_price-r["md2_price_m"]:.2f}',
                'points_gain_vs_outgoing': (r['md1_points']-outgoing_pts) if r['md1_points'] is not None and outgoing_pts is not None else '',
            })

    output.sort(key=lambda x: (x['outgoing'], -(x['candidate_md1_points'] if x['candidate_md1_points'] is not None else -9999), -float(x['candidate_points_per_md2_m'] or 0)))
    fields = list(output[0]) if output else []
    with OUT.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(output)
    print(f'candidate_rows={len(output)}')
    for name in squad:
        subset = [r for r in output if r['outgoing'] == name][:5]
        if subset:
            print('\n' + name)
            for r in subset:
                print(f"  {r['candidate']}: pts={r['candidate_md1_points']} price={r['candidate_md2_price_m']} ppm={r['candidate_points_per_md2_m']} cash_after={r['cash_after_m']} gain={r['points_gain_vs_outgoing']}")


if __name__ == '__main__':
    main()
