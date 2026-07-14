"""Coordinator refresh and stale-state behavior for Speiseplan."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace

from .kitafino.errors import error_code
from .models import Child, HealthStatus, MealEntry, MealPlanSnapshot
from .operational_logging import (
    DEFAULT_OPERATIONAL_LOGGER,
    RedactedOperationalLogger,
)
from .storage import SnapshotStore

FetchSource = Callable[[], Awaitable[str]]
ParseSource = Callable[[str], list[MealEntry]]
Clock = Callable[[], str]


class SpeiseplanDataUpdateCoordinator:
    """Coordinator core for refresh, stale policy, and sanitized snapshot cache."""

    def __init__(
        self,
        *,
        fetch_source: FetchSource,
        parse_source: Callable[..., list[MealEntry]],
        store: SnapshotStore | None = None,
        clock: Clock,
        children: list[Child] | None = None,
        parser_version: str | None = None,
        shared_source: bool = True,
        config_entry_id: str | None = None,
        operational_logger: RedactedOperationalLogger | None = None,
    ) -> None:
        """Create a coordinator core with injected I/O seams."""
        self.fetch_source = fetch_source
        self.parse_source = parse_source
        self.store = store or SnapshotStore()
        self.clock = clock
        self.children = list(children or [])
        self.parser_version = parser_version
        self.shared_source = shared_source
        self.config_entry_id = config_entry_id
        self.operational_logger = operational_logger or DEFAULT_OPERATIONAL_LOGGER
        self.snapshot: MealPlanSnapshot | None = None

    async def async_load_cached_snapshot(self) -> MealPlanSnapshot | None:
        """Load the last successful sanitized snapshot into coordinator state."""
        self.snapshot = await self.store.async_load()
        return self.snapshot

    async def async_refresh(self, *, phase: str = "refresh") -> MealPlanSnapshot:
        """Refresh source data and apply stale policy on failure."""
        fetched_at = self.clock()
        try:
            source = await self.fetch_source()
            entries = self.parse_source(source, fetched_at=fetched_at)
        except Exception as err:
            failure_code = error_code(err)
            self.operational_logger.log_failure(
                entry_id=self.config_entry_id,
                phase=phase,
                failure_class=failure_code,
            )
            snapshot = await self._snapshot_for_failure(err, fetched_at=fetched_at)
            self.snapshot = snapshot
            return snapshot

        snapshot = MealPlanSnapshot(
            health=HealthStatus(
                state="ok",
                last_error=None,
                last_successful_update=fetched_at,
                fetched_at=fetched_at,
            ),
            children=self.children,
            entries=entries,
            fetched_at=fetched_at,
            last_successful_update=fetched_at,
            shared_source=self.shared_source,
            parser_version=self.parser_version,
        )
        self.snapshot = snapshot
        await self.store.async_save(snapshot)
        return snapshot

    async def _snapshot_for_failure(
        self,
        error: BaseException,
        *,
        fetched_at: str,
    ) -> MealPlanSnapshot:
        """Build a failure snapshot using prior successful data when available."""
        failure_code = error_code(error)
        prior = self.snapshot or await self.store.async_load()
        if prior is None:
            return MealPlanSnapshot.empty(
                fetched_at=fetched_at,
                health_state=failure_code,
                last_error=failure_code,
            )

        return MealPlanSnapshot(
            health=HealthStatus(
                state="stale",
                last_error=failure_code,
                last_successful_update=prior.last_successful_update,
                fetched_at=fetched_at,
            ),
            children=prior.children,
            entries=[_mark_entry_stale(entry) for entry in prior.entries],
            fetched_at=fetched_at,
            last_successful_update=prior.last_successful_update,
            shared_source=prior.shared_source,
            parser_version=prior.parser_version,
        )


def _mark_entry_stale(entry: MealEntry) -> MealEntry:
    """Return a stale copy of a meal entry."""
    return replace(entry, stale=True)
