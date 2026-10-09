"""Tests for runtime coordinator wiring during integration setup."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
from typing import Any

import pytest

import custom_components.speiseplan as integration_module
from custom_components.speiseplan import PLATFORMS, async_setup_entry, async_unload_entry
from custom_components.speiseplan.const import (
    CONF_CHILD_SLUG,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    FORBIDDEN_SECRET_MARKERS,
    OPTION_CHILDREN,
    OPTION_SHARED_SOURCE,
    OPTION_UPDATE_TIME,
)
from custom_components.speiseplan.coordinator import SpeiseplanDataUpdateCoordinator
from custom_components.speiseplan.config_flow import async_validate_credential_update
from custom_components.speiseplan.kitafino.client import (
    KitafinoTransportRequest,
    KitafinoTransportResult,
)
from custom_components.speiseplan.kitafino.errors import KitafinoInvalidAuthError
from custom_components.speiseplan.sensor import SpeiseplanHealthSensor, async_setup_entry as async_setup_sensors
from custom_components.speiseplan.services import COORDINATOR_KEY


FIXTURE_HTML = """
<html>
  <body>
    <section data-week="current">
      <div class="weekday">Monday</div>
      <div class="meal">Synthetic pasta</div>
    </section>
    <section data-week="next">
      <div class="weekday">Monday</div>
      <div class="meal">Future soup</div>
    </section>
  </body>
