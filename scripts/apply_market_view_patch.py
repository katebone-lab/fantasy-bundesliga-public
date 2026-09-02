from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"Expected exactly one {label} block, found {text.count(old)}")
    return text.replace(old, new, 1)


def patch_fixture_model() -> None:
    path = ROOT / "fixture_model.py"
    text = path.read_text(encoding="utf-8")

    old = '''    strength["overall_strength"] = np.sqrt(\n        strength["attack_strength"] * strength["defence_strength"]\n    )\n    return strength[\n'''
    new = '''    strength["overall_strength"] = np.sqrt(\n        strength["attack_strength"] * strength["defence_strength"]\n    )\n    strength["attack_strength_pct"] = strength["attack_strength"].rank(pct=True) * 100\n    strength["defence_strength_pct"] = strength["defence_strength"].rank(pct=True) * 100\n    return strength[\n'''
    text = replace_once(text, old, new, "team strength percentile")

    old = '''            "attack_strength",\n            "defence_strength",\n            "overall_strength",\n'''
    new = '''            "attack_strength",\n            "defence_strength",\n            "overall_strength",\n            "attack_strength_pct",\n            "defence_strength_pct",\n'''
    text = replace_once(text, old, new, "team strength return columns")

    old = '''    fixtures = build_fixture_ratings(matchday)\n    out = out.merge(fixtures, on="club", how="left", validate="many_to_one")\n\n    out["fixture_ease"] = out.apply(\n'''
    new = '''    fixtures = build_fixture_ratings(matchday)\n    out = out.merge(fixtures, on="club", how="left", validate="many_to_one")\n    strengths = build_team_strengths()[\n        ["club", "attack_strength_pct", "defence_strength_pct"]\n    ]\n    out = out.merge(strengths, on="club", how="left", validate="many_to_one")\n\n    out["fixture_ease"] = out.apply(\n'''
    text = replace_once(text, old, new, "strength merge")

    old = '''    out["planning_score"] = (\n        0.30 * out["performance_component"]\n        + 0.15 * out["value_component"]\n        + 0.30 * out["fixture_ease"].fillna(50.0)\n        + 0.25 * out["lineup_likelihood"].fillna(20.0)\n    )\n    return out\n'''
    new = '''    out["planning_score"] = (\n        0.30 * out["performance_component"]\n        + 0.15 * out["value_component"]\n        + 0.30 * out["fixture_ease"].fillna(50.0)\n        + 0.25 * out["lineup_likelihood"].fillna(20.0)\n    )\n\n    def _team_component(row: pd.Series) -> float:\n        position = str(row.get("fantasy_position"))\n        attack = row.get("attack_strength_pct")\n        defence = row.get("defence_strength_pct")\n        attack = 50.0 if pd.isna(attack) else float(attack)\n        defence = 50.0 if pd.isna(defence) else float(defence)\n        if position in {"GK", "DEF"}:\n            return defence\n        if position == "FOR":\n            return attack\n        return 0.55 * attack + 0.45 * defence\n\n    out["team_strength_component"] = out.apply(_team_component, axis=1)\n    # A deliberately forward-looking score for browsing the whole positional market.\n    # Fixture and likely role dominate; MD1 performance is useful evidence but cannot\n    # bury new signings or players who simply did not feature in the opening match.\n    out["next_md_score"] = (\n        0.35 * out["fixture_ease"].fillna(50.0)\n        + 0.30 * out["lineup_likelihood"].fillna(20.0)\n        + 0.20 * out["team_strength_component"].fillna(50.0)\n        + 0.10 * out["performance_component"]\n        + 0.05 * out["value_component"]\n    )\n    return out\n'''
    text = replace_once(text, old, new, "next matchday score")
    path.write_text(text, encoding="utf-8")


