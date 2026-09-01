from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pandas as pd

from database_config import DEFAULT_DATABASE_CONFIG, PROJECT_ROOT, DatabaseConfig


class RepositoryError(ValueError):
    pass


@dataclass(frozen=True)
class MatchStatsResult:
    data: pd.DataFrame
    source_path: Path | None


@dataclass(frozen=True)
class MatchdayAvailability:
    season: int
    matchday: int
    round_name: str | None
    fantasy_player_count: int
    fixture_count: int
    api_stat_count: int
    squad_states: tuple[str, ...]


class FantasyRepository:
    def __init__(self, config: DatabaseConfig = DEFAULT_DATABASE_CONFIG, *, writable: bool = True):
        self.config = config
        self.writable = writable

    @property
    def database_path(self) -> Path:
        return self.config.resolved_path()

    def cache_token(self) -> int:
        return self.database_path.stat().st_mtime_ns

    def _open_connection(self) -> sqlite3.Connection:
        conn = (
            sqlite3.connect(f"file:{self.database_path.resolve()}?mode=ro", uri=True)
            if not self.writable else sqlite3.connect(self.database_path)
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._open_connection()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        if not self.writable:
            raise RepositoryError("Writes are disabled in public mode")
        with self._connection() as conn:
            with conn:
                yield conn

    def get_fantasy_players(self, season: int, matchday: int) -> pd.DataFrame:
        """Return official performance-matchday facts with same-matchday temporal facts."""
        with self._connection() as conn:
            return pd.read_sql_query(
                """SELECT player_id AS fantasy_player_id, player, club, season, matchday,
                          fantasy_position, price_m, availability, matchday_points,
                          points_per_m, notes
                   FROM vw_fantasy_player_matchday
                   WHERE season=? AND matchday=?
                   ORDER BY fantasy_player_matchday_id""",
                conn,
                params=(season, matchday),
            )

    def get_fantasy_performance(self, season: int, matchday: int) -> pd.DataFrame:
        return self.get_fantasy_players(season, matchday)

    def get_effective_prices(self, season: int, matchday: int) -> pd.DataFrame:
        with self._connection() as conn:
            return pd.read_sql_query(
                """SELECT player_id,player,season,effective_matchday,price_m,
                          price_movement_hundredths_m/100.0 AS price_movement_m
                   FROM vw_fantasy_price_history WHERE season=? AND effective_matchday=?
                   ORDER BY player_id""", conn, params=(season,matchday))

    def get_effective_availability(self, season: int, matchday: int) -> pd.DataFrame:
        with self._connection() as conn:
            return pd.read_sql_query(
                """SELECT fa.player_id,p.canonical_name AS player,fa.availability,fa.notes
                   FROM fantasy_player_availability_history fa
                   JOIN players p ON p.player_id=fa.player_id
                   JOIN matchdays md ON md.matchday_id=fa.effective_matchday_id
                   JOIN seasons s ON s.season_id=md.season_id
                   WHERE s.start_year=? AND md.matchday_number=? ORDER BY fa.player_id""",
                conn, params=(season,matchday))

    def get_player_price_history(self, player_id: int, season: int) -> pd.DataFrame:
        with self._connection() as conn:
            return pd.read_sql_query(
                """SELECT * FROM vw_fantasy_price_history WHERE player_id=? AND season=?
                   ORDER BY effective_matchday""", conn, params=(player_id,season))

    def get_planning_players(self, season: int, planning_matchday: int) -> pd.DataFrame:
        """Combine prior performance with facts explicitly effective for a planning matchday."""
        with self._connection() as conn:
            return pd.read_sql_query(
                """SELECT v.player_id AS fantasy_player_id,v.player,
                          c.canonical_name AS club,v.season,
                          v.performance_matchday AS matchday,
                          v.applicable_fantasy_position AS fantasy_position,
                          v.effective_price_m AS price_m,
                          v.effective_availability AS availability,
                          v.performance_points AS matchday_points,
                          CASE WHEN v.effective_price_m>0 AND v.performance_points IS NOT NULL
                               THEN v.performance_points/v.effective_price_m END AS points_per_m,
                          '' AS notes,v.planning_matchday,v.planning_context_status,
                          v.performance_club_id,v.planning_club_id
                   FROM vw_fantasy_player_planning_matchday v
                   JOIN clubs c ON c.club_id=v.applicable_club_id
                   WHERE v.season=? AND v.planning_matchday=?
                   ORDER BY v.player_id""", conn, params=(season,planning_matchday))

    def get_available_matchdays(self) -> list[MatchdayAvailability]:
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT s.start_year AS season, md.matchday_number AS matchday,
                          md.round_name,
                          (SELECT COUNT(*) FROM fantasy_player_matchdays fpm
                           WHERE fpm.matchday_id=md.matchday_id) AS fantasy_player_count,
                          (SELECT COUNT(*) FROM fixtures f
                           WHERE f.matchday_id=md.matchday_id) AS fixture_count,
                          (SELECT COUNT(*) FROM api_player_fixture_stats apfs
                           JOIN fixtures f ON f.fixture_id=apfs.fixture_id
                           WHERE f.matchday_id=md.matchday_id) AS api_stat_count
                   FROM matchdays md
                   JOIN seasons s ON s.season_id=md.season_id
                   ORDER BY s.start_year, md.matchday_number"""
            ).fetchall()
            states = conn.execute(
                """SELECT s.start_year AS season, md.matchday_number AS matchday, sq.status
                   FROM squads sq
                   JOIN matchdays md ON md.matchday_id=sq.matchday_id
                   JOIN seasons s ON s.season_id=md.season_id
                   ORDER BY s.start_year, md.matchday_number,
                            CASE sq.status WHEN 'final' THEN 0 ELSE 1 END"""
            ).fetchall()
        states_by_context: dict[tuple[int, int], list[str]] = {}
        for row in states:
            states_by_context.setdefault((row["season"], row["matchday"]), []).append(row["status"])
        return [
            MatchdayAvailability(
                season=row["season"],
                matchday=row["matchday"],
                round_name=row["round_name"],
                fantasy_player_count=row["fantasy_player_count"],
                fixture_count=row["fixture_count"],
                api_stat_count=row["api_stat_count"],
                squad_states=tuple(states_by_context.get((row["season"], row["matchday"]), [])),
            )
            for row in rows
        ]

    def get_fantasy_source_path(self, season: int, matchday: int) -> Path | None:
        with self._connection() as conn:
            row = conn.execute(
                """SELECT si.source_path
                   FROM fantasy_player_matchdays fpm
                   JOIN matchdays md ON md.matchday_id=fpm.matchday_id
                   JOIN seasons s ON s.season_id=md.season_id
                   JOIN source_imports si ON si.source_import_id=fpm.source_import_id
                   WHERE s.start_year=? AND md.matchday_number=?
                   ORDER BY si.source_import_id DESC LIMIT 1""",
                (season, matchday),
            ).fetchone()
        return PROJECT_ROOT / row[0] if row else None

    def get_latest_fantasy_matchday_at_or_before(
        self, season: int, matchday: int
    ) -> int | None:
        with self._connection() as conn:
            row = conn.execute(
                """SELECT MAX(md.matchday_number)
                   FROM fantasy_player_matchdays fpm
                   JOIN matchdays md ON md.matchday_id=fpm.matchday_id
                   JOIN seasons s ON s.season_id=md.season_id
                   WHERE s.start_year=? AND md.matchday_number<=?""",
                (season, matchday),
            ).fetchone()
        return row[0] if row and row[0] is not None else None

    def get_match_stats(self, season: int, matchday: int) -> MatchStatsResult:
        with self._connection() as conn:
            data = pd.read_sql_query(
                """SELECT v.api_player_id AS api_player_id,
                          v.api_player AS player,
                          v.external_fixture_id AS fixture_id,
                          v.kickoff_utc AS date,
                          v.status_short AS status,
                          COALESCE(team_alias.alias, v.club) AS team,
                          CASE
                            WHEN stats.club_id = fixture.home_club_id
                            THEN COALESCE(away_alias.alias, v.away_team)
                            ELSE COALESCE(home_alias.alias, v.home_team)
                          END AS opponent,
                          COALESCE(home_alias.alias, v.home_team) AS home_team,
                          COALESCE(away_alias.alias, v.away_team) AS away_team,
                          v.home_goals, v.away_goals, v.api_position AS position,
                          v.minutes, v.rating, v.captain, v.substitute,
                          v.shots, v.shots_on_target, v.goals, v.assists,
                          v.goals_conceded, v.saves, v.key_passes, v.passes_total,
                          v.pass_accuracy, v.tackles, v.blocks, v.interceptions,
                          v.duels_total, v.duels_won, v.dribbles_attempts,
                          v.dribbles_success, v.fouls_drawn, v.fouls_committed,
                          v.yellow_cards, v.red_cards, v.penalties_won,
                          v.penalties_scored, v.penalties_missed, v.penalties_saved
                   FROM vw_player_fixture_stats v
                   JOIN api_player_fixture_stats stats
                     ON stats.api_player_fixture_stat_id=v.api_player_fixture_stat_id
                   JOIN fixtures fixture ON fixture.fixture_id=v.fixture_id
                   LEFT JOIN club_aliases team_alias
                     ON team_alias.club_id=stats.club_id
                    AND team_alias.provider=fixture.provider
                   LEFT JOIN club_aliases home_alias
                     ON home_alias.club_id=fixture.home_club_id
                    AND home_alias.provider=fixture.provider
                   LEFT JOIN club_aliases away_alias
                     ON away_alias.club_id=fixture.away_club_id
                    AND away_alias.provider=fixture.provider
                   WHERE v.season=? AND v.matchday=?
                   ORDER BY stats.api_player_fixture_stat_id""",
                conn,
                params=(season, matchday),
            )
            source = conn.execute(
                """SELECT si.source_path
                   FROM api_player_fixture_stats apfs
                   JOIN fixtures f ON f.fixture_id=apfs.fixture_id
                   JOIN matchdays md ON md.matchday_id=f.matchday_id
                   JOIN seasons s ON s.season_id=md.season_id
                   JOIN source_imports si ON si.source_import_id=apfs.source_import_id
                   WHERE s.start_year=? AND md.matchday_number=?
                   ORDER BY si.source_import_id DESC LIMIT 1""",
                (season, matchday),
            ).fetchone()
        source_path = PROJECT_ROOT / source[0] if source else None
        return MatchStatsResult(data=data, source_path=source_path)

    def get_approved_name_map(self, season: int, matchday: int) -> pd.DataFrame:
        with self._connection() as conn:
            return pd.read_sql_query(
                """SELECT p.canonical_name AS fantasy_name,
                          c.canonical_name AS club,
                          ap.canonical_name AS api_name
                   FROM player_api_resolutions r
                   JOIN players p ON p.player_id=r.player_id
                   JOIN api_players ap ON ap.api_player_id=r.api_player_id
                   JOIN fantasy_player_matchdays fpm ON fpm.player_id=p.player_id
                   JOIN matchdays md ON md.matchday_id=fpm.matchday_id
                   JOIN seasons s ON s.season_id=md.season_id
                   JOIN clubs c ON c.club_id=fpm.club_id
                   WHERE r.status='approved' AND s.start_year=? AND md.matchday_number=?
                     AND (r.scope_club_id IS NULL OR r.scope_club_id=fpm.club_id)
                     AND (r.scope_matchday_id IS NULL OR r.scope_matchday_id=fpm.matchday_id)
                   ORDER BY c.canonical_name, p.canonical_name""",
                conn,
                params=(season, matchday),
            )

    def get_manual_only_players(self, season: int, matchday: int) -> pd.DataFrame:
        with self._connection() as conn:
            return pd.read_sql_query(
                """SELECT p.canonical_name AS fantasy_name, c.canonical_name AS club
                   FROM player_api_resolutions r
                   JOIN players p ON p.player_id=r.player_id
                   JOIN fantasy_player_matchdays fpm ON fpm.player_id=p.player_id
                   JOIN matchdays md ON md.matchday_id=fpm.matchday_id
                   JOIN seasons s ON s.season_id=md.season_id
                   JOIN clubs c ON c.club_id=fpm.club_id
                   WHERE r.status='manual_only' AND s.start_year=? AND md.matchday_number=?
                     AND (r.scope_club_id IS NULL OR r.scope_club_id=fpm.club_id)
                     AND (r.scope_matchday_id IS NULL OR r.scope_matchday_id=fpm.matchday_id)
                   ORDER BY c.canonical_name, p.canonical_name""",
                conn,
                params=(season, matchday),
            )

    def get_team_history(self) -> list[tuple[int, dict]]:
        with self._connection() as conn:
            squads = conn.execute(
                """SELECT squad_id FROM vw_squad_matchday
                   ORDER BY season DESC, matchday DESC, status='draft' DESC"""
            ).fetchall()
        return [(row[0], self.get_squad(row[0])) for row in squads]

    def get_team_history_for_matchday(
        self, season: int, matchday: int
    ) -> list[tuple[int, dict]]:
        with self._connection() as conn:
            squads = conn.execute(
                """SELECT v.squad_id FROM vw_squad_matchday v
                   WHERE v.season=? AND v.matchday=?
                   ORDER BY v.status='draft' DESC, v.squad_id DESC""",
                (season, matchday),
            ).fetchall()
        return [(row[0], self.get_squad(row[0])) for row in squads]

    def get_previous_final_squad_id(self, season: int, matchday: int) -> int | None:
        with self._connection() as conn:
            row = conn.execute(
                """SELECT sq.squad_id
                   FROM squads sq
                   JOIN matchdays md ON md.matchday_id=sq.matchday_id
                   JOIN seasons s ON s.season_id=md.season_id
                   WHERE s.start_year=? AND md.matchday_number=? AND sq.status='final'
                   ORDER BY sq.squad_id DESC LIMIT 1""",
                (season, matchday - 1),
            ).fetchone()
        return row[0] if row else None

    def get_squad(self, squad_id: int) -> dict:
        with self._connection() as conn:
            squad = conn.execute(
                """SELECT v.*, sq.source_description, sq.source_file
                   FROM vw_squad_matchday v JOIN squads sq ON sq.squad_id=v.squad_id
                   WHERE v.squad_id=?""",
                (squad_id,),
            ).fetchone()
            if squad is None:
                raise RepositoryError(f"Squad {squad_id} does not exist")
            members = conn.execute(
                """SELECT v.*,
                          COALESCE(v.recorded_points, (
                            SELECT prior_sm.recorded_points
                            FROM squad_memberships prior_sm
                            JOIN squads prior_sq ON prior_sq.squad_id=prior_sm.squad_id
                            JOIN matchdays prior_md ON prior_md.matchday_id=prior_sq.matchday_id
                            JOIN seasons prior_s ON prior_s.season_id=prior_md.season_id
                            WHERE prior_sm.player_id=v.player_id
                              AND prior_sq.status='final' AND prior_s.start_year=v.season
                              AND prior_md.matchday_number < v.matchday
                            ORDER BY prior_md.matchday_number DESC LIMIT 1
                          ), v.source_fantasy_points) AS previous_points
                   FROM vw_squad_members v WHERE v.squad_id=? ORDER BY v.slot_number""",
                (squad_id,),
            ).fetchall()
            transfers = conn.execute(
                """SELECT v.*, t.slot_number
                   FROM vw_transfer_history v JOIN transfers t ON t.transfer_id=v.transfer_id
                   WHERE v.squad_id=? ORDER BY v.sequence_number""",
                (squad_id,),
            ).fetchall()
            notes = conn.execute(
                "SELECT note_type, note_text FROM squad_notes WHERE squad_id=?",
                (squad_id,),
            ).fetchall()
            budgets = conn.execute(
                """SELECT squad_value_hundredths_m/100.0 AS squad_value_m,
                          cash_hundredths_m/100.0 AS cash_m,
                          total_value_hundredths_m/100.0 AS total_club_value_m, reason
                   FROM squad_budget_snapshots WHERE squad_id=? ORDER BY sequence_number""",
                (squad_id,),
            ).fetchall()
        record = {
            "squad_id": squad_id,
            "record_key": f"{squad['season']}_md{squad['matchday']:02d}",
            "season": squad["season"], "matchday": squad["matchday"],
            "status": squad["status"], "formation": squad["formation"],
            "starting_points": squad["starting_points"],
            "squad_value_m": squad["squad_value_m"], "cash_m": squad["cash_m"],
            "total_club_value_m": squad["total_value_m"],
            "source": squad["source_description"], "source_file": squad["source_file"],
            "players": [], "transfers": [],
            "notes": {row["note_type"]: row["note_text"] for row in notes},
            "budget_snapshots": [dict(row) for row in budgets],
        }
        for row in members:
            record["players"].append({
                "player_id": row["player_id"], "player": row["player"], "club": row["club"],
                "position": row["fantasy_position"], "slot": row["slot"],
                "slot_number": row["slot_number"], "starred": bool(row["starred"]),
                "points": row["recorded_points"], "previous_points": row["previous_points"],
                "price_m": row["valuation_price_m"],
                "purchase_price_m": row["acquisition_price_m"],
            })
        for row in transfers:
            record["transfers"].append({
                "transfer_id": row["transfer_id"], "player_index": row["slot_number"] - 1,
                "slot_number": row["slot_number"], "player_out": row["player_out"],
                "player_in": row["player_in"], "sale_price_m": row["sale_price_m"],
                "purchase_price_m": row["purchase_price_m"],
                "cash_before_m": row["cash_before_m"], "cash_after_m": row["cash_after_m"],
            })
        return record

    def approve_api_resolution(self, player_id: int, api_player_id: int) -> None:
        with self._transaction() as conn:
            player = conn.execute("SELECT 1 FROM players WHERE player_id=?", (player_id,)).fetchone()
            api = conn.execute("SELECT 1 FROM api_players WHERE api_player_id=?", (api_player_id,)).fetchone()
            if not player or not api:
                raise RepositoryError("The selected player identity no longer exists")
            conn.execute("DELETE FROM player_api_resolutions WHERE player_id=?", (player_id,))
            try:
                conn.execute(
                    """INSERT INTO player_api_resolutions(
                           player_id, api_player_id, status, resolution_method
                       ) VALUES (?, ?, 'approved', 'user_approved_in_app')""",
                    (player_id, api_player_id),
                )
            except sqlite3.IntegrityError as exc:
                raise RepositoryError("That API identity is already linked to another player") from exc

    def mark_player_manual_only(self, player_id: int, season: int, matchday: int) -> None:
        with self._transaction() as conn:
            md = conn.execute(
                """SELECT md.matchday_id FROM matchdays md JOIN seasons s ON s.season_id=md.season_id
                   WHERE s.start_year=? AND md.matchday_number=?""",
                (season, matchday),
            ).fetchone()
            if md is None:
                raise RepositoryError("The selected matchday does not exist")
            conn.execute("DELETE FROM player_api_resolutions WHERE player_id=?", (player_id,))
            conn.execute(
                """INSERT INTO player_api_resolutions(
                       player_id, status, scope_matchday_id, resolution_method
                   ) VALUES (?, 'manual_only', ?, 'user_marked_in_app')""",
                (player_id, md[0]),
            )

    def save_squad_notes(self, squad_id: int, notes: dict[str, str]) -> None:
        with self._transaction() as conn:
            if not conn.execute("SELECT 1 FROM squads WHERE squad_id=?", (squad_id,)).fetchone():
                raise RepositoryError("The selected squad does not exist")
            for note_type, note_text in notes.items():
                conn.execute(
                    """INSERT INTO squad_notes(squad_id, note_type, note_text) VALUES (?, ?, ?)
                       ON CONFLICT(squad_id, note_type) DO UPDATE SET note_text=excluded.note_text""",
                    (squad_id, note_type, note_text),
                )

    def create_next_matchday_draft(self, source_squad_id: int) -> int:
        with self._transaction() as conn:
            source = conn.execute(
                """SELECT sq.*, md.matchday_number, md.season_id, s.start_year
                   FROM squads sq JOIN matchdays md ON md.matchday_id=sq.matchday_id
                   JOIN seasons s ON s.season_id=md.season_id WHERE sq.squad_id=?""",
                (source_squad_id,),
            ).fetchone()
            if source is None or source["status"] != "final":
                raise RepositoryError("A draft can only be copied from a final squad")
            next_number = source["matchday_number"] + 1
            conn.execute(
                "INSERT OR IGNORE INTO matchdays(season_id, matchday_number) VALUES (?, ?)",
                (source["season_id"], next_number),
            )
            md_id = conn.execute(
                "SELECT matchday_id FROM matchdays WHERE season_id=? AND matchday_number=?",
                (source["season_id"], next_number),
            ).fetchone()[0]
            existing = conn.execute(
                "SELECT squad_id FROM squads WHERE matchday_id=? AND status='draft'", (md_id,)
            ).fetchone()
            if existing:
                return existing[0]
            members = conn.execute(
                "SELECT * FROM squad_memberships WHERE squad_id=? ORDER BY slot_number",
                (source_squad_id,),
            ).fetchall()
            valuations = []
            for member in members:
                latest = conn.execute(
                    """SELECT fp.price_hundredths_m FROM fantasy_player_prices fp
                       JOIN matchdays md ON md.matchday_id=fp.effective_matchday_id
                       WHERE fp.player_id=? AND md.season_id=? AND md.matchday_number=?""",
                    (member["player_id"], source["season_id"], next_number),
                ).fetchone()
                valuations.append(latest[0] if latest else member["valuation_price_hundredths_m"])
            squad_value = sum(valuations)
            total_value = squad_value + source["cash_hundredths_m"]
            conn.execute(
                """INSERT INTO squads(
                       matchday_id, status, formation, starting_points,
                       squad_value_hundredths_m, cash_hundredths_m, total_value_hundredths_m,
                       source_description
                   ) VALUES (?, 'draft', ?, NULL, ?, ?, ?, ?)""",
                (md_id, source["formation"], squad_value, source["cash_hundredths_m"], total_value,
                 f"Copied from {source['start_year']}_md{source['matchday_number']:02d}.json"),
            )
            draft_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            for member, valuation in zip(members, valuations):
                conn.execute(
                    """INSERT INTO squad_memberships(
                           squad_id, player_id, slot, slot_number, starred,
                           acquisition_price_hundredths_m, valuation_price_hundredths_m, recorded_points
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)""",
                    (draft_id, member["player_id"], member["slot"], member["slot_number"], member["starred"],
                     member["acquisition_price_hundredths_m"] or member["valuation_price_hundredths_m"], valuation),
                )
            conn.execute(
                """INSERT INTO squad_budget_snapshots(
                       squad_id, sequence_number, squad_value_hundredths_m,
                       cash_hundredths_m, total_value_hundredths_m, reason
                   ) VALUES (?, 1, ?, ?, ?, ?)""",
                (draft_id, squad_value, source["cash_hundredths_m"], total_value,
                 f"Matchday {next_number} draft created"),
            )
            for row in conn.execute("SELECT note_type FROM squad_notes WHERE squad_id=?", (source_squad_id,)):
                conn.execute(
                    "INSERT INTO squad_notes(squad_id, note_type, note_text) VALUES (?, ?, '')",
                    (draft_id, row[0]),
                )
            return draft_id

    def apply_transfer(self, squad_id: int, slot_number: int, incoming_player_id: int) -> int:
        with self._transaction() as conn:
            squad = conn.execute(
                """SELECT sq.*, md.season_id, md.matchday_number FROM squads sq
                   JOIN matchdays md ON md.matchday_id=sq.matchday_id WHERE sq.squad_id=?""",
                (squad_id,),
            ).fetchone()
            if squad is None or squad["status"] != "draft":
                raise RepositoryError("Transfers can only be applied to a draft")
            outgoing = conn.execute(
                "SELECT * FROM squad_memberships WHERE squad_id=? AND slot_number=?",
                (squad_id, slot_number),
            ).fetchone()
            if outgoing is None:
                raise RepositoryError("The selected squad slot does not exist")
            if conn.execute(
                "SELECT 1 FROM squad_memberships WHERE squad_id=? AND player_id=?",
                (squad_id, incoming_player_id),
            ).fetchone():
                raise RepositoryError("The replacement is already in this squad")
            incoming = conn.execute(
                """SELECT fp.price_hundredths_m,pc.club_id,pc.fantasy_position
                   FROM fantasy_player_prices fp
                   JOIN matchdays md ON md.matchday_id=fp.effective_matchday_id
                   JOIN fantasy_player_planning_contexts pc
                     ON pc.player_id=fp.player_id AND pc.effective_matchday_id=fp.effective_matchday_id
                   WHERE fp.player_id=? AND md.season_id=? AND md.matchday_number=?""",
                (incoming_player_id, squad["season_id"], squad["matchday_number"]),
            ).fetchone()
            outgoing_fact = conn.execute(
                """SELECT pc.fantasy_position FROM fantasy_player_planning_contexts pc
                   JOIN matchdays md ON md.matchday_id=pc.effective_matchday_id
                   WHERE pc.player_id=? AND md.season_id=? AND md.matchday_number=?""",
                (outgoing["player_id"], squad["season_id"], squad["matchday_number"]),
            ).fetchone()
            if incoming is None or outgoing_fact is None or incoming["fantasy_position"] != outgoing_fact[0]:
                raise RepositoryError("The replacement must have the same fantasy position")
            available = squad["cash_hundredths_m"] + outgoing["valuation_price_hundredths_m"]
            if incoming["price_hundredths_m"] > available:
                raise RepositoryError("The replacement is outside the available budget")
            same_club = conn.execute(
                """SELECT COUNT(*) FROM squad_memberships sm
                   WHERE sm.squad_id=? AND sm.squad_membership_id<>? AND EXISTS (
                     SELECT 1 FROM fantasy_player_planning_contexts pc JOIN matchdays md ON md.matchday_id=pc.effective_matchday_id
                     WHERE pc.player_id=sm.player_id AND md.season_id=?
                       AND md.matchday_number=? AND pc.club_id=?
                   )""",
                (squad_id, outgoing["squad_membership_id"], squad["season_id"], squad["matchday_number"],
                 incoming["club_id"]),
            ).fetchone()[0]
            if same_club >= 3:
                raise RepositoryError("The replacement would exceed the three-player club limit")
            sequence = conn.execute(
                "SELECT COALESCE(MAX(sequence_number), 0)+1 FROM transfers WHERE squad_id=?", (squad_id,)
            ).fetchone()[0]
            cash_after = available - incoming["price_hundredths_m"]
            conn.execute(
                """UPDATE squad_memberships SET player_id=?, acquisition_price_hundredths_m=?,
                       valuation_price_hundredths_m=?, recorded_points=NULL
                   WHERE squad_membership_id=?""",
                (incoming_player_id, incoming["price_hundredths_m"], incoming["price_hundredths_m"],
                 outgoing["squad_membership_id"]),
            )
            conn.execute(
                """INSERT INTO transfers(
                       squad_id, sequence_number, player_out_id, player_in_id,
                       sale_price_hundredths_m, purchase_price_hundredths_m,
                       cash_before_hundredths_m, cash_after_hundredths_m,
                       slot_number, outgoing_acquisition_price_hundredths_m
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (squad_id, sequence, outgoing["player_id"], incoming_player_id,
                 outgoing["valuation_price_hundredths_m"], incoming["price_hundredths_m"],
                 squad["cash_hundredths_m"], cash_after, slot_number,
                 outgoing["acquisition_price_hundredths_m"]),
            )
            transfer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            squad_value = conn.execute(
                "SELECT SUM(valuation_price_hundredths_m) FROM squad_memberships WHERE squad_id=?", (squad_id,)
            ).fetchone()[0]
            conn.execute(
                """UPDATE squads SET squad_value_hundredths_m=?, cash_hundredths_m=?,
                       total_value_hundredths_m=? WHERE squad_id=?""",
                (squad_value, cash_after, squad_value + cash_after, squad_id),
            )
            return transfer_id

    def undo_transfer(self, squad_id: int, transfer_id: int) -> None:
        with self._transaction() as conn:
            transfer = conn.execute(
                "SELECT * FROM transfers WHERE squad_id=? AND transfer_id=?",
                (squad_id, transfer_id),
            ).fetchone()
            if transfer is None:
                raise RepositoryError("The selected transfer does not exist")
            if conn.execute(
                """SELECT 1 FROM transfers WHERE squad_id=? AND slot_number=?
                   AND sequence_number>? LIMIT 1""",
                (squad_id, transfer["slot_number"], transfer["sequence_number"]),
            ).fetchone():
                raise RepositoryError("Undo the later transfer in this squad slot first")
            membership = conn.execute(
                "SELECT * FROM squad_memberships WHERE squad_id=? AND slot_number=?",
                (squad_id, transfer["slot_number"]),
            ).fetchone()
            if membership is None or membership["player_id"] != transfer["player_in_id"]:
                raise RepositoryError("The squad slot no longer matches this transfer")
            conn.execute(
                """UPDATE squad_memberships SET player_id=?,
                       acquisition_price_hundredths_m=?, valuation_price_hundredths_m=?, recorded_points=NULL
                   WHERE squad_membership_id=?""",
                (transfer["player_out_id"], transfer["outgoing_acquisition_price_hundredths_m"],
                 transfer["sale_price_hundredths_m"], membership["squad_membership_id"]),
            )
            conn.execute("DELETE FROM transfers WHERE transfer_id=?", (transfer_id,))
            squad_value = conn.execute(
                "SELECT SUM(valuation_price_hundredths_m) FROM squad_memberships WHERE squad_id=?", (squad_id,)
            ).fetchone()[0]
            cash = transfer["cash_before_hundredths_m"]
            conn.execute(
                """UPDATE squads SET squad_value_hundredths_m=?, cash_hundredths_m=?,
                       total_value_hundredths_m=? WHERE squad_id=?""",
                (squad_value, cash, squad_value + cash, squad_id),
            )
