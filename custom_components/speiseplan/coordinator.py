"""Coordinator refresh and stale-state behavior for Speiseplan."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta

from .kitafino.errors import (
    KitafinoCannotConnectError,
    KitafinoInvalidAuthError,
    error_code,
)
from .models import (
    WEEKDAYS,
    WEEK_KINDS,
    Child,
    HealthStatus,
    MealEntry,
    MealPlanSnapshot,
)
from .operational_logging import (
    DEFAULT_OPERATIONAL_LOGGER,
    RedactedOperationalLogger,
)
from .storage import SnapshotStore

FetchSource = Callable[[], Awaitable[str]]
ParseSource = Callable[[str], list[MealEntry]]
Clock = Callable[[], str]
SnapshotUpdateCallback = Callable[[MealPlanSnapshot], Awaitable[None]]


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
        child_slug: str | None = None,
        operational_logger: RedactedOperationalLogger | None = None,
        snapshot_update_callback: SnapshotUpdateCallback | None = None,
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
        self.child_slug = child_slug
        self.operational_logger = operational_logger or DEFAULT_OPERATIONAL_LOGGER
        self.snapshot_update_callback = snapshot_update_callback
        self.snapshot: MealPlanSnapshot | None = None

    async def async_load_cached_snapshot(self) -> MealPlanSnapshot | None:
        """Load the last successful sanitized snapshot into coordinator state."""
        cached = await self.store.async_load()
        self.snapshot = self._owned_cached_snapshot(cached)
        return self.snapshot

    async def async_refresh(self, *, phase: str = "refresh") -> MealPlanSnapshot:
        """Refresh source data and apply stale policy on failure."""
        fetched_at = self.clock()
        try:
            source = await self.fetch_source()
            entries = self.parse_source(source, fetched_at=fetched_at)
        except Exception as err:
            failure_code = error_code(err)
            diagnostics = (
                {
                    "request_stage": err.stage,
                    "failure_reason": err.reason,
                    "http_status": err.http_status,
                }
                if isinstance(
                    err,
                    (KitafinoCannotConnectError, KitafinoInvalidAuthError),
                )
                else {}
            )
            self.operational_logger.log_failure(
                entry_id=self.config_entry_id,
                phase=phase,
                failure_class=failure_code,
                **diagnostics,
            )
            snapshot = await self._snapshot_for_failure(err, fetched_at=fetched_at)
            self.snapshot = snapshot
            await self._async_notify_snapshot_update(snapshot)
            return snapshot

        fresh_entries = [self._stamp_fresh_owner(entry) for entry in entries]
        merged_entries = await self._merged_successful_entries(
            fresh_entries,
            fetched_at=fetched_at,
        )
        snapshot = MealPlanSnapshot(
            health=HealthStatus(
                state="ok",
                last_error=None,
                last_successful_update=fetched_at,
                fetched_at=fetched_at,
            ),
            children=self.children,
            entries=merged_entries,
            fetched_at=fetched_at,
            last_successful_update=fetched_at,
            shared_source=self.shared_source,
            parser_version=self.parser_version,
        )
        self.snapshot = snapshot
        await self.store.async_save(snapshot)
        await self._async_notify_snapshot_update(snapshot)
        return snapshot

    async def _merged_successful_entries(
        self,
        fresh_entries: list[MealEntry],
        *,
        fetched_at: str,
    ) -> list[MealEntry]:
        """Merge fresh output with the valid prior snapshot by meal identity."""
        prior = self.snapshot
        if prior is None:
            try:
                prior = await self.store.async_load()
            except (TypeError, ValueError):
                prior = None
        prior = self._owned_cached_snapshot(prior)
        allowed_scopes = {_entry_scope(entry) for entry in fresh_entries}
        if not allowed_scopes:
            allowed_scopes = self._empty_parse_scopes(fetched_at)
        merged = {
            _entry_identity(entry): _mark_entry_stale(entry)
            for entry in (prior.entries if prior is not None else [])
            if _entry_scope(entry) in allowed_scopes
        }
        merged.update({_entry_identity(entry): entry for entry in fresh_entries})
        return sorted(merged.values(), key=_entry_sort_key)

    def _empty_parse_scopes(
        self,
        fetched_at: str,
    ) -> set[tuple[str, bool, int, int, str]]:
        """Return this owner's current and next ISO-week scopes at refresh time."""
        try:
            fetched_date = datetime.fromisoformat(fetched_at).date()
        except ValueError:
            return set()
        owner = self.child_slug or "shared"
        scopes = set()
        for week_kind, date_value in (
            ("current", fetched_date),
            ("next", fetched_date + timedelta(days=7)),
        ):
            iso_year, iso_week, _ = date_value.isocalendar()
            scopes.add((owner, self.shared_source, iso_year, iso_week, week_kind))
        return scopes

    async def _async_notify_snapshot_update(
        self,
        snapshot: MealPlanSnapshot,
    ) -> None:
        """Notify an optional projection hook after snapshot state changes."""
        if self.snapshot_update_callback is not None:
            await self.snapshot_update_callback(snapshot)

    async def _snapshot_for_failure(
        self,
        error: BaseException,
        *,
        fetched_at: str,
    ) -> MealPlanSnapshot:
        """Build a failure snapshot using prior successful data when available."""
        failure_code = error_code(error)
        prior = self.snapshot or await self.store.async_load()
        prior = self._owned_cached_snapshot(prior)
        if prior is None:
            return MealPlanSnapshot(
                health=HealthStatus(
                    state=failure_code,
                    last_error=failure_code,
                    fetched_at=fetched_at,
                ),
                children=self.children,
                fetched_at=fetched_at,
                shared_source=self.shared_source,
                parser_version=self.parser_version,
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

    def _stamp_fresh_owner(self, entry: MealEntry) -> MealEntry:
        """Stamp only freshly parsed output with this authenticated owner."""
        if self.child_slug is None:
            return replace(entry, stale=False)
        return replace(
            entry,
            child_key=self.child_slug,
            stale=False,
            shared_source=False,
        )

    def _owned_cached_snapshot(
        self,
        snapshot: MealPlanSnapshot | None,
    ) -> MealPlanSnapshot | None:
        """Reject shared or foreign cached data for child-owned coordinators."""
        if snapshot is None:
            return None
        if self.child_slug is None:
            if not snapshot.shared_source or any(
                not entry.shared_source for entry in snapshot.entries
            ):
                return None
            return snapshot
        if not snapshot.entries:
            if snapshot.shared_source or snapshot.children != self.children:
                return None
            return snapshot
        if (
            snapshot.shared_source
            or any(
                entry.shared_source or entry.child_key != self.child_slug
                for entry in snapshot.entries
            )
        ):
            return None
        return replace(
            snapshot,
            children=self.children,
            shared_source=False,
        )


def _mark_entry_stale(entry: MealEntry) -> MealEntry:
    """Return a stale copy of a meal entry."""
    return replace(entry, stale=True)


def _entry_scope(entry: MealEntry) -> tuple[str, bool, int, int, str]:
    """Return the owner and week dimensions shared by merge candidates."""
    return (
        entry.child_key,
        entry.shared_source,
        entry.iso_year,
        entry.iso_week,
        entry.week_kind,
    )


def _entry_identity(entry: MealEntry) -> tuple[str, bool, int, int, str, str]:
    """Return the complete identity for one weekday meal."""
    return (*_entry_scope(entry), entry.weekday)


def _entry_sort_key(entry: MealEntry) -> tuple[int, int, int, str, bool, int]:
    """Sort entries deterministically by week kind and canonical weekday."""
    return (
        WEEK_KINDS.index(entry.week_kind),
        entry.iso_year,
        entry.iso_week,
        entry.child_key,
        entry.shared_source,
        WEEKDAYS.index(entry.weekday),
    )
