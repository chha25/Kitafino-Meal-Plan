"""Tests for optional MQTT snapshot projection."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import custom_components.speiseplan as integration_module
import custom_components.speiseplan.services as services_module
from custom_components.speiseplan.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    FORBIDDEN_SECRET_MARKERS,
    OPTION_MQTT_ENABLED,
)
from custom_components.speiseplan.kitafino.client import (
    KitafinoTransportRequest,
    KitafinoTransportResult,
)
from custom_components.speiseplan.models import Child, HealthStatus, MealEntry, MealPlanSnapshot
from custom_components.speiseplan.mqtt import (
    async_publish_if_enabled,
    async_publish_snapshot,
    build_entry_payload,
    build_entry_topic,
    build_health_topic,
    build_snapshot_payload,
    build_snapshot_topic,
)
from custom_components.speiseplan.services import (
    COORDINATOR_KEY,
    ManualRefreshThrottler,
    async_handle_manual_refresh,
)


FETCHED_AT = "2026-07-14T06:00:00+02:00"
ROOT = Path(__file__).resolve().parents[1]
FIXTURE_HTML = """
<html>
  <body>
    <section data-week="current">
      <div class="weekday">Monday</div>
      <div class="meal">Synthetic pasta</div>
    </section>
  </body>
</html>
"""


class FakeServices:
    def async_register(self, domain: str, service: str, handler: Any) -> None:
        return None


class FakeConfigEntries:
    async def async_forward_entry_setups(
        self,
        entry: Any,
        platforms: tuple[str, ...],
    ) -> None:
        return None


class FakeHass:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.services = FakeServices()
        self.config_entries = FakeConfigEntries()


class FakeEntry:
    entry_id = "entry-1"

    def __init__(self, *, mqtt_enabled: bool = False) -> None:
        self.data = {
            CONF_USERNAME: "parent@example.test",
            CONF_PASSWORD: "super-secret",
        }
        self.options = {OPTION_MQTT_ENABLED: mqtt_enabled}


class FakeCoordinator:
    def __init__(self, snapshot: MealPlanSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    async def async_refresh(self, *, phase: str = "refresh") -> MealPlanSnapshot:
        self.calls += 1
        return self.snapshot


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


def _snapshot() -> MealPlanSnapshot:
    return MealPlanSnapshot(
        health=HealthStatus(
            state="ok",
            fetched_at=FETCHED_AT,
            last_successful_update=FETCHED_AT,
        ),
        children=[
            Child(
                child_key="REAL_ACCOUNT_ID_VALUE",
                display_name="Private Child",
            )
        ],
        entries=[
            MealEntry(
                child_key="shared",
                week_kind="current",
                iso_year=2026,
                iso_week=29,
                weekday="monday",
                meal_text="Synthetic pasta",
                source_date=None,
                fetched_at=FETCHED_AT,
                stale=False,
                shared_source=True,
            )
        ],
        fetched_at=FETCHED_AT,
        last_successful_update=FETCHED_AT,
        shared_source=True,
        parser_version="kitafino-html-v1",
    )


def test_manifest_declares_mqtt_after_dependency() -> None:
    manifest = json.loads(
        (ROOT / "custom_components/speiseplan/manifest.json").read_text()
    )

    assert "mqtt" in manifest["after_dependencies"]
    assert "mqtt" not in manifest["dependencies"]


def test_readme_documents_mqtt_contract() -> None:
    readme = (ROOT / "README.md").read_text()

    for expected in (
        "MQTT publishing is disabled by default",
        "speiseplan/{entry_id}/snapshot",
        "speiseplan/{entry_id}/health",
        "speiseplan/{entry_id}/meal/{source}/{week}/{day}",
        "QoS `0`",
        "retained messages disabled",
        "child display names",
        "\"health\"",
        "\"entries\"",
        "\"meal_text\"",
        "\"source_date\"",
        "\"iso_week\"",
        "Known unsafe values are redacted",
    ):
        assert expected in readme


async def successful_transport(
    request: KitafinoTransportRequest,
) -> KitafinoTransportResult:
    return KitafinoTransportResult(
        login_status=200,
        login_url=request.login_url,
        login_text="ok",
        source_status=200,
        source_url=request.meal_plan_url,
        source_text=FIXTURE_HTML,
    )


def test_mqtt_payload_is_snapshot_derived_and_redacted() -> None:
    payload = build_snapshot_payload(_snapshot())
    serialized = json.dumps(payload, sort_keys=True)

    assert build_snapshot_topic("entry-1") == "speiseplan/entry-1/snapshot"
    assert build_health_topic("entry-1") == "speiseplan/entry-1/health"
    assert (
        build_entry_topic(
            "entry-1",
            source="shared",
            week="current",
            day="monday",
        )
        == "speiseplan/entry-1/meal/shared/current/monday"
    )
    assert payload["health"]["state"] == "ok"
    assert payload["configured_child_count"] == 1
    assert payload["entries"][0]["meal_text"] == "Synthetic pasta"
    assert payload["entries"][0]["source"] == "shared"
    assert payload["entries"][0]["week"] == "current"
    assert payload["entries"][0]["day"] == "monday"
    assert "Private Child" not in serialized
    assert "REAL_ACCOUNT_ID_VALUE" not in serialized
    for marker in FORBIDDEN_SECRET_MARKERS:
        assert marker not in serialized


def test_mqtt_entry_identifiers_are_sanitized() -> None:
    entry = MealEntry(
        child_key="REAL_ACCOUNT_ID_VALUE/private child",
        week_kind="current",
        iso_year=2026,
        iso_week=29,
        weekday="monday",
        meal_text="Pasta",
        source_date=None,
        fetched_at=FETCHED_AT,
        stale=False,
        shared_source=False,
    )

    assert build_entry_payload(entry)["source"] == "unknown"
    assert (
        build_entry_topic(
            "entry/one",
            source=entry.child_key,
            week=entry.week_kind,
            day=entry.weekday,
        )
        == "speiseplan/entry_one/meal/unknown/current/monday"
    )


def test_mqtt_payload_string_fields_are_redacted_when_contaminated() -> None:
    health = HealthStatus(
        state="stale",
        last_error="network_error",
        fetched_at="cookie=REAL_SESSION_COOKIE_VALUE",
        last_successful_update="2026-07-14T06:00:00+02:00",
    )
    object.__setattr__(health, "last_error", "RAW_KITAFINO_HTML_CAPTURE")
    snapshot = MealPlanSnapshot(
        health=health,
        entries=[
            MealEntry(
                child_key="shared",
                week_kind="current",
                iso_year=2026,
                iso_week=29,
                weekday="monday",
                meal_text="password=super-secret",
                source_date="account_id=REAL_ACCOUNT_ID_VALUE",
                fetched_at="token=abc",
                stale=False,
                shared_source=True,
            )
        ],
        fetched_at="response_body=RAW_KITAFINO_HTML_CAPTURE",
        last_successful_update="2026-07-14T06:00:00+02:00",
        shared_source=True,
        parser_version="raw_html parser dump",
    )

    serialized = json.dumps(build_snapshot_payload(snapshot), sort_keys=True)

    assert "redacted" in serialized
    assert "unknown_error" in serialized
    for forbidden in (
        "RAW_KITAFINO_HTML_CAPTURE",
        "REAL_SESSION_COOKIE_VALUE",
        "REAL_ACCOUNT_ID_VALUE",
        "super-secret",
        "token=abc",
        "raw_html parser dump",
    ):
        assert forbidden not in serialized


def test_mqtt_disabled_does_not_publish() -> None:
    calls: list[tuple[Any, str, str, int, bool]] = []

    result = _run(
        async_publish_if_enabled(
            FakeHass(),
            FakeEntry(mqtt_enabled=False),
            _snapshot(),
            publisher=lambda *args: calls.append(args),
        )
    )

    assert result == {"published": False, "reason": "disabled"}
    assert calls == []


def test_mqtt_enabled_publishes_snapshot_payload() -> None:
    calls: list[tuple[Any, str, str, int, bool]] = []

    async def publisher(
        hass: Any,
        topic: str,
        payload: str,
        qos: int,
        retain: bool,
    ) -> None:
        calls.append((hass, topic, payload, qos, retain))

    result = _run(
        async_publish_snapshot(
            FakeHass(),
            entry_id="entry-1",
            snapshot=_snapshot(),
            publisher=publisher,
        )
    )

    assert result == {
        "published": True,
        "topic": "speiseplan/entry-1/snapshot",
        "topics": [
            "speiseplan/entry-1/snapshot",
            "speiseplan/entry-1/health",
            "speiseplan/entry-1/meal/shared/current/monday",
        ],
    }
    assert [call[1] for call in calls] == result["topics"]
    assert json.loads(calls[0][2]) == build_snapshot_payload(_snapshot())
    assert json.loads(calls[1][2]) == build_snapshot_payload(_snapshot())["health"]
    assert json.loads(calls[2][2]) == build_snapshot_payload(_snapshot())["entries"][0]
    assert all(call[3:] == (0, False) for call in calls)


def test_mqtt_publish_failure_is_optional_and_redacted() -> None:
    async def failing_publisher(
        hass: Any,
        topic: str,
        payload: str,
        qos: int,
        retain: bool,
    ) -> None:
        raise RuntimeError("RAW_KITAFINO_HTML_CAPTURE super-secret")

    result = _run(
        async_publish_snapshot(
            FakeHass(),
            entry_id="entry-1",
            snapshot=_snapshot(),
            publisher=failing_publisher,
        )
    )

    assert result == {
        "published": False,
        "reason": "publish_failed",
        "topic": "speiseplan/entry-1/snapshot",
    }
    assert "RAW_KITAFINO_HTML_CAPTURE" not in str(result)
    assert "super-secret" not in str(result)


def test_setup_publishes_once_when_mqtt_enabled(monkeypatch: object) -> None:
    calls: list[tuple[Any, Any, MealPlanSnapshot | None]] = []

    async def fake_publish(
        hass: Any,
        entry: Any,
        snapshot: MealPlanSnapshot | None,
    ) -> dict[str, Any]:
        calls.append((hass, entry, snapshot))
        return {"published": True}

    monkeypatch.setattr(  # type: ignore[attr-defined]
        integration_module,
        "async_publish_if_enabled",
        fake_publish,
    )
    hass = FakeHass()
    entry = FakeEntry(mqtt_enabled=True)

    _run(
        integration_module.async_setup_entry(
            hass,
            entry,
            kitafino_transport=successful_transport,
        )
    )

    assert len(calls) == 1
    assert calls[0][1] is entry
    assert calls[0][2] is not None
    assert calls[0][2].health.state == "ok"


def test_setup_keeps_entities_when_optional_mqtt_publish_fails(
    monkeypatch: object,
) -> None:
    async def failing_publish(
        hass: Any,
        entry: Any,
        snapshot: MealPlanSnapshot | None,
    ) -> dict[str, Any]:
        return {"published": False, "reason": "publish_failed"}

    monkeypatch.setattr(  # type: ignore[attr-defined]
        integration_module,
        "async_publish_if_enabled",
        failing_publish,
    )
    hass = FakeHass()
    entry = FakeEntry(mqtt_enabled=True)

    result = _run(
        integration_module.async_setup_entry(
            hass,
            entry,
            kitafino_transport=successful_transport,
        )
    )

    assert result is True
    assert COORDINATOR_KEY in hass.data[DOMAIN][entry.entry_id]


def test_manual_refresh_publishes_when_entry_mqtt_enabled(monkeypatch: object) -> None:
    calls: list[tuple[Any, Any, MealPlanSnapshot | None]] = []

    async def fake_publish(
        hass: Any,
        entry: Any,
        snapshot: MealPlanSnapshot | None,
    ) -> dict[str, Any]:
        calls.append((hass, entry, snapshot))
        return {"published": True}

    monkeypatch.setattr(  # type: ignore[attr-defined]
        services_module,
        "async_publish_if_enabled",
        fake_publish,
    )
    hass = SimpleNamespace(
        data={
            DOMAIN: {
                "entry-1": {
                    "entry": FakeEntry(mqtt_enabled=True),
                    COORDINATOR_KEY: FakeCoordinator(_snapshot()),
                }
            }
        }
    )

    result = _run(
        async_handle_manual_refresh(
            hass,
            throttler=ManualRefreshThrottler(),
        )
    )

    assert result["refreshed"] == 1
    assert len(calls) == 1
    assert calls[0][2] == _snapshot()
