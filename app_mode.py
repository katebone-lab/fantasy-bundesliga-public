from __future__ import annotations

import os
from dataclasses import dataclass


MODE_ENVIRONMENT_VARIABLE = "FANTASY_BUNDESLIGA_MODE"


@dataclass(frozen=True)
class ApplicationMode:
    name: str

    @property
    def allows_writes(self) -> bool:
        return self.name == "local"

    @property
    def is_public(self) -> bool:
        return self.name == "public"


def get_application_mode() -> ApplicationMode:
    value = os.environ.get(MODE_ENVIRONMENT_VARIABLE, "local").strip().lower()
    if value not in {"local", "public"}:
        raise ValueError(
            f"{MODE_ENVIRONMENT_VARIABLE} must be 'local' or 'public', not {value!r}"
        )
    return ApplicationMode(value)
