"""Sanitized snapshot storage for Speiseplan."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

from .models import MealPlanSnapshot


class SnapshotStore:
    """Store sanitized last-successful meal-plan snapshots."""

    def __init__(self, raw_data: dict[str, Any] | None = None) -> None:
        """Create an in-memory store facade for sanitized snapshot data."""
        self.raw_data = deepcopy(raw_data) if raw_data is not None else None

    async def async_save(self, snapshot: MealPlanSnapshot) -> None:
        """Persist a sanitized snapshot dictionary."""
        self.raw_data = deepcopy(replace(snapshot, children=[]).to_dict())

    async def async_load(self) -> MealPlanSnapshot | None:
        """Load a sanitized snapshot, if present."""
        if self.raw_data is None:
            return None
        return MealPlanSnapshot.from_dict(deepcopy(self.raw_data))
