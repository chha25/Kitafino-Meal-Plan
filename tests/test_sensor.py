"""Tests for Speiseplan shared current week meal sensors."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from custom_components.speiseplan import PLATFORMS
from custom_components.speiseplan import async_setup_entry as async_setup_integration_entry
from custom_components.speiseplan.const import (
    DOMAIN,
    FORBIDDEN_SECRET_MARKERS,
    SHARED_CURRENT_ENTITY_ID_TEMPLATE,
    WEEKDAYS,
)
from custom_components.speiseplan.models import (
    Child,
    HealthStatus,
    MealEntry,
    MealPlanSnapshot,
)
from custom_components.speiseplan.sensor import (
    HEALTH_ENTITY_ID,
    SpeiseplanChildCurrentMealSensor,
    SpeiseplanHealthSensor,
    SpeiseplanSharedCurrentMealSensor,
    async_setup_entry,
    build_shared_current_meal_sensors,
)
from custom_components.speiseplan.services import COORDINATOR_KEY


FETCHED_AT = "2026-07-12T06:00:00+02:00"


class FakeCoordinator:
    def __init__(
        self,
        snapshot: MealPlanSnapshot | None,
        *,
        child_slug: str | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.child_slug = child_slug


class FakeEntry:
    entry_id = "entry-1"


class FakeHass:
    def __init__(self, coordinator: FakeCoordinator) -> None:
        self.data: dict[str, Any] = {
            DOMAIN: {
                "entry-1": {
                    COORDINATOR_KEY: coordinator,
                }
            }
        }


class FakeConfigEntries:
    def __init__(self) -> None:
        self.forwarded: list[tuple[Any, tuple[str, ...]]] = []

    async def async_forward_entry_setups(
        self,
        entry: Any,
        platforms: tuple[str, ...],
    ) -> None:
        self.forwarded.append((entry, platforms))


class FakeServices:
    def async_register(self, domain: str, service: str, handler: Any) -> None:
        return None


class FakeSetupHass(FakeHass):
    def __init__(self, coordinator: FakeCoordinator) -> None:
        super().__init__(coordinator)
        self.config_entries = FakeConfigEntries()
        self.services = FakeServices()


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


def _entry(weekday: str, meal_text: str, *, stale: bool = False) -> MealEntry:
    return MealEntry(
        child_key="shared",
        week_kind="current",
        iso_year=2026,
        iso_week=29,
        weekday=weekday,
        meal_text=meal_text,
        source_date="2026-07-13",
        fetched_at=FETCHED_AT,
        stale=stale,
        shared_source=True,
    )


def _next_week_entry(weekday: str, meal_text: str) -> MealEntry:
    return MealEntry(
        child_key="shared",
        week_kind="next",
        iso_year=2026,
        iso_week=30,
        weekday=weekday,
        meal_text=meal_text,
        source_date=None,
        fetched_at=FETCHED_AT,
        stale=False,
        shared_source=True,
    )


def _snapshot(
    *entries: MealEntry,
    children: list[Child] | None = None,
    health_state: str = "ok",
    last_error: str | None = None,
) -> MealPlanSnapshot:
    return MealPlanSnapshot(
        health=HealthStatus(
            state=health_state,
            last_error=last_error,
            fetched_at=FETCHED_AT,
            last_successful_update=FETCHED_AT,
        ),
        children=list(children or []),
        entries=list(entries),
        fetched_at=FETCHED_AT,
        last_successful_update=FETCHED_AT,
        shared_source=True,
        parser_version="kitafino-html-v1",
    )


def test_shared_current_entity_id_template_is_stable() -> None:
    assert "monday" in WEEKDAYS
    assert (
        SHARED_CURRENT_ENTITY_ID_TEMPLATE.format(weekday="monday")
        == "sensor.speiseplan_shared_current_monday"
    )


def test_builds_one_shared_current_sensor_per_weekday() -> None:
    coordinator = FakeCoordinator(_snapshot(_entry("monday", "Pasta")))

    sensors = build_shared_current_meal_sensors(coordinator)

    assert len(sensors) == 5
    assert [sensor.weekday for sensor in sensors] == list(WEEKDAYS)
    assert [sensor.entity_id for sensor in sensors] == [
        SHARED_CURRENT_ENTITY_ID_TEMPLATE.format(weekday=weekday)
        for weekday in WEEKDAYS
    ]
    assert all("Shared Current Week" in sensor.name for sensor in sensors)


def test_configured_child_labels_do_not_create_child_specific_sensors() -> None:
    coordinator = FakeCoordinator(
        _snapshot(
            _entry("monday", "Pasta"),
            children=[
                Child(child_key="kind_1", display_name="Kind 1"),
                Child(child_key="kind_2", display_name="Kind 2"),
            ],
        )
    )

    sensors = build_shared_current_meal_sensors(coordinator)

    assert len(sensors) == 5
    assert all("Shared Current Week" in sensor.name for sensor in sensors)
    assert all("Kind 1" not in sensor.name for sensor in sensors)
    assert all("Kind 2" not in sensor.name for sensor in sensors)


def test_next_week_entries_do_not_create_extra_sensors_or_replace_current_week() -> None:
    coordinator = FakeCoordinator(
        _snapshot(
            _entry("monday", "Current pasta"),
            _next_week_entry("monday", "Future soup"),
        )
    )

    sensors = build_shared_current_meal_sensors(coordinator)
    monday = sensors[0]

    assert len(sensors) == 5
    assert monday.entity_id == "sensor.speiseplan_shared_current_monday"
    assert monday.native_value == "Current pasta"
    assert monday.extra_state_attributes["week_kind"] == "current"


def test_shared_current_sensor_state_and_attributes_from_snapshot() -> None:
    sensor = SpeiseplanSharedCurrentMealSensor(
        coordinator=FakeCoordinator(_snapshot(_entry("monday", "Pasta", stale=True))),
        weekday="monday",
    )

    assert sensor.native_value == "Pasta"
    assert sensor.available is True
    assert sensor.extra_state_attributes == {
        "child_key": "shared",
        "week_kind": "current",
        "iso_year": 2026,
        "iso_week": 29,
        "weekday": "monday",
        "source_date": "2026-07-13",
        "last_successful_update": FETCHED_AT,
        "stale": True,
        "shared_source": True,
    }


def test_missing_weekday_entry_is_unavailable() -> None:
    sensor = SpeiseplanSharedCurrentMealSensor(
        coordinator=FakeCoordinator(_snapshot(_entry("monday", "Pasta"))),
        weekday="tuesday",
    )

    assert sensor.native_value is None
    assert sensor.available is False
    assert sensor.extra_state_attributes == {
        "weekday": "tuesday",
        "week_kind": "current",
        "shared_source": True,
        "stale": None,
        "last_successful_update": FETCHED_AT,
    }


def test_empty_child_sensor_remains_child_owned_and_non_shared() -> None:
    sensor = SpeiseplanChildCurrentMealSensor(
        coordinator=FakeCoordinator(None, child_slug="lena"),
        weekday="tuesday",
        child_slug="lena",
    )

    assert sensor.available is False
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {
        "weekday": "tuesday",
        "week_kind": "current",
        "shared_source": False,
        "stale": None,
        "last_successful_update": None,
        "child_key": "lena",
    }


def test_sensor_setup_uses_coordinator_from_hass_data() -> None:
    added: list[Any] = []
    coordinator = FakeCoordinator(_snapshot(_entry("monday", "Pasta")))
    hass = FakeHass(coordinator)

    _run(async_setup_entry(hass, FakeEntry(), added.extend))

    assert len(added) == 6
    assert isinstance(added[0], SpeiseplanHealthSensor)
    assert all(
        isinstance(sensor, SpeiseplanSharedCurrentMealSensor) for sensor in added[1:]
    )


def test_integration_setup_forwards_sensor_platform() -> None:
    hass = FakeSetupHass(FakeCoordinator(_snapshot(_entry("monday", "Pasta"))))
    entry = FakeEntry()

    result = _run(async_setup_integration_entry(hass, entry))

    assert result is True
    assert PLATFORMS == ("sensor",)
    assert hass.config_entries.forwarded == [(entry, ("sensor",))]


def test_health_sensor_reports_snapshot_health_and_freshness_attributes() -> None:
    sensor = SpeiseplanHealthSensor(
        coordinator=FakeCoordinator(
            _snapshot(
                _entry("monday", "Pasta"),
                children=[Child(child_key="kind_1", display_name="Kind 1")],
            )
        )
    )

    assert sensor.entity_id == HEALTH_ENTITY_ID
    assert sensor.unique_id == "speiseplan_health"
    assert sensor.name == "Speiseplan Health"
    assert sensor.native_value == "ok"
    assert sensor.available is True
    assert sensor.extra_state_attributes == {
        "last_successful_update": FETCHED_AT,
        "last_error": None,
        "configured_child_count": 1,
        "shared_source": True,
        "parser_version": "kitafino-html-v1",
        "fetched_at": FETCHED_AT,
    }


def test_sensor_entity_ids_can_be_assigned_by_home_assistant() -> None:
    health = SpeiseplanHealthSensor(
        coordinator=FakeCoordinator(_snapshot(_entry("monday", "Pasta"))),
    )
    meal = SpeiseplanSharedCurrentMealSensor(
        coordinator=FakeCoordinator(_snapshot(_entry("monday", "Pasta"))),
        weekday="monday",
    )

    health.entity_id = "sensor.kitafino_health"
    meal.entity_id = "sensor.kitafino_monday"

    assert health.entity_id == "sensor.kitafino_health"
    assert meal.entity_id == "sensor.kitafino_monday"


def test_health_sensor_reports_stale_status_with_last_error() -> None:
    sensor = SpeiseplanHealthSensor(
        coordinator=FakeCoordinator(
            _snapshot(
                _entry("monday", "Pasta", stale=True),
                health_state="stale",
                last_error="network_error",
            )
        )
    )

    assert sensor.native_value == "stale"
    assert sensor.extra_state_attributes["last_error"] == "network_error"


def test_health_sensor_without_snapshot_is_unavailable() -> None:
    sensor = SpeiseplanHealthSensor(coordinator=FakeCoordinator(None))

    assert sensor.native_value is None
    assert sensor.available is False
    assert sensor.extra_state_attributes == {
        "last_successful_update": None,
        "last_error": None,
        "configured_child_count": 0,
        "shared_source": True,
        "parser_version": None,
        "fetched_at": None,
    }


def test_child_health_without_snapshot_remains_child_owned() -> None:
    sensor = SpeiseplanHealthSensor(
        coordinator=FakeCoordinator(None, child_slug="lena"),
        child_slug="lena",
    )

    assert sensor.available is False
    assert sensor.extra_state_attributes == {
        "last_successful_update": None,
        "last_error": None,
        "configured_child_count": 0,
        "shared_source": False,
        "parser_version": None,
        "fetched_at": None,
        "child_key": "lena",
    }


def test_health_sensor_public_data_contains_no_secret_markers() -> None:
    sensor = SpeiseplanHealthSensor(
        coordinator=FakeCoordinator(
            _snapshot(
                _entry("monday", "Pasta"),
                children=[Child(child_key="secret", display_name="Private Child")],
            )
        )
    )

    serialized = json.dumps(
        {
            "entity_id": sensor.entity_id,
            "name": sensor.name,
            "native_value": sensor.native_value,
            "attributes": sensor.extra_state_attributes,
        },
        sort_keys=True,
    )

    for marker in FORBIDDEN_SECRET_MARKERS:
        assert marker not in serialized
    assert "Private Child" not in serialized
    assert "username" not in serialized.lower()
    assert "password" not in serialized.lower()
    assert "cookie" not in serialized.lower()
    assert "raw_html" not in serialized.lower()
    assert "account_id" not in serialized.lower()


def test_sensor_public_data_contains_no_secret_markers() -> None:
    sensor = SpeiseplanSharedCurrentMealSensor(
        coordinator=FakeCoordinator(_snapshot(_entry("monday", "Pasta"))),
        weekday="monday",
    )

    serialized = json.dumps(
        {
            "entity_id": sensor.entity_id,
            "name": sensor.name,
            "native_value": sensor.native_value,
            "attributes": sensor.extra_state_attributes,
        },
        sort_keys=True,
    )

    for marker in FORBIDDEN_SECRET_MARKERS:
        assert marker not in serialized
    assert "username" not in serialized.lower()
    assert "password" not in serialized.lower()
    assert "cookie" not in serialized.lower()
    assert "raw_html" not in serialized.lower()
    assert "account_id" not in serialized.lower()
