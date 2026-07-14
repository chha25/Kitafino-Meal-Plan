"""Service registration and manual refresh handling for Speiseplan."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from .const import DOMAIN
from .kitafino.errors import error_code
from .models import MealPlanSnapshot
from .operational_logging import DEFAULT_OPERATIONAL_LOGGER

SERVICE_REFRESH = "refresh"
COORDINATOR_KEY = "coordinator"
SERVICES_REGISTERED_KEY = "_services_registered"
DEFAULT_MANUAL_REFRESH_INTERVAL = timedelta(minutes=15)

Clock = Callable[[], datetime]


class ManualRefreshThrottler:
    """Track accepted manual refresh attempts per config entry."""

    def __init__(
        self,
        *,
        interval: timedelta = DEFAULT_MANUAL_REFRESH_INTERVAL,
    ) -> None:
        """Create a deterministic manual refresh throttler."""
        self.interval = interval
        self._last_refresh_by_key: dict[str, datetime] = {}

    def check_and_record(self, key: str, now: datetime) -> tuple[bool, int]:
        """Return whether refresh is allowed and seconds until the next slot."""
        last_refresh = self._last_refresh_by_key.get(key)
        if last_refresh is None:
            self._last_refresh_by_key[key] = now
            return True, 0

        elapsed = now - last_refresh
        if elapsed >= self.interval:
            self._last_refresh_by_key[key] = now
            return True, 0

        remaining = self.interval - elapsed
        return False, max(1, int(remaining.total_seconds()))


_THROTTLER = ManualRefreshThrottler()


def _utc_now() -> datetime:
    """Return the current UTC time for service throttling."""
    return datetime.now(tz=UTC)


async def async_setup_services(
    hass: Any,
    *,
    throttler: ManualRefreshThrottler | None = None,
    clock: Clock = _utc_now,
) -> None:
    """Register Speiseplan services."""
    domain_data = getattr(hass, "data", {}).setdefault(DOMAIN, {})
    if domain_data.get(SERVICES_REGISTERED_KEY):
        return

    async def handle_refresh(call: Any) -> dict[str, Any]:
        data = getattr(call, "data", {}) or {}
        entry_id = data.get("entry_id")
        if not isinstance(entry_id, str):
            entry_id = None

        return await async_handle_manual_refresh(
            hass,
            entry_id=entry_id,
            throttler=throttler or _THROTTLER,
            now=clock(),
        )

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, handle_refresh)
    domain_data[SERVICES_REGISTERED_KEY] = True


async def async_handle_manual_refresh(
    hass: Any,
    *,
    entry_id: str | None = None,
    throttler: ManualRefreshThrottler | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh configured coordinators while enforcing manual throttling."""
    throttler = throttler or _THROTTLER
    now = now or _utc_now()
    coordinators = _find_coordinators(hass, entry_id=entry_id)
    throttle_key = entry_id or ",".join(entry for entry, _ in coordinators) or "global"
    allowed, seconds_until_allowed = throttler.check_and_record(throttle_key, now)
    if not allowed:
        return _manual_refresh_result(
            refreshed=0,
            throttled=True,
            seconds_until_allowed=seconds_until_allowed,
            snapshots=[
                snapshot
                for _, coordinator in coordinators
                if (snapshot := getattr(coordinator, "snapshot", None)) is not None
            ],
            errors=[],
        )

    snapshots: list[MealPlanSnapshot] = []
    errors: list[dict[str, str]] = []
    refreshed = 0
    for coordinator_entry_id, coordinator in coordinators:
        try:
            snapshot = await coordinator.async_refresh(phase="manual_refresh")
        except Exception as err:
            failure_code = error_code(err)
            DEFAULT_OPERATIONAL_LOGGER.log_failure(
                entry_id=coordinator_entry_id,
                phase="manual_refresh",
                failure_class=failure_code,
            )
            errors.append(
                {
                    "entry_id": coordinator_entry_id,
                    "error": failure_code,
                }
            )
            continue

        refreshed += 1
        snapshots.append(snapshot)

    return _manual_refresh_result(
        refreshed=refreshed,
        throttled=False,
        seconds_until_allowed=0,
        snapshots=snapshots,
        errors=errors,
    )


def _find_coordinators(hass: Any, *, entry_id: str | None) -> list[tuple[str, Any]]:
    """Return configured coordinators from Home Assistant domain data."""
    domain_data = getattr(hass, "data", {}).get(DOMAIN, {})
    if not isinstance(domain_data, dict):
        return []

    entry_items = (
        [(entry_id, domain_data.get(entry_id))]
        if entry_id is not None
        else list(domain_data.items())
    )
    coordinators: list[tuple[str, Any]] = []
    for current_entry_id, entry_data in entry_items:
        if current_entry_id == SERVICES_REGISTERED_KEY:
            continue
        if not isinstance(current_entry_id, str) or not isinstance(entry_data, dict):
            continue
        coordinator = entry_data.get(COORDINATOR_KEY)
        if coordinator is not None:
            coordinators.append((current_entry_id, coordinator))

    return coordinators


def _manual_refresh_result(
    *,
    refreshed: int,
    throttled: bool,
    seconds_until_allowed: int,
    snapshots: list[MealPlanSnapshot],
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    """Build a sanitized manual refresh result dictionary."""
    return {
        "refreshed": refreshed,
        "throttled": throttled,
        "seconds_until_allowed": seconds_until_allowed,
        "snapshots": [snapshot.to_dict() for snapshot in snapshots],
        "errors": errors,
    }
