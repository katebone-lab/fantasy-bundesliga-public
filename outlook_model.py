from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


OUTLOOK_ROOT = Path(__file__).resolve().parent / "data" / "matchday_outlook"

STATUS_RULES = [
    (r"expected to start|set to start|likely to start|should start|predicted to start", "Likely starter", 88),
    (r"will start|starts|starting xi|named in the xi", "Starter", 95),
    (r"could start|may start|in contention|pushing for a start|possible starter", "Uncertain", 55),
    (r"bench option|likely from the bench|expected on the bench|substitute", "Bench option", 30),
    (r"expected to miss out|unlikely to start|not expected to start|doubtful|ruled out|injured", "Unlikely starter", 15),
]

ROLE_PATTERNS = [
    (r"right wing-back|rwb", "RWB"),
    (r"left wing-back|lwb", "LWB"),
    (r"right-back|right back|rb", "RB"),
    (r"left-back|left back|lb", "LB"),
    (r"centre-back|center-back|centre back|center back|cb", "CB"),
    (r"attacking midfield|number 10|no\. ?10|am", "AM"),
    (r"central midfield|centre midfield|cm", "CM"),
    (r"defensive midfield|dm", "DM"),
    (r"right wing|right winger|rw", "RW"),
    (r"left wing|left winger|lw", "LW"),
    (r"striker|centre-forward|center-forward|cf", "CF"),
]


def outlook_path(season: int, matchday: int) -> Path:
    return OUTLOOK_ROOT / f"{season}_md{matchday:02d}.json"


def load_outlook_evidence(season: int, matchday: int) -> pd.DataFrame:
    path = outlook_path(season, matchday)
    if not path.exists():
        return pd.DataFrame()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return pd.DataFrame(payload.get("evidence", []))


def save_outlook_evidence(season: int, matchday: int, evidence: pd.DataFrame) -> Path:
    OUTLOOK_ROOT.mkdir(parents=True, exist_ok=True)
    path = outlook_path(season, matchday)
    payload = {
        "season": int(season),
        "matchday": int(matchday),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "evidence": evidence.to_dict(orient="records"),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _classify_context(context: str) -> tuple[str, int, str]:
    lower = context.lower()
    for pattern, label, probability in STATUS_RULES:
        if re.search(pattern, lower):
            return label, probability, pattern
    return "Uncertain", 50, "no explicit starting-language match"


def _infer_role(context: str) -> str:
    lower = context.lower()
    for pattern, role in ROLE_PATTERNS:
        if re.search(pattern, lower):
            return role
    return ""


def extract_outlook_from_text(
    text: str,
    players: pd.DataFrame,
    source_name: str,
    source_url: str,
) -> pd.DataFrame:
    if not text.strip() or players.empty:
        return pd.DataFrame()

    rows: list[dict] = []
    source_text = re.sub(r"\s+", " ", text.strip())
    captured_at = datetime.now(timezone.utc).isoformat()

    player_rows = players[[c for c in ["player", "club", "fantasy_position"] if c in players.columns]].drop_duplicates("player")
    for _, player_row in player_rows.iterrows():
        player = str(player_row["player"])
        match = re.search(rf"(?<!\w){re.escape(player)}(?!\w)", source_text, flags=re.IGNORECASE)
        if not match:
            continue
        start = max(0, match.start() - 180)
        end = min(len(source_text), match.end() + 180)
        context = source_text[start:end]
        status, probability, rule = _classify_context(context)
        rows.append(
            {
                "player": player,
                "club": str(player_row.get("club", "")),
                "position": str(player_row.get("fantasy_position", "")),
                "status": status,
                "start_probability": probability,
                "role": _infer_role(context),
                "injury_news": bool(re.search(r"injur|doubt|ruled out|suspend|illness", context, flags=re.IGNORECASE)),
                "source": source_name.strip() or "Pasted source",
                "source_url": source_url.strip(),
                "captured_at": captured_at,
                "evidence_note": context.strip(),
                "parser_rule": rule,
            }
        )
    return pd.DataFrame(rows)


def aggregate_outlook(evidence: pd.DataFrame) -> pd.DataFrame:
    if evidence.empty:
        return evidence
    working = evidence.copy()
    working["start_probability"] = pd.to_numeric(working["start_probability"], errors="coerce").clip(0, 100)
    grouped = []
    for player, rows in working.groupby("player", sort=True):
        probs = rows["start_probability"].dropna()
        probability = float(probs.mean()) if not probs.empty else 50.0
        if probability >= 80:
            label = "Likely starter"
        elif probability >= 60:
            label = "Leaning start"
        elif probability >= 40:
            label = "Uncertain"
        elif probability >= 20:
            label = "Leaning bench"
        else:
            label = "Unlikely starter"
        latest = rows.sort_values("captured_at").iloc[-1]
        roles = rows["role"].dropna().astype(str)
        roles = roles[roles.str.len() > 0]
        grouped.append(
            {
                "player": player,
                "club": latest.get("club", ""),
                "position": latest.get("position", ""),
                "lineup_likelihood": round(probability, 1),
                "lineup_label": label,
                "role": roles.iloc[-1] if not roles.empty else "",
                "source_count": int(rows["source"].nunique()),
                "latest_source": latest.get("source", ""),
                "latest_captured_at": latest.get("captured_at", ""),
            }
        )
    return pd.DataFrame(grouped)


def apply_outlook_overrides(planning: pd.DataFrame, season: int, matchday: int) -> pd.DataFrame:
    evidence = load_outlook_evidence(season, matchday)
    if evidence.empty or planning.empty:
        return planning
    outlook = aggregate_outlook(evidence)
    if outlook.empty:
        return planning
    result = planning.merge(
        outlook[["player", "lineup_likelihood", "lineup_label", "role", "source_count", "latest_source"]],
        on="player",
        how="left",
        suffixes=("", "_outlook"),
    )
    for column in ["lineup_likelihood", "lineup_label"]:
        override = f"{column}_outlook"
        if override in result.columns:
            result[column] = result[override].combine_first(result.get(column))
            result = result.drop(columns=[override])
    return result
