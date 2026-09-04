from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from data_repository import FantasyRepository
from outlook_model import (
    aggregate_outlook,
    extract_outlook_from_text,
    load_outlook_evidence,
    save_outlook_evidence,
)


REVIEW_COLUMNS = [
    "player",
    "club",
    "position",
    "status",
    "start_probability",
    "role",
    "injury_news",
    "source",
    "source_url",
    "captured_at",
    "evidence_note",
    "parser_rule",
]


def _normalise_review(frame: pd.DataFrame) -> pd.DataFrame:
    review = frame.copy()
    for column in REVIEW_COLUMNS:
        if column not in review.columns:
            review[column] = ""
    review["start_probability"] = pd.to_numeric(review["start_probability"], errors="coerce").fillna(50).clip(0, 100)
    review["injury_news"] = review["injury_news"].fillna(False).astype(bool)
    return review[REVIEW_COLUMNS]


def _append_evidence(season: int, matchday: int, incoming: pd.DataFrame) -> None:
    existing = load_outlook_evidence(season, matchday)
    combined = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
    save_outlook_evidence(season, matchday, combined)


def render_outlook_tab(
    repository: FantasyRepository,
    season: int,
    matchday: int,
) -> None:
    st.subheader(f"Matchday Outlook · MD{matchday}")
    st.caption(
        "Paste a probable-lineup/news source or add a manual observation. The app structures the evidence first, then asks you to review it before saving. Saved outlook evidence can override the older previous-match minutes proxy."
    )

    planning = repository.get_planning_players(season, matchday).copy()
    if planning.empty:
        st.info("No planning-player list is available for this matchday yet.")
        return

    source_tab, manual_tab, current_tab = st.tabs(["Paste source", "Manual entry", "Current outlook"])

    with source_tab:
        source_name = st.text_input("Source name", placeholder="e.g. Fantasy Football Scout")
        source_url = st.text_input("Source URL", placeholder="https://...")
        pasted = st.text_area(
            "Paste article, predicted lineup or notes",
            height=280,
            placeholder="Paste the relevant text here. The parser will match known Fantasy Bundesliga players and infer start/bench language where it can.",
        )
        if st.button("Extract outlook", type="primary", use_container_width=True):
            extracted = extract_outlook_from_text(
                pasted,
                planning,
                source_name,
                source_url,
            )
            st.session_state[f"outlook_review_{season}_{matchday}"] = _normalise_review(extracted)

        review_key = f"outlook_review_{season}_{matchday}"
        if review_key in st.session_state:
            review = st.session_state[review_key]
            if review.empty:
                st.warning("No known players were matched in the pasted text.")
            else:
                st.markdown("#### Review extracted evidence")
                st.caption("Edit any uncertain status, probability, role or note before saving.")
                edited = st.data_editor(
                    review,
                    hide_index=True,
                    width="stretch",
                    num_rows="dynamic",
                    column_config={
                        "start_probability": st.column_config.NumberColumn("Start probability", min_value=0, max_value=100, step=5, format="%.0f%%"),
                        "injury_news": st.column_config.CheckboxColumn("Injury/news flag"),
                        "evidence_note": st.column_config.TextColumn("Evidence note", width="large"),
                        "source_url": st.column_config.LinkColumn("Source URL"),
                    },
                    key=f"outlook_editor_{season}_{matchday}",
                )
                if st.button("Approve and save extracted evidence", use_container_width=True):
                    _append_evidence(season, matchday, _normalise_review(edited))
                    del st.session_state[review_key]
                    st.success("Outlook evidence saved.")
                    st.rerun()

    with manual_tab:
        player_options = planning.sort_values(["club", "player"])["player"].drop_duplicates().tolist()
        player = st.selectbox("Player", player_options, key=f"manual_outlook_player_{season}_{matchday}")
        row = planning.loc[planning["player"] == player].iloc[0]
        c1, c2, c3 = st.columns(3)
        status = c1.selectbox(
            "Status",
            ["Starter", "Likely starter", "Uncertain", "Bench option", "Unlikely starter"],
            index=2,
        )
        probability = c2.slider("Start probability", 0, 100, 50, 5)
        role = c3.text_input("Expected role", placeholder="e.g. RWB, AM, CF")
        injury_news = st.checkbox("Injury/news concern")
        manual_source = st.text_input("Source", key=f"manual_source_{season}_{matchday}")
        manual_url = st.text_input("Source URL", key=f"manual_url_{season}_{matchday}")
        note = st.text_area("Evidence note", key=f"manual_note_{season}_{matchday}")
        if st.button("Save manual evidence", use_container_width=True):
            evidence = pd.DataFrame([
                {
                    "player": player,
                    "club": str(row.get("club", "")),
                    "position": str(row.get("fantasy_position", "")),
                    "status": status,
                    "start_probability": probability,
                    "role": role,
                    "injury_news": injury_news,
                    "source": manual_source.strip() or "Manual entry",
                    "source_url": manual_url.strip(),
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "evidence_note": note.strip(),
                    "parser_rule": "manual",
                }
            ])
            _append_evidence(season, matchday, evidence)
            st.success(f"Saved outlook evidence for {player}.")
            st.rerun()

    with current_tab:
        evidence = load_outlook_evidence(season, matchday)
        if evidence.empty:
            st.info("No outlook evidence has been saved for this matchday yet.")
            return

        summary = aggregate_outlook(evidence)
        st.markdown("#### Aggregated outlook")
        st.dataframe(
            summary,
            hide_index=True,
            width="stretch",
            column_config={
                "lineup_likelihood": st.column_config.NumberColumn("Start probability", format="%.0f%%"),
                "source_count": st.column_config.NumberColumn("Sources", format="%d"),
            },
        )
        st.markdown("#### Source evidence")
        st.dataframe(
            evidence.sort_values("captured_at", ascending=False),
            hide_index=True,
            width="stretch",
            column_config={
                "start_probability": st.column_config.NumberColumn("Start probability", format="%.0f%%"),
                "source_url": st.column_config.LinkColumn("Source URL"),
                "evidence_note": st.column_config.TextColumn("Evidence note", width="large"),
            },
        )
