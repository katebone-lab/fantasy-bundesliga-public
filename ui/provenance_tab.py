from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = ROOT / "data" / "public_provenance.json"
RESULTS = ROOT / "data" / "fixture_model" / "2026_results.csv"


def _read_provenance() -> dict:
    if not PROVENANCE.exists():
        return {"generated_at_utc": None, "api_pulls": [], "screenshot_batches": []}
    try:
        data = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"generated_at_utc": None, "api_pulls": [], "screenshot_batches": []}
    data.setdefault("api_pulls", [])
    data.setdefault("screenshot_batches", [])
    return data


def _date(value) -> str:
    if value in (None, ""):
        return "—"
    try:
        stamp = pd.to_datetime(value, utc=True)
        return stamp.strftime("%d %b %Y · %H:%M UTC")
    except Exception:
        return str(value)


def render_provenance_tab() -> None:
    st.subheader("Data freshness & provenance")
    st.caption(
        "A compact audit trail showing when the app's competition, API and Fantasy screenshot data were refreshed."
    )

    provenance = _read_provenance()
    api = pd.DataFrame(provenance["api_pulls"])
    screenshots = pd.DataFrame(provenance["screenshot_batches"])

    latest_results_md = None
    result_rows = 0
    if RESULTS.exists():
        results = pd.read_csv(RESULTS)
        if not results.empty:
            latest_results_md = int(pd.to_numeric(results["matchday"], errors="coerce").max())
            result_rows = len(results)

    latest_api_md = None
    latest_api_at = None
    if not api.empty:
        latest_api_md = api.iloc[0].get("matchday")
        latest_api_at = api.iloc[0].get("completed_at_utc") or api.iloc[0].get("started_at_utc")

    latest_shot_md = None
    latest_shot_at = None
    if not screenshots.empty:
        latest_shot_md = screenshots.iloc[0].get("matchday")
        latest_shot_at = screenshots.iloc[0].get("published_at_utc") or screenshots.iloc[0].get("captured_at_utc")

    cols = st.columns(4)
    cols[0].metric("Bundesliga results", f"Through MD{latest_results_md}" if latest_results_md else "Not captured")
    cols[1].metric("API-Football", f"Through MD{int(latest_api_md)}" if pd.notna(latest_api_md) else "Awaiting provenance")
    cols[2].metric("Fantasy screenshots", f"Through MD{int(latest_shot_md)}" if pd.notna(latest_shot_md) else "Awaiting provenance")
    cols[3].metric("Results captured", f"{result_rows} matches")

    if provenance.get("generated_at_utc"):
        st.caption(f"Provenance feed last generated: {_date(provenance['generated_at_utc'])}")
    else:
        st.info(
            "The provenance feed has not been published yet. The panel is ready and will populate as the automated API workflow and future screenshot batches publish metadata."
        )

    st.markdown("#### API-Football pulls")
    if api.empty:
        st.caption("No API pull history has been published to the provenance feed yet.")
    else:
        view = api.copy()
        if "completed_at_utc" in view:
            view["completed_at_utc"] = view["completed_at_utc"].map(_date)
        if "started_at_utc" in view:
            view["started_at_utc"] = view["started_at_utc"].map(_date)
        keep = [c for c in ["provider", "season", "matchday", "status", "completed_at_utc", "started_at_utc"] if c in view]
        labels = {"provider":"Source", "season":"Season", "matchday":"MD", "status":"Status", "completed_at_utc":"Completed", "started_at_utc":"Started"}
        st.dataframe(view[keep].rename(columns=labels), hide_index=True, width="stretch")
        if latest_api_at:
            st.caption(f"Latest API refresh: {_date(latest_api_at)}")

    st.markdown("#### Fantasy screenshot uploads")
    if screenshots.empty:
        st.caption("No screenshot-batch history has been published to the provenance feed yet.")
    else:
        view = screenshots.copy()
        for col in ["captured_at_utc", "approved_at_utc", "published_at_utc"]:
            if col in view:
                view[col] = view[col].map(_date)
        keep = [c for c in ["batch_key", "season", "matchday", "status", "image_count", "captured_at_utc", "published_at_utc"] if c in view]
        labels = {"batch_key":"Batch", "season":"Season", "matchday":"MD", "status":"Status", "image_count":"Images", "captured_at_utc":"Captured / uploaded", "published_at_utc":"Published"}
        st.dataframe(view[keep].rename(columns=labels), hide_index=True, width="stretch")
        if latest_shot_at:
            st.caption(f"Latest Fantasy screenshot publication: {_date(latest_shot_at)}")

    st.markdown("#### What each source means")
    st.write(
        "**Bundesliga results** are competition facts used for the league table and team-strength/FDR model. "
        "**API-Football** supplies player-level match statistics such as minutes and ratings. "
        "**Fantasy screenshots** are the evidence for Fantasy Bundesliga prices and fantasy points after the transfer market reopens."
    )
