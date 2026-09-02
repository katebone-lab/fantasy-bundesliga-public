from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Expected one {label} block, found {count}")
    return text.replace(old, new, 1)


def patch_fixture_model() -> None:
    path = ROOT / "fixture_model.py"
    text = path.read_text(encoding="utf-8")
    text = once(text,
'''    strength["overall_strength"] = np.sqrt(
        strength["attack_strength"] * strength["defence_strength"]
    )
    return strength[
''',
'''    strength["overall_strength"] = np.sqrt(
        strength["attack_strength"] * strength["defence_strength"]
    )
    strength["attack_strength_pct"] = strength["attack_strength"].rank(pct=True) * 100
    strength["defence_strength_pct"] = strength["defence_strength"].rank(pct=True) * 100
    return strength[
''', "strength percentiles")
    text = once(text,
'''            "attack_strength",
            "defence_strength",
            "overall_strength",
''',
'''            "attack_strength",
            "defence_strength",
            "overall_strength",
            "attack_strength_pct",
            "defence_strength_pct",
''', "strength columns")
    text = once(text,
'''    fixtures = build_fixture_ratings(matchday)
    out = out.merge(fixtures, on="club", how="left", validate="many_to_one")

    out["fixture_ease"] = out.apply(
''',
'''    fixtures = build_fixture_ratings(matchday)
    out = out.merge(fixtures, on="club", how="left", validate="many_to_one")
    strengths = build_team_strengths()[
        ["club", "attack_strength_pct", "defence_strength_pct"]
    ]
    out = out.merge(strengths, on="club", how="left", validate="many_to_one")

    out["fixture_ease"] = out.apply(
''', "strength merge")
    text = once(text,
'''    out["planning_score"] = (
        0.30 * out["performance_component"]
        + 0.15 * out["value_component"]
        + 0.30 * out["fixture_ease"].fillna(50.0)
        + 0.25 * out["lineup_likelihood"].fillna(20.0)
    )
    return out
''',
'''    out["planning_score"] = (
        0.30 * out["performance_component"]
        + 0.15 * out["value_component"]
        + 0.30 * out["fixture_ease"].fillna(50.0)
        + 0.25 * out["lineup_likelihood"].fillna(20.0)
    )

    def _team_component(row: pd.Series) -> float:
        position = str(row.get("fantasy_position"))
        attack = row.get("attack_strength_pct")
        defence = row.get("defence_strength_pct")
        attack = 50.0 if pd.isna(attack) else float(attack)
        defence = 50.0 if pd.isna(defence) else float(defence)
        if position in {"GK", "DEF"}:
            return defence
        if position == "FOR":
            return attack
        return 0.55 * attack + 0.45 * defence

    out["team_strength_component"] = out.apply(_team_component, axis=1)
    out["next_md_score"] = (
        0.35 * out["fixture_ease"].fillna(50.0)
        + 0.30 * out["lineup_likelihood"].fillna(20.0)
        + 0.20 * out["team_strength_component"].fillna(50.0)
        + 0.10 * out["performance_component"]
        + 0.05 * out["value_component"]
    )
    return out
''', "next matchday score")
    path.write_text(text, encoding="utf-8")


