from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class DatabaseConfig:
    """SQLite location shared by the importer, repository, app, and tests."""

    path: Path = PROJECT_ROOT / "data" / "fantasy_bundesliga.sqlite"

    def resolved_path(self) -> Path:
        return self.path.expanduser().resolve()


DEFAULT_DATABASE_CONFIG = DatabaseConfig()