def patch_team_ui() -> None:
    path = ROOT / "ui" / "public_team_tab.py"
    text = path.read_text(encoding="utf-8")

    old = '''def _candidate_label(row: pd.Series) -> str:\n    points = "—" if pd.isna(row.get("matchday_points")) else f"{row['matchday_points']:.0f} pts"\n    minutes = "—" if pd.isna(row.get("minutes")) else f"{row['minutes']:.0f} min"\n    fixture = row.get("fixture_label", "Unknown")\n    price_basis = row.get("price_source", "Last known price")\n    return f"{row['player']} · {row['club']} · £{row['price_m']:.2f}m · {price_basis} · {points} · {minutes} · {fixture}"\n'''
    new = '''def _candidate_label(row: pd.Series) -> str:\n    points = "—" if pd.isna(row.get("matchday_points")) else f"{row['matchday_points']:.0f} pts"\n    minutes = "—" if pd.isna(row.get("minutes")) else f"{row['minutes']:.0f} min"\n    fixture = row.get("fixture_label", "Unknown")\n    price_basis = row.get("price_source", "Last known price")\n    affordability = row.get("affordability", "")\n    score = row.get("next_md_score")\n    score_text = "—" if pd.isna(score) else f"MD2 {score:.0f}/100"\n    return f"{row['player']} · {row['club']} · £{row['price_m']:.2f}m · {affordability} · {score_text} · {price_basis} · {points} · {minutes} · {fixture}"\n'''
    text = replace_once(text, old, new, "candidate label")

    old = '''    row3 = st.columns(4)\n'''
    new = '''    row3 = st.columns(5)\n'''
    text = replace_once(text, old, new, "candidate detail columns")

    old = '''    row3[3].metric(\n        "MD2 planning score",\n        "—" if pd.isna(candidate.get("planning_score")) else f"{candidate['planning_score']:.0f}/100",\n    )\n\n    st.caption(\n'''
    new = '''    row3[3].metric(\n        "Best placed for MD2",\n        "—" if pd.isna(candidate.get("next_md_score")) else f"{candidate['next_md_score']:.0f}/100",\n    )\n    row3[4].metric(\n        "Planning score",\n        "—" if pd.isna(candidate.get("planning_score")) else f"{candidate['planning_score']:.0f}/100",\n    )\n\n    st.caption(\n'''
    text = replace_once(text, old, new, "candidate next-md detail")

    old = '''        "The planning score combines MD1 performance (30%), value (15%), fixture (30%) and lineup likelihood (25%). Each component remains visible so the score is not a black box."\n'''
    new = '''        "Best placed for MD2 is deliberately more forward-looking: fixture 35%, lineup likelihood 30%, team strength 20%, MD1 performance 10% and value 5%. "\n        "The broader planning score remains available separately and combines MD1 performance (30%), value (15%), fixture (30%) and lineup likelihood (25%)."\n'''
    text = replace_once(text, old, new, "score explanation")

    old = '''    valid = candidates[\n        (candidates["fantasy_position"] == outgoing["position"])\n        & (~candidates["player"].isin(squad_names))\n        & (candidates["price_m"].notna())\n        & (candidates["price_m"] <= available_budget)\n    ].copy()\n    valid = valid[\n        valid["club"].map(lambda club: remaining_club_counts.get(club, 0) < 3)\n    ].copy()\n\n    if valid.empty:\n        st.warning("No valid replacements are available within this budget.")\n        return\n\n    valid["transfer_cost_m"] = valid["price_m"] - outgoing_price\n    valid["cash_impact"] = valid["transfer_cost_m"].map(_cash_impact_label)\n    valid["cash_after_transfer_m"] = cash_m - valid["transfer_cost_m"]\n    valid["points_change"] = valid["matchday_points"] - pd.to_numeric(\n        outgoing["matchday_points"], errors="coerce"\n    )\n'''
    new = '''    market = candidates[\n        (candidates["fantasy_position"] == outgoing["position"])\n        & (~candidates["player"].isin(squad_names))\n        & (candidates["price_m"].notna())\n    ].copy()\n    market = market[\n        market["club"].map(lambda club: remaining_club_counts.get(club, 0) < 3)\n    ].copy()\n\n    if market.empty:\n        st.warning("No same-position candidates are available.")\n        return\n\n    market["transfer_cost_m"] = market["price_m"] - outgoing_price\n    market["cash_impact"] = market["transfer_cost_m"].map(_cash_impact_label)\n    market["cash_after_transfer_m"] = cash_m - market["transfer_cost_m"]\n    market["over_budget_m"] = market["price_m"] - available_budget\n    market["affordability"] = market["over_budget_m"].map(\n        lambda value: "Affordable" if value <= 0 else f"£{value:.2f}m over budget"\n    )\n    market["points_change"] = market["matchday_points"] - pd.to_numeric(\n        outgoing["matchday_points"], errors="coerce"\n    )\n\n    pool_mode = st.radio(\n        "Candidate pool",\n        options=["Best placed for MD2", "Affordable only"],\n        horizontal=True,\n        key=f"public_transfer_pool_{season}_{matchday}_{outgoing_name}",\n        help="Browse the whole same-position market by default, or restrict the list to players affordable from this one sale plus current cash.",\n    )\n    valid = (\n        market.copy()\n        if pool_mode == "Best placed for MD2"\n        else market[market["price_m"] <= available_budget].copy()\n    )\n    if valid.empty:\n        st.warning("No affordable replacements are available. Switch to Best placed for MD2 to browse the full positional market.")\n        return\n'''
    text = replace_once(text, old, new, "candidate pool")

    old = '''    candidate_rows = valid.sort_values(["player", "club"]).reset_index(drop=True)\n'''
    new = '''    candidate_rows = valid.sort_values(\n        ["next_md_score", "lineup_likelihood", "fixture_ease", "player"],\n        ascending=[False, False, False, True],\n        na_position="last",\n    ).reset_index(drop=True)\n'''
    text = replace_once(text, old, new, "candidate ordering")

    old = '''        options=[\n            "MD2 planning score",\n            "Fixture ease",\n'''
    new = '''        options=[\n            "Best placed for MD2",\n            "MD2 planning score",\n            "Fixture ease",\n'''
    text = replace_once(text, old, new, "rank options")

    old = '''    rank_column = {\n        "MD2 planning score": "planning_score",\n'''
    new = '''    rank_column = {\n        "Best placed for MD2": "next_md_score",\n        "MD2 planning score": "planning_score",\n'''
    text = replace_once(text, old, new, "rank mapping")

    old = '''        "planning_score",\n        "price_m",\n        "cash_impact",\n'''
    new = '''        "next_md_score",\n        "team_strength_component",\n        "planning_score",\n        "price_m",\n        "affordability",\n        "cash_impact",\n'''
    text = replace_once(text, old, new, "view columns")

    old = '''            "planning_score": "MD2 planning score",\n            "price_m": "Planning price (£m)",\n'''
    # Current file may still call the price column MD2 price; accept either wording below.
    if old not in text:
        old = '''            "planning_score": "MD2 planning score",\n            "price_m": "MD2 price (£m)",\n'''
    new = '''            "next_md_score": "Best placed for MD2",\n            "team_strength_component": "Team strength",\n            "planning_score": "MD2 planning score",\n            "price_m": "Planning price (£m)",\n            "affordability": "Affordability",\n'''
    text = replace_once(text, old, new, "view rename")

    old = '''            "MD2 planning score": st.column_config.NumberColumn(format="%.0f"),\n'''
    new = '''            "Best placed for MD2": st.column_config.NumberColumn(format="%.0f"),\n            "Team strength": st.column_config.NumberColumn(format="%.0f"),\n            "MD2 planning score": st.column_config.NumberColumn(format="%.0f"),\n'''
    text = replace_once(text, old, new, "column config")

    old = '''        f"{len(valid)} valid replacements in the full pool; {len(shortlist)} match the optional filters; showing the top {min(12, len(shortlist))}. "\n'''
    new = '''        f"{len(market)} same-position players in the full market; {len(valid)} in the selected pool; {len(shortlist)} match the optional filters; showing the top {min(12, len(shortlist))}. "\n        "Best placed for MD2 is a forward-looking ranking: fixture 35%, lineup likelihood 30%, team strength 20%, MD1 performance 10% and value 5%. "\n'''
    text = replace_once(text, old, new, "shortlist caption")

    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_fixture_model()
    patch_team_ui()
    print("market_view_patch=ok")


if __name__ == "__main__":
    main()
