from __future__ import annotations

from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "ui" / "public_team_tab.py"


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"Expected exactly one match, found {text.count(old)} for:\n{old[:120]}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''    price_history = repository.get_effective_prices(season, matchday).copy()\n    if not price_history.empty and {"player", "price_movement_m"}.issubset(\n        price_history.columns\n    ):\n        price_history = price_history[["player", "price_movement_m"]].drop_duplicates(\n            subset=["player"], keep="first"\n        )\n        planning = planning.merge(price_history, on="player", how="left")\n    else:\n        planning["price_movement_m"] = pd.NA\n''',
        '''    # Keep exact-matchday captured prices separate from the planning view's\n    # effective/last-known price. This lets new signings and zero-pointers remain\n    # visible without labelling an older price as a captured MD2 observation.\n    price_history = repository.get_effective_prices(season, matchday).copy()\n    if not price_history.empty and {"player", "price_m", "price_movement_m"}.issubset(\n        price_history.columns\n    ):\n        price_history = price_history[["player", "price_m", "price_movement_m"]].drop_duplicates(\n            subset=["player"], keep="first"\n        ).rename(columns={"price_m": "captured_matchday_price_m"})\n        planning = planning.merge(price_history, on="player", how="left")\n        planning["price_source"] = planning["captured_matchday_price_m"].notna().map(\n            {True: f"Captured MD{matchday} price", False: "Last known price"}\n        )\n    else:\n        planning["captured_matchday_price_m"] = pd.NA\n        planning["price_movement_m"] = pd.NA\n        planning["price_source"] = "Last known price"\n''',
    )

    text = replace_once(
        text,
        '''    return f"{row['player']} · {row['club']} · £{row['price_m']:.2f}m · {points} · {minutes} · {fixture}"\n''',
        '''    price_basis = row.get("price_source", "Last known price")\n    return f"{row['player']} · {row['club']} · £{row['price_m']:.2f}m · {price_basis} · {points} · {minutes} · {fixture}"\n''',
    )

    text = replace_once(
        text,
        '''def _render_candidate_detail(candidate: pd.Series) -> None:\n    st.markdown("##### Candidate detail")\n    row1 = st.columns(5)\n    row1[0].metric("MD2 price", f"£{candidate['price_m']:.2f}m")\n''',
        '''def _fixture_badge_color(ease: float | int | None) -> str:\n    if ease is None or pd.isna(ease):\n        return "gray"\n    ease = float(ease)\n    if ease >= 60:\n        return "green"\n    if ease >= 40:\n        return "gray"\n    if ease >= 20:\n        return "orange"\n    return "red"\n\n\ndef _lineup_badge_color(likelihood: float | int | None) -> str:\n    if likelihood is None or pd.isna(likelihood):\n        return "gray"\n    likelihood = float(likelihood)\n    if likelihood >= 80:\n        return "green"\n    if likelihood >= 60:\n        return "blue"\n    if likelihood >= 40:\n        return "orange"\n    return "red"\n\n\ndef _render_candidate_detail(candidate: pd.Series) -> None:\n    st.markdown("##### Candidate detail")\n    row1 = st.columns(5)\n    price_source = candidate.get("price_source", "Last known price")\n    price_heading = "MD2 price" if str(price_source).startswith("Captured MD") else "Last known price"\n    row1[0].metric(price_heading, f"£{candidate['price_m']:.2f}m")\n    row1[0].caption(str(price_source))\n''',
    )

    text = replace_once(
        text,
        '''    row3[1].metric(\n        "Fixture ease",\n        "—" if pd.isna(candidate.get("fixture_ease")) else f"{candidate['fixture_ease']:.0f}/100",\n        candidate.get("fixture_label") if pd.notna(candidate.get("fixture_ease")) else None,\n    )\n    row3[2].metric(\n        "Lineup likelihood",\n        "—" if pd.isna(candidate.get("lineup_likelihood")) else f"{candidate['lineup_likelihood']:.0f}%",\n        candidate.get("lineup_label") if pd.notna(candidate.get("lineup_likelihood")) else None,\n    )\n''',
        '''    row3[1].metric(\n        "Fixture ease",\n        "—" if pd.isna(candidate.get("fixture_ease")) else f"{candidate['fixture_ease']:.0f}/100",\n    )\n    if pd.notna(candidate.get("fixture_ease")):\n        row3[1].badge(\n            str(candidate.get("fixture_label", "Unknown")),\n            color=_fixture_badge_color(candidate.get("fixture_ease")),\n        )\n    row3[2].metric(\n        "Lineup likelihood",\n        "—" if pd.isna(candidate.get("lineup_likelihood")) else f"{candidate['lineup_likelihood']:.0f}%",\n    )\n    if pd.notna(candidate.get("lineup_likelihood")):\n        row3[2].badge(\n            str(candidate.get("lineup_label", "Unknown")),\n            color=_lineup_badge_color(candidate.get("lineup_likelihood")),\n        )\n''',
    )

    text = replace_once(
        text,
        '''        "planning_score",\n        "price_m",\n        "cash_impact",\n''',
        '''        "planning_score",\n        "price_m",\n        "price_source",\n        "cash_impact",\n''',
    )

    text = replace_once(
        text,
        '''            "planning_score": "MD2 planning score",\n            "price_m": "MD2 price (£m)",\n            "cash_impact": "Cash impact",\n''',
        '''            "planning_score": "MD2 planning score",\n            "price_m": "Planning price (£m)",\n            "price_source": "Price basis",\n            "cash_impact": "Cash impact",\n''',
    )

    text = replace_once(
        text,
        '''            "MD2 price (£m)": st.column_config.NumberColumn(format="%.2f"),\n''',
        '''            "Planning price (£m)": st.column_config.NumberColumn(format="%.2f"),\n''',
    )

    text = replace_once(
        text,
        '''        "The lineup percentage is an MD1-role prior, not a live injury/probable-lineup forecast. Club and position still use the latest published historical context where explicit Matchday 2 planning context has not yet been captured."\n''',
        '''        "The lineup percentage is an MD1-role prior, not a live injury/probable-lineup forecast. Price basis distinguishes an exact captured MD2 price from a last-known earlier price, so zero-pointers and new arrivals can remain in the candidate pool without overstating price certainty. Club and position still use the latest published historical context where explicit Matchday 2 planning context has not yet been captured."\n''',
    )

    PATH.write_text(text, encoding="utf-8")
    print("price_provenance_ui_patch=ok")


if __name__ == "__main__":
    main()
