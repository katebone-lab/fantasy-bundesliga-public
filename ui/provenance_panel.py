from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_PATH = ROOT / "data" / "provenance.json"
RESULTS_PATH = ROOT / "data" / "fixture_model" / "2026_results.csv"


def _display_time(value: object) -> str:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return "Not recorded"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%d %b %Y %H:%M UTC")
    except ValueError:
        return text


def _load_events() -> list[dict]:
    if not PROVENANCE_PATH.exists():
        return []
    payload = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    events = payload.get("events", [])
    return events if isinstance(events, list) else []


def _results_freshness() -> tuple[str, str]:
    if not RESULTS_PATH.exists():
        return "No results file", "Not recorded"
    results = pd.read_csv(RESULTS_PATH)
    if results.empty:
        return "No completed results", "Not recorded"
    completed = results[results["status"].astype(str).str.lower().eq("final")].copy()
    if completed.empty:
        return "No completed results", "Not recorded"
    latest_md = int(completed["matchday"].max())
    latest_rows = completed[completed["matchday"] == latest_md]
    captured = latest_rows.get("captured_at")
    captured_at = "Not recorded"
    if captured is not None and captured.notna().any():
        captured_at = _display_time(captured.dropna().astype(str).max())
    return f"Through MD{latest_md} · {len(latest_rows)}/9 results", captured_at


def render_provenance_panel() -> None:
    events = _load_events()
    results_status, results_time = _results_freshness()

    with st.sidebar.expander("Data freshness & provenance", expanded=False):
        st.caption("What the app currently knows, when it was refreshed, and where it came from.")

        st.markdown("**Bundesliga results**")
        st.write(results_status)
        st.caption(f"Official Bundesliga · captured {results_time}")

        api_events = [event for event in events if event.get("kind") == "api_football"]
        st.markdown("**API-Football player stats**")
        if api_events:
            latest = sorted(
                api_events,
                key=lambda item: item.get("published_at_utc") or item.get("observed_at_utc") or "",
                reverse=True,
            )[0]
            st.write(f"MD{latest.get('matchday', '—')} · {latest.get('status', 'recorded')}")
            st.caption(
                "API-Football · "
                + _display_time(latest.get("published_at_utc") or latest.get("observed_at_utc"))
            )
        else:
            st.write("No automated pull recorded yet")
            st.caption("The first successful scheduled import will appear here.")

        screenshot_events = [event for event in events if event.get("kind") == "fantasy_screenshot"]
        st.markdown("**Fantasy screenshot captures**")
        if screenshot_events:
            for event in sorted(
                screenshot_events,
                key=lambda item: (item.get("season", 0), item.get("matchday", 0)),
                reverse=True,
            )[:4]:
                st.write(f"MD{event.get('matchday', '—')} · {event.get('label', 'Screenshot capture')}")
                observed = event.get("observed_at_utc")
                published = event.get("published_at_utc")
                if observed:
                    st.caption(f"Uploaded/captured {_display_time(observed)}")
                elif published:
                    st.caption(f"Published {_display_time(published)} · original upload time not recorded")
                if event.get("details"):
                    st.caption(str(event["details"]))
        else:
            st.write("No screenshot capture recorded")

        if events:
            with st.popover("Full provenance log"):
                rows = []
                for event in sorted(
                    events,
                    key=lambda item: item.get("published_at_utc") or item.get("observed_at_utc") or "",
                    reverse=True,
                ):
                    rows.append(
                        {
                            "Source": event.get("kind", "unknown").replace("_", " ").title(),
                            "Season": event.get("season"),
                            "MD": event.get("matchday"),
                            "Observed / uploaded": _display_time(event.get("observed_at_utc")),
                            "Published": _display_time(event.get("published_at_utc")),
                            "Status": event.get("status", "recorded"),
                            "Details": event.get("details", ""),
                        }
                    )
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
