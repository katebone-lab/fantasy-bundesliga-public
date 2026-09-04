from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from data_repository import FantasyRepository


PUBLIC_TEAM_ROOT = Path(__file__).resolve().parents[1] / "data" / "public_team"
POSITION_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FOR": 3}


def _latest_team_record() -> dict | None:
    available = sorted(PUBLIC_TEAM_ROOT.glob("*_md*.json"))
    if not available:
        return None
    records = [json.loads(path.read_text(encoding="utf-8")) for path in available]
    records.sort(key=lambda r: (int(r["season"]), int(r["matchday"])), reverse=True)
    return records[0]


def _base_team(repository: FantasyRepository, record: dict) -> pd.DataFrame:
    team = pd.DataFrame(record.get("players", [])).copy()
    if team.empty:
        return team
    season = int(record["season"])
    matchday = int(record["matchday"])
    prices = repository.get_effective_prices(season, matchday)[["player", "price_m"]].drop_duplicates("player")
    team = team.merge(prices, on="player", how="left")
    team["price_m"] = pd.to_numeric(team["price_m"], errors="coerce").combine_first(
        pd.to_numeric(team["last_squad_valuation_m"], errors="coerce")
    )
    team["position_order"] = team["position"].map(POSITION_ORDER).fillna(99)
    return team


def _apply_plan(team: pd.DataFrame, plan: list[dict]) -> pd.DataFrame:
    working = team.copy()
    for move in plan:
        mask = working["player"] == move["out"]
        if not mask.any():
            continue
        idx = working.index[mask][0]
        working.loc[idx, ["player", "club", "position", "price_m"]] = [
            move["in"], move["club"], move["position"], move["in_price_m"]
        ]
    return working


def _cash_after_plan(starting_cash: float, plan: list[dict]) -> float:
    return round(starting_cash + sum(float(m["out_price_m"]) - float(m["in_price_m"]) for m in plan), 2)


def render_transfer_centre_tab(repository: FantasyRepository) -> None:
    record = _latest_team_record()
    if record is None:
        st.info("No public team snapshot is available yet.")
        return

    season = int(record["season"])
    matchday = int(record["matchday"])
    starting_cash = float(record.get("cash_m", 0.0))
    base_team = _base_team(repository, record)
    candidates = repository.get_planning_players(season, matchday).copy()
    if candidates.empty or base_team.empty:
        st.info("Transfer planning data is not available yet.")
        return

    candidates["price_m"] = pd.to_numeric(candidates["price_m"], errors="coerce")
    state_key = f"transfer_sandbox_{season}_{matchday}"
    if state_key not in st.session_state:
        st.session_state[state_key] = []
    plan: list[dict] = st.session_state[state_key]

    current_team = _apply_plan(base_team, plan)
    current_cash = _cash_after_plan(starting_cash, plan)

    st.subheader(f"Transfer Centre · Matchday {matchday}")
    st.caption("Planning sandbox only. Moves here do not change the saved squad or the official Fantasy Bundesliga team.")

    m1, m2, m3 = st.columns(3)
    m1.metric("Starting bank", f"€{starting_cash:.2f}m")
    m2.metric("Planned transfers", len(plan))
    m3.metric("Bank after plan", f"€{current_cash:.2f}m")

    if plan:
        summary = pd.DataFrame(plan)
        summary["cash_change_m"] = summary["out_price_m"] - summary["in_price_m"]
        st.dataframe(
            summary[["out", "in", "cash_change_m"]].rename(
                columns={"out": "Out", "in": "In", "cash_change_m": "Cash released (+) / spent (-) €m"}
            ),
            hide_index=True,
            width="stretch",
            column_config={"Cash released (+) / spent (-) €m": st.column_config.NumberColumn(format="%+.2f")},
        )
        c1, c2 = st.columns(2)
        if c1.button("Undo last transfer", use_container_width=True):
            st.session_state[state_key] = plan[:-1]
            st.rerun()
        if c2.button("Reset plan", use_container_width=True):
            st.session_state[state_key] = []
            st.rerun()

    st.markdown("#### Add a transfer")
    outgoing_names = current_team.sort_values(["position_order", "player"])["player"].tolist()
    outgoing_name = st.selectbox("Player out", outgoing_names, key=f"sandbox_out_{season}_{matchday}")
    outgoing = current_team.loc[current_team["player"] == outgoing_name].iloc[0]
    available_budget = round(current_cash + float(outgoing["price_m"]), 2)

    current_names = set(current_team["player"].astype(str))
    remaining_counts = current_team.loc[current_team["player"] != outgoing_name, "club"].value_counts().to_dict()
    market = candidates[
        (candidates["fantasy_position"] == outgoing["position"])
        & (~candidates["player"].isin(current_names))
        & candidates["price_m"].notna()
        & (candidates["price_m"] <= available_budget)
    ].copy()
    market = market[market["club"].map(lambda club: remaining_counts.get(club, 0) < 3)]

    if market.empty:
        st.warning("No affordable valid same-position replacements are available for this player.")
        return

    sort_columns = [c for c in ["next_md_score", "lineup_likelihood", "fixture_ease", "player"] if c in market.columns]
    if sort_columns:
        ascending = [False] * (len(sort_columns) - 1) + [True] if sort_columns[-1] == "player" else [False] * len(sort_columns)
        market = market.sort_values(sort_columns, ascending=ascending, na_position="last")

    option_rows = market.reset_index(drop=True)
    candidate_idx = st.selectbox(
        "Player in",
        options=list(option_rows.index),
        format_func=lambda i: f"{option_rows.loc[i, 'player']} · {option_rows.loc[i, 'club']} · €{option_rows.loc[i, 'price_m']:.2f}m",
        key=f"sandbox_in_{season}_{matchday}_{outgoing_name}",
    )
    incoming = option_rows.loc[candidate_idx]
    new_cash = round(current_cash + float(outgoing["price_m"]) - float(incoming["price_m"]), 2)

    p1, p2, p3 = st.columns(3)
    p1.metric("Outgoing value", f"€{float(outgoing['price_m']):.2f}m")
    p2.metric("Incoming price", f"€{float(incoming['price_m']):.2f}m")
    p3.metric("Bank after this move", f"€{new_cash:.2f}m")

    if st.button("Add to transfer plan", type="primary", use_container_width=True):
        st.session_state[state_key] = plan + [{
            "out": str(outgoing["player"]),
            "in": str(incoming["player"]),
            "club": str(incoming["club"]),
            "position": str(outgoing["position"]),
            "out_price_m": float(outgoing["price_m"]),
            "in_price_m": float(incoming["price_m"]),
        }]
        st.rerun()

    st.markdown("#### Planned squad")
    squad_view = current_team.sort_values(["position_order", "player"])[["player", "club", "position", "slot", "price_m"]].rename(
        columns={"player": "Player", "club": "Club", "position": "Position", "slot": "Slot", "price_m": "Price (€m)"}
    )
    st.dataframe(
        squad_view,
        hide_index=True,
        width="stretch",
        column_config={"Price (€m)": st.column_config.NumberColumn(format="%.2f")},
    )
