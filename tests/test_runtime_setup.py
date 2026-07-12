"""Tests for runtime coordinator wiring during integration setup."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from custom_components.speiseplan import PLATFORMS, async_setup_entry
from custom_components.speiseplan.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    FORBIDDEN_SECRET_MARKERS,
    OPTION_CHILDREN,
    OPTION_SHARED_SOURCE,
)
from custom_components.speiseplan.coordinator import SpeiseplanDataUpdateCoordinator
from custom_components.speiseplan.kitafino.client import (
    KitafinoTransportRequest,
    KitafinoTransportResult,
)
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
        self.coordinator_was_present_on_forward = False

    async def async_forward_entry_setups(
        self,
        entry: Any,
        platforms: tuple[str, ...],
    ) -> None:
        self.coordinator_was_present_on_forward = (
            COORDINATOR_KEY in self.hass.data[DOMAIN][entry.entry_id]
        )
        self.forwarded.append((entry, platforms))


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