def patch_ui() -> None:
    path = ROOT / "ui" / "public_team_tab.py"
    text = path.read_text(encoding="utf-8")
    text = once(text,
'''def _candidate_label(row: pd.Series) -> str:
    points = "—" if pd.isna(row.get("matchday_points")) else f"{row['matchday_points']:.0f} pts"
    minutes = "—" if pd.isna(row.get("minutes")) else f"{row['minutes']:.0f} min"
    fixture = row.get("fixture_label", "Unknown")
    price_basis = row.get("price_source", "Last known price")
    return f"{row['player']} · {row['club']} · £{row['price_m']:.2f}m · {price_basis} · {points} · {minutes} · {fixture}"
''',
'''def _candidate_label(row: pd.Series) -> str:
    points = "—" if pd.isna(row.get("matchday_points")) else f"{row['matchday_points']:.0f} pts"
    minutes = "—" if pd.isna(row.get("minutes")) else f"{row['minutes']:.0f} min"
    fixture = row.get("fixture_label", "Unknown")
    price_basis = row.get("price_source", "Last known price")
    affordability = row.get("affordability", "")
    score = row.get("next_md_score")
    score_text = "—" if pd.isna(score) else f"MD2 {score:.0f}/100"
    return f"{row['player']} · {row['club']} · £{row['price_m']:.2f}m · {affordability} · {score_text} · {price_basis} · {points} · {minutes} · {fixture}"
''', "candidate label")
    text = once(text, '    row3 = st.columns(4)\n', '    row3 = st.columns(5)\n', "detail columns")
    text = once(text,
'''    row3[3].metric(
        "MD2 planning score",
        "—" if pd.isna(candidate.get("planning_score")) else f"{candidate['planning_score']:.0f}/100",
    )

    st.caption(
''',
'''    row3[3].metric(
        "Best placed for MD2",
        "—" if pd.isna(candidate.get("next_md_score")) else f"{candidate['next_md_score']:.0f}/100",
    )
    row3[4].metric(
        "Planning score",
        "—" if pd.isna(candidate.get("planning_score")) else f"{candidate['planning_score']:.0f}/100",
    )

    st.caption(
''', "detail score")
    text = once(text,
'''        "The planning score combines MD1 performance (30%), value (15%), fixture (30%) and lineup likelihood (25%). Each component remains visible so the score is not a black box."
''',
'''        "Best placed for MD2 is deliberately more forward-looking: fixture 35%, lineup likelihood 30%, team strength 20%, MD1 performance 10% and value 5%. "
        "The broader planning score remains available separately and combines MD1 performance (30%), value (15%), fixture (30%) and lineup likelihood (25%)."
''', "detail caption")
    text = once(text,
'''    valid = candidates[
        (candidates["fantasy_position"] == outgoing["position"])
        & (~candidates["player"].isin(squad_names))
        & (candidates["price_m"].notna())
        & (candidates["price_m"] <= available_budget)
    ].copy()
    valid = valid[
        valid["club"].map(lambda club: remaining_club_counts.get(club, 0) < 3)
    ].copy()

    if valid.empty:
        st.warning("No valid replacements are available within this budget.")
        return

    valid["transfer_cost_m"] = valid["price_m"] - outgoing_price
    valid["cash_impact"] = valid["transfer_cost_m"].map(_cash_impact_label)
    valid["cash_after_transfer_m"] = cash_m - valid["transfer_cost_m"]
    valid["points_change"] = valid["matchday_points"] - pd.to_numeric(
        outgoing["matchday_points"], errors="coerce"
    )
''',
'''    market = candidates[
        (candidates["fantasy_position"] == outgoing["position"])
        & (~candidates["player"].isin(squad_names))
        & (candidates["price_m"].notna())
    ].copy()
    market = market[
        market["club"].map(lambda club: remaining_club_counts.get(club, 0) < 3)
    ].copy()

    if market.empty:
        st.warning("No same-position candidates are available.")
        return

    market["transfer_cost_m"] = market["price_m"] - outgoing_price
    market["cash_impact"] = market["transfer_cost_m"].map(_cash_impact_label)
    market["cash_after_transfer_m"] = cash_m - market["transfer_cost_m"]
    market["over_budget_m"] = market["price_m"] - available_budget
    market["affordability"] = market["over_budget_m"].map(
        lambda value: "Affordable" if value <= 0 else f"£{value:.2f}m over budget"
    )
    market["points_change"] = market["matchday_points"] - pd.to_numeric(
        outgoing["matchday_points"], errors="coerce"
    )

    pool_mode = st.radio(
        "Candidate pool",
        options=["Best placed for MD2", "Affordable only"],
        horizontal=True,
        key=f"public_transfer_pool_{season}_{matchday}_{outgoing_name}",
        help="Browse the whole same-position market by default, or restrict to players affordable from this sale plus current cash.",
    )
    valid = market.copy() if pool_mode == "Best placed for MD2" else market[market["price_m"] <= available_budget].copy()
    if valid.empty:
        st.warning("No affordable replacements are available. Switch to Best placed for MD2 to browse the full positional market.")
        return
''', "market pool")
    text = once(text,
'    candidate_rows = valid.sort_values(["player", "club"]).reset_index(drop=True)\n',
'''    candidate_rows = valid.sort_values(
        ["next_md_score", "lineup_likelihood", "fixture_ease", "player"],
        ascending=[False, False, False, True],
        na_position="last",
    ).reset_index(drop=True)
''', "candidate ordering")
    text = once(text,
'''        options=[
            "MD2 planning score",
            "Fixture ease",
''',
'''        options=[
            "Best placed for MD2",
            "MD2 planning score",
            "Fixture ease",
''', "rank options")
    text = once(text,
'''    rank_column = {
        "MD2 planning score": "planning_score",
''',
'''    rank_column = {
        "Best placed for MD2": "next_md_score",
        "MD2 planning score": "planning_score",
''', "rank mapping")
    text = once(text,
'''        "planning_score",
        "price_m",
        "price_source",
        "cash_impact",
''',
'''        "next_md_score",
        "team_strength_component",
        "planning_score",
        "price_m",
        "price_source",
        "affordability",
        "cash_impact",
''', "view columns")
    text = once(text,
'''            "planning_score": "MD2 planning score",
            "price_m": "Planning price (£m)",
            "price_source": "Price basis",
''',
'''            "next_md_score": "Best placed for MD2",
            "team_strength_component": "Team strength",
            "planning_score": "MD2 planning score",
            "price_m": "Planning price (£m)",
            "price_source": "Price basis",
            "affordability": "Affordability",
''', "view rename")
    text = once(text,
'''            "MD2 planning score": st.column_config.NumberColumn(format="%.0f"),
''',
'''            "Best placed for MD2": st.column_config.NumberColumn(format="%.0f"),
            "Team strength": st.column_config.NumberColumn(format="%.0f"),
            "MD2 planning score": st.column_config.NumberColumn(format="%.0f"),
''', "column config")
    text = once(text,
'''        f"{len(valid)} valid replacements in the full pool; {len(shortlist)} match the optional filters; showing the top {min(12, len(shortlist))}. "
''',
'''        f"{len(market)} same-position players in the full market; {len(valid)} in the selected pool; {len(shortlist)} match the optional filters; showing the top {min(12, len(shortlist))}. "
        "Best placed for MD2 is a forward-looking ranking: fixture 35%, lineup likelihood 30%, team strength 20%, MD1 performance 10% and value 5%. "
''', "shortlist caption")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_fixture_model()
    patch_ui()
    print("market_view_patch_v2=ok")


if __name__ == "__main__":
    main()
