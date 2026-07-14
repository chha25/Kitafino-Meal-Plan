"""Tests for manual refresh service behavior."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import logging
from typing import Any

import custom_components.speiseplan.services as services_module
from custom_components.speiseplan.const import DOMAIN, FORBIDDEN_SECRET_MARKERS
from custom_components.speiseplan import async_setup_entry
from custom_components.speiseplan.kitafino.errors import KitafinoCannotConnectError
from custom_components.speiseplan.models import HealthStatus, MealEntry, MealPlanSnapshot
from custom_components.speiseplan.operational_logging import RedactedOperationalLogger
from custom_components.speiseplan.services import (
    COORDINATOR_KEY,
    SERVICE_REFRESH,
    ManualRefreshThrottler,
    async_handle_manual_refresh,
    async_setup_services,
)


FETCHED_AT = "2026-07-12T06:00:00+02:00"
SECOND_FETCHED_AT = "2026-07-12T07:00:00+02:00"


class FakeServices:
    def __init__(self) -> None:
        self.registered: dict[tuple[str, str], Any] = {}
        self.register_calls = 0

    def async_register(self, domain: str, service: str, handler: Any) -> None:
        self.register_calls += 1
        self.registered[(domain, service)] = handler


class FakeHass:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.services = FakeServices()


class FakeEntry:
    entry_id = "entry-1"


class FakeCoordinator:
    def __init__(self, *snapshots: MealPlanSnapshot) -> None:
        self.snapshots = list(snapshots)
        self.calls = 0
        self.snapshot: MealPlanSnapshot | None = None

    async def async_refresh(self, *, phase: str = "refresh") -> MealPlanSnapshot:
        self.calls += 1
        if not self.snapshots:
            raise AssertionError("No snapshot queued")
        self.snapshot = self.snapshots.pop(0)
        return self.snapshot


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


def _entry(*, stale: bool = False) -> MealEntry:
    return MealEntry(
        child_key="shared",
        week_kind="current",
        iso_year=2026,
        iso_week=29,
        weekday="monday",
        meal_text="Pasta",
        source_date=None,
        fetched_at=FETCHED_AT,
        stale=stale,
        shared_source=True,
    )


def _ok_snapshot() -> MealPlanSnapshot:
    return MealPlanSnapshot(
        health=HealthStatus(
            state="ok",
            fetched_at=FETCHED_AT,
            last_successful_update=FETCHED_AT,
        ),
        entries=[_entry()],
        fetched_at=FETCHED_AT,
        last_successful_update=FETCHED_AT,
        shared_source=True,
        parser_version="kitafino-html-v1",
    )


def _stale_snapshot() -> MealPlanSnapshot:
    return MealPlanSnapshot(
        health=HealthStatus(
            state="stale",
            last_error="network_error",
            fetched_at=SECOND_FETCHED_AT,
            last_successful_update=FETCHED_AT,
        ),
        entries=[_entry(stale=True)],
        fetched_at=SECOND_FETCHED_AT,
        last_successful_update=FETCHED_AT,
        shared_source=True,
        parser_version="kitafino-html-v1",
    )


def _hass_with_coordinator(coordinator: FakeCoordinator) -> FakeHass:
    hass = FakeHass()
    hass.data[DOMAIN] = {
        "entry-1": {
            COORDINATOR_KEY: coordinator,
        }
    }
    return hass


def test_setup_registers_refresh_service() -> None:
    hass = FakeHass()

    _run(async_setup_services(hass))

    assert (DOMAIN, SERVICE_REFRESH) in hass.services.registered


def test_config_entry_setup_registers_refresh_service() -> None:
    hass = FakeHass()

    result = _run(async_setup_entry(hass, FakeEntry()))

    assert result is True
    assert (DOMAIN, SERVICE_REFRESH) in hass.services.registered


def test_service_registration_is_idempotent() -> None:
    hass = FakeHass()

    _run(async_setup_services(hass))
    _run(async_setup_services(hass))

    assert hass.services.register_calls == 1


def test_manual_refresh_delegates_to_coordinator_and_returns_sanitized_snapshot() -> None:
    coordinator = FakeCoordinator(_ok_snapshot())
    hass = _hass_with_coordinator(coordinator)
    throttler = ManualRefreshThrottler()

    result = _run(
        async_handle_manual_refresh(
            hass,
            throttler=throttler,
            now=datetime(2026, 7, 12, 6, 0, tzinfo=UTC),
        )
    )

    assert coordinator.calls == 1
    assert result["refreshed"] == 1
    assert result["throttled"] is False
    assert result["snapshots"] == [_ok_snapshot().to_dict()]


def test_manual_refresh_ignores_internal_domain_data_keys() -> None:
    coordinator = FakeCoordinator(_ok_snapshot())
    hass = _hass_with_coordinator(coordinator)
    hass.data[DOMAIN]["_services_registered"] = True

    result = _run(
        async_handle_manual_refresh(
            hass,
            throttler=ManualRefreshThrottler(),
            now=datetime(2026, 7, 12, 6, 0, tzinfo=UTC),
        )
    )

    assert result["refreshed"] == 1
    assert result["errors"] == []


def test_manual_refresh_uses_same_failure_snapshot_policy_as_coordinator() -> None:
    coordinator = FakeCoordinator(_stale_snapshot())
    hass = _hass_with_coordinator(coordinator)

    result = _run(
        async_handle_manual_refresh(
            hass,
            throttler=ManualRefreshThrottler(),
            now=datetime(2026, 7, 12, 6, 0, tzinfo=UTC),
        )
    )

    assert coordinator.calls == 1
    assert result["snapshots"][0]["health"]["state"] == "stale"
    assert result["snapshots"][0]["health"]["last_error"] == "network_error"
    assert result["snapshots"][0]["entries"][0]["stale"] is True


def test_manual_refresh_throttles_repeated_calls_inside_15_minutes() -> None:
    coordinator = FakeCoordinator(_ok_snapshot(), _ok_snapshot())
    hass = _hass_with_coordinator(coordinator)
    throttler = ManualRefreshThrottler()

    first = _run(
        async_handle_manual_refresh(
            hass,
            throttler=throttler,
            now=datetime(2026, 7, 12, 6, 0, tzinfo=UTC),
        )
    )
    second = _run(
        async_handle_manual_refresh(
            hass,
            throttler=throttler,
            now=datetime(2026, 7, 12, 6, 14, 59, tzinfo=UTC),
        )
    )
    third = _run(
        async_handle_manual_refresh(
            hass,
            throttler=throttler,
            now=datetime(2026, 7, 12, 6, 15, tzinfo=UTC),
        )
    )

    assert first["throttled"] is False
    assert second["throttled"] is True
    assert second["seconds_until_allowed"] == 1
    assert third["throttled"] is False
    assert coordinator.calls == 2


def test_throttled_refresh_does_not_hide_existing_snapshot() -> None:
    coordinator = FakeCoordinator(_ok_snapshot())
    hass = _hass_with_coordinator(coordinator)
    throttler = ManualRefreshThrottler()
    first_at = datetime(2026, 7, 12, 6, 0, tzinfo=UTC)

    _run(async_handle_manual_refresh(hass, throttler=throttler, now=first_at))
    result = _run(
        async_handle_manual_refresh(
            hass,
            throttler=throttler,
            now=first_at + timedelta(minutes=1),
        )
    )

    assert result["throttled"] is True
    assert result["snapshots"] == [_ok_snapshot().to_dict()]
    assert coordinator.calls == 1


def test_manual_refresh_result_contains_no_secret_markers() -> None:
    coordinator = FakeCoordinator(_ok_snapshot())
    hass = _hass_with_coordinator(coordinator)

    result = _run(
        async_handle_manual_refresh(
            hass,
            throttler=ManualRefreshThrottler(),
            now=datetime(2026, 7, 12, 6, 0, tzinfo=UTC),
        )
    )
    serialized = json.dumps(result, sort_keys=True)

    for marker in FORBIDDEN_SECRET_MARKERS:
        assert marker not in serialized
    assert "username" not in serialized.lower()
    assert "password" not in serialized.lower()
    assert "cookie" not in serialized.lower()
    assert "raw_html" not in serialized.lower()
    assert "account_id" not in serialized.lower()


def test_manual_refresh_maps_unexpected_coordinator_exception_safely() -> None:
    class RaisingCoordinator:
        snapshot = None
        calls = 0

        async def async_refresh(self, *, phase: str = "refresh") -> MealPlanSnapshot:
            self.calls += 1
            raise KitafinoCannotConnectError("RAW_KITAFINO_HTML_CAPTURE")

    coordinator = RaisingCoordinator()
    hass = _hass_with_coordinator(coordinator)  # type: ignore[arg-type]

    result = _run(
        async_handle_manual_refresh(
            hass,
            throttler=ManualRefreshThrottler(),
            now=datetime(2026, 7, 12, 6, 0, tzinfo=UTC),
        )
    )

    assert result["refreshed"] == 0
    assert result["errors"] == [{"entry_id": "entry-1", "error": "network_error"}]
    assert "RAW_KITAFINO_HTML_CAPTURE" not in json.dumps(result, sort_keys=True)


def test_manual_refresh_logs_unexpected_coordinator_exception_safely(
    caplog: object,
    monkeypatch: object,
) -> None:
    class RaisingCoordinator:
        snapshot = None

        async def async_refresh(self, *, phase: str = "refresh") -> MealPlanSnapshot:
            raise KitafinoCannotConnectError(
                "RAW_KITAFINO_HTML_CAPTURE parent@example.test super-secret",
            )

    logger = logging.getLogger("speiseplan.test.services.logging")
    monkeypatch.setattr(  # type: ignore[attr-defined]
        services_module,
        "DEFAULT_OPERATIONAL_LOGGER",
        RedactedOperationalLogger(logger=logger),
    )
    hass = _hass_with_coordinator(RaisingCoordinator())  # type: ignore[arg-type]

    with caplog.at_level(logging.WARNING, logger=logger.name):  # type: ignore[attr-defined]
        result = _run(
            async_handle_manual_refresh(
                hass,
                throttler=ManualRefreshThrottler(),
                now=datetime(2026, 7, 12, 6, 0, tzinfo=UTC),
            )
        )

    text = caplog.text  # type: ignore[attr-defined]
    assert result["errors"] == [{"entry_id": "entry-1", "error": "network_error"}]
    assert "entry_id=entry-1" in text
    assert "phase=manual_refresh" in text
    assert "failure_class=network_error" in text
    assert "RAW_KITAFINO_HTML_CAPTURE" not in text
    assert "parent@example.test" not in text
    assert "super-secret" not in text