</html>
"""


class FakeConfigEntries:
    def __init__(self, hass: "FakeHass") -> None:
        self.hass = hass
        self.forwarded: list[tuple[Any, tuple[str, ...]]] = []
        self.unloaded: list[tuple[Any, tuple[str, ...]]] = []
        self.coordinator_was_present_on_forward = False
        self.unload_result = True
        self.reloaded: list[str] = []
        self.forward_error: Exception | None = None

    async def async_forward_entry_setups(
        self,
        entry: Any,
        platforms: tuple[str, ...],
    ) -> None:
        if self.forward_error is not None:
            raise self.forward_error
        self.coordinator_was_present_on_forward = (
            COORDINATOR_KEY in self.hass.data[DOMAIN][entry.entry_id]
        )
        self.forwarded.append((entry, platforms))

    async def async_unload_platforms(
        self,
        entry: Any,
        platforms: tuple[str, ...],
    ) -> bool:
        self.unloaded.append((entry, platforms))
        return self.unload_result

    async def async_reload(self, entry_id: str) -> None:
        self.reloaded.append(entry_id)


class FakeServices:
    def async_register(self, domain: str, service: str, handler: Any) -> None:
        return None


class FakeHass:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.config_entries = FakeConfigEntries(self)
        self.services = FakeServices()


class FakeEntry:
    entry_id = "entry-1"

    def __init__(
        self,
        *,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self.data = data or {
            CONF_USERNAME: "parent@example.test",
            CONF_PASSWORD: "super-secret",
        }
        self.options = options or {}


class ScheduledFakeHass(FakeHass):
    def __init__(self) -> None:
        super().__init__()
        self.bus = object()


class ScheduledFakeEntry(FakeEntry):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.update_listeners: list[Any] = []
        self.update_listener_unsubscribed = 0

    def add_update_listener(self, listener: Any) -> Any:
        self.update_listeners.append(listener)

        def unsubscribe() -> None:
            self.update_listener_unsubscribed += 1

        return unsubscribe


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


async def successful_transport(
    request: KitafinoTransportRequest,
) -> KitafinoTransportResult:
    assert request.fetch_source is True
    return KitafinoTransportResult(
        login_status=200,
        login_url=request.login_url,
        login_text="ok",
        source_status=200,
        source_url=request.meal_plan_url,
        source_text=FIXTURE_HTML,
    )


async def failing_transport(
    request: KitafinoTransportRequest,
) -> KitafinoTransportResult:
    return KitafinoTransportResult(
        login_status=503,
        login_url=request.login_url,
        login_text="RAW_KITAFINO_HTML_CAPTURE",
        source_status=None,
        source_url=None,
        source_text=None,
    )


def test_setup_builds_coordinator_before_forwarding_sensor_platform() -> None:
    hass = FakeHass()
    entry = FakeEntry()

    result = _run(
        async_setup_entry(
            hass,
            entry,
            kitafino_transport=successful_transport,
        )
    )

    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR_KEY]
    assert result is True
    assert isinstance(coordinator, SpeiseplanDataUpdateCoordinator)
    assert hass.config_entries.coordinator_was_present_on_forward is True
    assert hass.config_entries.forwarded == [(entry, PLATFORMS)]
    assert coordinator.snapshot is not None
    assert coordinator.snapshot.health.state == "ok"
    assert [entry.week_kind for entry in coordinator.snapshot.entries] == ["current"]
    assert coordinator.snapshot.entries[0].meal_text == "Synthetic pasta"


def test_setup_schedules_one_daily_local_refresh_and_options_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass = ScheduledFakeHass()
    entry = ScheduledFakeEntry(options={OPTION_UPDATE_TIME: "07:35"})
    schedules: list[tuple[Any, int, int, int]] = []
    cancelled: list[bool] = []

    def track_time_change(
        tracked_hass: Any,
        action: Any,
        *,
        hour: int,
        minute: int,
        second: int,
    ) -> Any:
        assert tracked_hass is hass
        schedules.append((action, hour, minute, second))

        def unsubscribe() -> None:
            cancelled.append(True)

        return unsubscribe

    monkeypatch.setattr(integration_module, "async_track_time_change", track_time_change)
    _run(async_setup_entry(hass, entry, kitafino_transport=successful_transport))

    assert [(hour, minute, second) for _, hour, minute, second in schedules] == [
        (7, 35, 0)
    ]
    assert len(entry.update_listeners) == 1
    _run(entry.update_listeners[0](hass, entry))
    assert hass.config_entries.reloaded == [entry.entry_id]

    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR_KEY]
    snapshot = coordinator.snapshot
    _run(async_unload_entry(hass, entry))
    assert cancelled == [True]
    assert entry.update_listener_unsubscribed == 1

    _run(schedules[0][0](datetime.now()))
    assert coordinator.snapshot is snapshot


def test_setup_failure_cleans_all_callbacks_even_when_one_cleanup_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass = ScheduledFakeHass()
    hass.config_entries.forward_error = RuntimeError("forward failed")
    entry = ScheduledFakeEntry()
    schedule_cancelled = 0

    def track_time_change(hass: Any, action: Any, **kwargs: Any) -> Any:
        def unsubscribe() -> None:
            nonlocal schedule_cancelled
            schedule_cancelled += 1
            raise RuntimeError("cancel failed")

        return unsubscribe

    monkeypatch.setattr(integration_module, "async_track_time_change", track_time_change)

    with pytest.raises(RuntimeError, match="forward failed"):
        _run(async_setup_entry(hass, entry, kitafino_transport=successful_transport))

    assert schedule_cancelled == 1
    assert entry.update_listener_unsubscribed == 1
    assert entry.entry_id not in hass.data[DOMAIN]


def test_scheduled_callback_refreshes_only_its_own_coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass = ScheduledFakeHass()
    first = ScheduledFakeEntry(options={OPTION_UPDATE_TIME: "06:00"})
    first.entry_id = "entry-first"
    second = ScheduledFakeEntry(options={OPTION_UPDATE_TIME: "08:15"})
    second.entry_id = "entry-second"
    callbacks: list[Any] = []
    cancelled: list[int] = []

    def track_time_change(hass: Any, action: Any, **kwargs: Any) -> Any:
        index = len(callbacks)
        callbacks.append(action)

        def unsubscribe() -> None:
            cancelled.append(index)

        return unsubscribe

    monkeypatch.setattr(integration_module, "async_track_time_change", track_time_change)
    _run(async_setup_entry(hass, first, kitafino_transport=successful_transport))
    _run(async_setup_entry(hass, second, kitafino_transport=successful_transport))
    first_coordinator = hass.data[DOMAIN][first.entry_id][COORDINATOR_KEY]
    second_coordinator = hass.data[DOMAIN][second.entry_id][COORDINATOR_KEY]
    first_before = first_coordinator.snapshot
    second_before = second_coordinator.snapshot

    _run(callbacks[0](datetime.now()))

    assert first_coordinator.snapshot is not first_before
    assert second_coordinator.snapshot is second_before
    _run(async_unload_entry(hass, first))
    assert cancelled == [0]
    assert second.entry_id in hass.data[DOMAIN]


def test_sensor_setup_creates_entities_from_runtime_coordinator() -> None:
    hass = FakeHass()
    entry = FakeEntry()
    added: list[Any] = []
    _run(
        async_setup_entry(
            hass,
            entry,
            kitafino_transport=successful_transport,
        )
    )

    _run(async_setup_sensors(hass, entry, added.extend))

    assert len(added) == 6
    assert isinstance(added[0], SpeiseplanHealthSensor)
    assert added[0].native_value == "ok"
    assert added[1].native_value == "Synthetic pasta"


def test_child_options_become_metadata_without_child_specific_sensors() -> None:
    hass = FakeHass()
    entry = FakeEntry(
        options={
            OPTION_CHILDREN: [
                {"name": "Lena", "slug": "lena"},
                {"name": "Max", "slug": "max"},
            ],
            OPTION_SHARED_SOURCE: True,
        }
    )
    added: list[Any] = []

    _run(
        async_setup_entry(
            hass,
            entry,
            kitafino_transport=successful_transport,
        )
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR_KEY]
    _run(async_setup_sensors(hass, entry, added.extend))

    assert [child.child_key for child in coordinator.children] == ["lena", "max"]
    assert [child.display_name for child in coordinator.children] == ["Lena", "Max"]
    assert len(added) == 6


def test_two_child_entries_are_isolated_and_have_distinct_entities() -> None:
    hass = FakeHass()
    lena = FakeEntry(
        data={
            CONF_CHILD_SLUG: "lena",
            CONF_USERNAME: "same",
            CONF_PASSWORD: "same",
        }
    )
    lena.entry_id = "entry-lena"
    max_entry = FakeEntry(
        data={
            CONF_CHILD_SLUG: "max",
            CONF_USERNAME: "same",
            CONF_PASSWORD: "same",
        }
    )
    max_entry.entry_id = "entry-max"
    lena_entities: list[Any] = []
    max_entities: list[Any] = []

    _run(async_setup_entry(hass, lena, kitafino_transport=successful_transport))
    _run(async_setup_entry(hass, max_entry, kitafino_transport=successful_transport))
    _run(async_setup_sensors(hass, lena, lena_entities.extend))
    _run(async_setup_sensors(hass, max_entry, max_entities.extend))

    assert len(lena_entities) + len(max_entities) == 12
    assert {entity.unique_id for entity in lena_entities}.isdisjoint(
        {entity.unique_id for entity in max_entities}
    )
    assert {entity.child_slug for entity in lena_entities[1:]} == {"lena"}
    assert {entity.child_slug for entity in max_entities[1:]} == {"max"}
    assert lena_entities[1].extra_state_attributes["child_key"] == "lena"
    assert max_entities[1].extra_state_attributes["child_key"] == "max"

    _run(async_unload_entry(hass, lena))
    survivor = hass.data[DOMAIN][max_entry.entry_id][COORDINATOR_KEY]
    refreshed = _run(survivor.async_refresh())
    assert refreshed.health.state == "ok"


def test_child_failure_never_falls_back_to_shared_identity() -> None:
    hass = FakeHass()
    entry = FakeEntry(
        data={
            CONF_CHILD_SLUG: "lena",
            CONF_USERNAME: "user",
            CONF_PASSWORD: "secret",
        }
    )

    _run(async_setup_entry(hass, entry, kitafino_transport=failing_transport))
    snapshot = hass.data[DOMAIN][entry.entry_id][COORDINATOR_KEY].snapshot

    assert snapshot.shared_source is False
    assert [child.child_key for child in snapshot.children] == ["lena"]


def test_one_child_failure_does_not_block_other_child_refresh() -> None:
    hass = FakeHass()
    failing_entry = FakeEntry(
        data={
            CONF_CHILD_SLUG: "lena",
            CONF_USERNAME: "lena-user",
            CONF_PASSWORD: "secret",
        }
    )
    failing_entry.entry_id = "entry-lena"
    healthy_entry = FakeEntry(
        data={
            CONF_CHILD_SLUG: "max",
            CONF_USERNAME: "max-user",
            CONF_PASSWORD: "secret",
        }
    )
    healthy_entry.entry_id = "entry-max"

    _run(async_setup_entry(hass, failing_entry, kitafino_transport=failing_transport))
    _run(async_setup_entry(hass, healthy_entry, kitafino_transport=successful_transport))
    refreshed = _run(
        hass.data[DOMAIN][healthy_entry.entry_id][COORDINATOR_KEY].async_refresh()
    )

    assert refreshed.health.state == "ok"
    assert {meal.child_key for meal in refreshed.entries} == {"max"}


@pytest.mark.parametrize("stored_slug", ["shared", " lena "])
def test_invalid_persisted_child_slug_cannot_create_colliding_entities(
    stored_slug: str,
) -> None:
    hass = FakeHass()
    entry = FakeEntry(
        data={
            CONF_CHILD_SLUG: stored_slug,
            CONF_USERNAME: "user",
            CONF_PASSWORD: "secret",
        }
    )

    with pytest.raises(ValueError, match="Invalid child slug"):
        _run(async_setup_entry(hass, entry, kitafino_transport=successful_transport))

    assert entry.entry_id not in hass.data[DOMAIN]


def test_reauthentication_preserves_slug_and_entity_identities() -> None:
    original_data = {
        CONF_CHILD_SLUG: "lena",
        CONF_USERNAME: "old-user",
        CONF_PASSWORD: "old-secret",
    }
    before_hass = FakeHass()
    before_entry = FakeEntry(data=original_data)
    before_entities: list[Any] = []
    _run(async_setup_entry(before_hass, before_entry, kitafino_transport=successful_transport))
    _run(async_setup_sensors(before_hass, before_entry, before_entities.extend))

    async def accept_credentials(username: str, password: str) -> None:
        return None

    update = _run(
        async_validate_credential_update(
            original_data,
            {CONF_USERNAME: "new-user", CONF_PASSWORD: "new-secret"},
            validator=accept_credentials,
        )
    )
    after_hass = FakeHass()
    after_entry = FakeEntry(data=update.entry_data)
    after_entities: list[Any] = []
    _run(async_setup_entry(after_hass, after_entry, kitafino_transport=successful_transport))
    _run(async_setup_sensors(after_hass, after_entry, after_entities.extend))

    assert update.entry_data[CONF_CHILD_SLUG] == "lena"
    assert [entity.unique_id for entity in before_entities] == [
        entity.unique_id for entity in after_entities
    ]


def test_failed_reauthentication_leaves_existing_child_entities_unchanged() -> None:
    original_data = {
        CONF_CHILD_SLUG: "lena",
        CONF_USERNAME: "old-user",
        CONF_PASSWORD: "old-secret",
    }
    hass = FakeHass()
    entry = FakeEntry(data=original_data)
    entities: list[Any] = []
    _run(async_setup_entry(hass, entry, kitafino_transport=successful_transport))
    _run(async_setup_sensors(hass, entry, entities.extend))
    identities = [entity.unique_id for entity in entities]

    async def reject_credentials(username: str, password: str) -> None:
        raise KitafinoInvalidAuthError()

    update = _run(
        async_validate_credential_update(
            original_data,
            {CONF_USERNAME: "bad-user", CONF_PASSWORD: "bad-secret"},
            validator=reject_credentials,
        )
    )

    assert update.errors == {"base": "invalid_auth"}
    assert original_data[CONF_CHILD_SLUG] == "lena"
    assert [entity.unique_id for entity in entities] == identities


def test_failed_initial_refresh_still_publishes_safe_entities() -> None:
    hass = FakeHass()
    entry = FakeEntry()
    added: list[Any] = []

    _run(
        async_setup_entry(
            hass,
            entry,
            kitafino_transport=failing_transport,
        )
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR_KEY]
    _run(async_setup_sensors(hass, entry, added.extend))

    assert coordinator.snapshot is not None
    assert coordinator.snapshot.health.state == "network_error"
    assert len(added) == 6
    assert added[0].native_value == "network_error"
    assert added[1].available is False


def test_runtime_setup_public_state_contains_no_secret_markers() -> None:
    hass = FakeHass()
    entry = FakeEntry()

    _run(
        async_setup_entry(
            hass,
            entry,
            kitafino_transport=successful_transport,
        )
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR_KEY]
    serialized = json.dumps(coordinator.snapshot.to_dict(), sort_keys=True)

    for marker in FORBIDDEN_SECRET_MARKERS:
        assert marker not in serialized
    assert "parent@example.test" not in serialized
    assert "super-secret" not in serialized
    assert "password" not in serialized.lower()
    assert "cookie" not in serialized.lower()
    assert "raw_html" not in serialized.lower()
    assert "account_id" not in serialized.lower()


def test_unload_entry_unloads_sensor_platform_before_removing_data() -> None:
    hass = FakeHass()
    entry = FakeEntry()
    _run(
        async_setup_entry(
            hass,
            entry,
            kitafino_transport=successful_transport,
        )
    )

    result = _run(async_unload_entry(hass, entry))

    assert result is True
    assert hass.config_entries.unloaded == [(entry, PLATFORMS)]
    assert entry.entry_id not in hass.data[DOMAIN]


def test_failed_platform_unload_preserves_entry_data() -> None:
    hass = FakeHass()
    entry = FakeEntry()
    _run(
        async_setup_entry(
            hass,
            entry,
            kitafino_transport=successful_transport,
        )
    )
    hass.config_entries.unload_result = False

    result = _run(async_unload_entry(hass, entry))

    assert result is False
    assert entry.entry_id in hass.data[DOMAIN]
