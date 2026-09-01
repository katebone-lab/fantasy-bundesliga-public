from __future__ import annotations

import pandas as pd
import streamlit as st

from app_constants import AVAILABILITY_LABELS, POSITION_LABELS


def install_page_style() -> None:
    st.markdown(
        """
        <style>
          .player-hero {background:linear-gradient(120deg,#d90035,#f03855);color:white;padding:1.4rem 1.6rem;border-radius:14px 14px 4px 4px;box-shadow:0 8px 24px rgba(150,0,35,.18)}
          .player-kicker {font-size:.75rem;font-weight:800;letter-spacing:.12em;opacity:.82}
          .player-name {font-size:2rem;font-weight:850;line-height:1.08;margin:.25rem 0}
          .player-club {font-size:.95rem;font-weight:600;opacity:.92}
          .fixture-strip {display:flex;justify-content:center;align-items:center;gap:1.4rem;background:#f2f3f5;padding:.85rem 1rem;margin:.8rem 0 1rem;border-radius:4px;text-align:center}
          .fixture-strip strong {font-size:1.35rem;color:#111827}
          .stat-row {display:flex;justify-content:space-between;padding:.55rem .15rem;border-bottom:1px solid rgba(128,128,128,.18)}
        </style>
        """,
        unsafe_allow_html=True,
    )


def display_summary_metrics(
    player_count: str,
    club_count: str,
    known_points_count: str,
    status_label: str,
    status_value: str,
) -> None:
    metric1, metric2, metric3, metric4 = st.columns(4)
    metric1.metric("Players", player_count)
    metric2.metric("Clubs", club_count)
    metric3.metric("Known MD points", known_points_count)
    metric4.metric(status_label, status_value)


def display_player_table(df: pd.DataFrame) -> None:
    view = df.copy()
    view["Position"] = view["fantasy_position"].map(POSITION_LABELS)
    view["Availability"] = view["availability"].map(AVAILABILITY_LABELS).fillna(view["availability"])
    view["Price (£m)"] = view["price_m"]
    view["MD points"] = view["matchday_points"]
    view["Points / £m"] = view["points_per_m"]
    columns = ["player", "club", "Position", "Price (£m)", "MD points", "Points / £m", "Availability"]
    st.dataframe(
        view[columns], width="stretch", hide_index=True,
        column_config={
            "player": st.column_config.TextColumn("Player"),
            "club": st.column_config.TextColumn("Club"),
            "Price (£m)": st.column_config.NumberColumn(format="%.2f"),
            "MD points": st.column_config.NumberColumn(format="%.0f"),
            "Points / £m": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def display_player_detail(row: pd.Series) -> None:
    points = "—" if pd.isna(row.get("matchday_points")) else f"{row['matchday_points']:.0f} P"
    price = "—" if pd.isna(row.get("price_m")) else f"£{row['price_m']:.2f}m"
    position = POSITION_LABELS.get(row.get("fantasy_position"), row.get("fantasy_position", ""))
    availability = AVAILABILITY_LABELS.get(row.get("availability"), str(row.get("availability", "")).title())
    st.markdown(
        f"""
        <div class="player-hero">
          <div class="player-kicker">{position.upper()}</div>
          <div class="player-name">{row['player']}</div>
          <div class="player-club">{row['club']} · {availability}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    metric1, metric2, metric3, metric4 = st.columns(4)
    metric1.metric("Matchday points", points)
    metric2.metric("Market value", price)
    metric3.metric("Minutes", "—" if pd.isna(row.get("minutes")) else f"{row['minutes']:.0f}'")
    metric4.metric("API rating", "—" if pd.isna(row.get("rating")) else f"{row['rating']:.1f}")
    if pd.notna(row.get("home_team")):
        score = "–"
        if pd.notna(row.get("home_goals")) and pd.notna(row.get("away_goals")):
            score = f"{row['home_goals']:.0f} – {row['away_goals']:.0f}"
        st.markdown(
            f"<div class='fixture-strip'><span>{row['home_team']}</span><strong>{score}</strong>"
            f"<span>{row['away_team']}</span></div>", unsafe_allow_html=True,
        )
    if not bool(row.get("api_match", False)):
        st.info("No approved API match is linked to this player yet, so detailed match statistics are unavailable.")
        return
    groups = {
        "Playing time & team": [("Minutes played", "minutes"), ("Goals conceded", "goals_conceded")],
        "Goals & assists": [("Goals", "goals"), ("Assists", "assists")],
        "Shots & chances": [("Shots", "shots"), ("Shots on target", "shots_on_target"), ("Key passes", "key_passes")],
        "Duels & dribbles": [("Duels", "duels_total"), ("Duels won", "duels_won"), ("Dribbles attempted", "dribbles_attempts"), ("Successful dribbles", "dribbles_success")],
        "Defensive actions": [("Tackles", "tackles"), ("Blocks", "blocks"), ("Interceptions", "interceptions")],
        "Goalkeeper actions": [("Saves", "saves"), ("Penalties saved", "penalties_saved")],
        "Cards, fouls & penalties": [("Fouls drawn", "fouls_drawn"), ("Fouls committed", "fouls_committed"), ("Yellow cards", "yellow_cards"), ("Red cards", "red_cards"), ("Penalties won", "penalties_won"), ("Penalties scored", "penalties_scored"), ("Penalties missed", "penalties_missed")],
    }
    st.markdown("#### Match statistics")
    st.caption("These are API-Football match statistics, not an inferred Official Fantasy points breakdown.")
    for title, fields in groups.items():
        available = [(label, row.get(key)) for label, key in fields if pd.notna(row.get(key))]
        total = sum(float(value) for _, value in available) if available else 0
        with st.expander(f"{title} · {total:g}", expanded=title in {"Playing time & team", "Goals & assists"}):
            if not available or all(float(value) == 0 for _, value in available):
                st.caption("There are no recorded entries in this category.")
            else:
                for label, value in available:
                    st.markdown(
                        f"<div class='stat-row'><span>{label}</span><strong>{float(value):g}</strong></div>",
                        unsafe_allow_html=True,
                    )
