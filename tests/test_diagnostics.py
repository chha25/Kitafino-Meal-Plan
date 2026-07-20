"""Tests for diagnostics scaffold and redaction guardrails."""

from __future__ import annotations

from pathlib import Path
import asyncio
from types import SimpleNamespace

from custom_components.speiseplan.const import (
    CONF_CHILD_SLUG,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    FORBIDDEN_SECRET_MARKERS,
    OPTION_CHILDREN,
    OPTION_MQTT_ENABLED,
    OPTION_SHARED_SOURCE,
    OPTION_UPDATE_TIME,
)
from custom_components.speiseplan.diagnostics import async_get_config_entry_diagnostics
from custom_components.speiseplan.models import Child, HealthStatus, MealEntry, MealPlanSnapshot
from custom_components.speiseplan.services import COORDINATOR_KEY


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_PATHS = [
    ROOT / "CHANGELOG.md",
    ROOT / "README.md",
    ROOT / "hacs.json",
    ROOT / "custom_components/speiseplan/manifest.json",
    ROOT / "tests/fixtures/README.md",
    ROOT / "tests/fixtures/kitafino_current_week.html",
    ROOT / "tests/fixtures/kitafino_parse_error.html",
]


def test_public_scaffold_contains_no_forbidden_secret_markers() -> None:
    public_text = "\n".join(path.read_text() for path in PUBLIC_PATHS)

    for marker in FORBIDDEN_SECRET_MARKERS:
        assert marker not in public_text


def test_readme_documents_per_child_setup_and_legacy_conversion() -> None:
    readme = (ROOT / "README.md").read_text()

    assert "Add the integration once per child" in readme
    assert "immutable public slug" in readme
    assert "remove it and add one new entry per child" in readme
    assert "including a `shared` row, remain saveable" in readme


def test_readme_documents_next_week_as_deferred() -> None:
    readme = (ROOT / "README.md").read_text()

    assert "Next Week support is deferred" in readme
    assert "Current Week sensors do not depend on Next Week data" in readme


def test_readme_documents_entity_state_and_attribute_contract() -> None:
    readme = (ROOT / "README.md").read_text()

    for expected in (
        "sensor.speiseplan_health",
        "sensor.speiseplan_shared_current_{weekday}",
        "last_successful_update",
        "last_error",
        "shared_source",
        "stale",
        "iso_week",
        "parser_version",
    ):
        assert expected in readme


def test_diagnostics_redact_config_entry_credentials() -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_USERNAME: "parent@example.test",
            CONF_PASSWORD: "super-secret",
        },
    )

    diagnostics = asyncio.run(async_get_config_entry_diagnostics(None, entry))

    assert diagnostics["username_configured"] is True
    assert diagnostics["password_configured"] is True
    assert "parent@example.test" not in str(diagnostics)
    assert "super-secret" not in str(diagnostics)


def test_diagnostics_remain_redacted_after_credential_update() -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_USERNAME: "updated@example.test",
            CONF_PASSWORD: "new-secret",
        },
    )

    diagnostics = asyncio.run(async_get_config_entry_diagnostics(None, entry))

    assert diagnostics["username_configured"] is True
    assert diagnostics["password_configured"] is True
    assert "updated@example.test" not in str(diagnostics)
    assert "new-secret" not in str(diagnostics)


def test_diagnostics_report_child_count_and_shared_source_without_labels() -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_USERNAME: "parent@example.test",
            CONF_PASSWORD: "super-secret",
        },
        options={
            OPTION_CHILDREN: [
                {"name": "Lena", "slug": "lena"},
                {"name": "Max", "slug": "max"},
            ],
            OPTION_SHARED_SOURCE: True,
        },
    )

    diagnostics = asyncio.run(async_get_config_entry_diagnostics(None, entry))
    serialized = str(diagnostics)

    assert diagnostics["configured_child_count"] == 2
    assert diagnostics["shared_source"] is True
    assert "Lena" not in serialized
    assert "Max" not in serialized
    assert "lena" not in serialized
    assert "max" not in serialized
    assert "parent@example.test" not in serialized
    assert "super-secret" not in serialized


def test_child_diagnostics_report_mode_without_exposing_public_slug() -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_CHILD_SLUG: "lena",
            CONF_USERNAME: "parent@example.test",
            CONF_PASSWORD: "super-secret",
        },
        options={},
    )

    diagnostics = asyncio.run(async_get_config_entry_diagnostics(None, entry))
    serialized = str(diagnostics)

    assert diagnostics["configured_child_count"] == 1
    assert diagnostics["shared_source"] is False
    assert "lena" not in serialized
    assert "parent@example.test" not in serialized


def test_invalid_persisted_slug_is_not_reported_as_child_mode() -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={CONF_CHILD_SLUG: "shared"},
        options={},
    )

    diagnostics = asyncio.run(async_get_config_entry_diagnostics(None, entry))

    assert diagnostics["configured_child_count"] == 0
    assert diagnostics["shared_source"] is True


def test_diagnostics_include_redacted_options_and_runtime_snapshot() -> None:
    health = HealthStatus(
        state="stale",
        last_error="network_error",
        fetched_at="2026-07-14T06:05:00+02:00",
        last_successful_update="2026-07-14T06:00:00+02:00",
    )
    object.__setattr__(health, "last_error", "RAW_KITAFINO_HTML_CAPTURE")
    snapshot = MealPlanSnapshot(
        health=health,
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
                meal_text="RAW_KITAFINO_HTML_CAPTURE",
                source_date=None,
                fetched_at="2026-07-14T06:00:00+02:00",
                stale=True,
                shared_source=True,
            )
        ],
        fetched_at="parent@example.test",
        last_successful_update="2026-07-14T06:00:00+02:00",
        shared_source=True,
        parser_version="raw_html parser dump",
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_USERNAME: "parent@example.test",
            CONF_PASSWORD: "super-secret",
        },
        options={
            OPTION_CHILDREN: [{"name": "Private Child", "slug": "kid"}],
            OPTION_SHARED_SOURCE: True,
            OPTION_UPDATE_TIME: "06:00",
            OPTION_MQTT_ENABLED: True,
        },
    )
    hass = SimpleNamespace(
        data={
            DOMAIN: {
                "entry-1": {
                    COORDINATOR_KEY: SimpleNamespace(snapshot=snapshot),
                }
            }
        }
    )

    diagnostics = asyncio.run(async_get_config_entry_diagnostics(hass, entry))
    serialized = str(diagnostics)

    assert diagnostics["update_time"] == "06:00"
    assert diagnostics["version"] == "1.0.0"
    assert diagnostics["mqtt_enabled"] is True
    assert diagnostics["configured_child_count"] == 1
    assert diagnostics["runtime"] == {
        "snapshot_present": True,
        "health": {
            "state": "stale",
            "last_error": "unknown_error",
            "last_successful_update": "2026-07-14T06:00:00+02:00",
            "fetched_at": "2026-07-14T06:05:00+02:00",
        },
        "last_successful_update": "2026-07-14T06:00:00+02:00",
        "fetched_at": "redacted",
        "parser_version": "redacted",
        "entry_count": 1,
        "configured_child_count": 1,
        "shared_source": True,
    }
    assert "parent@example.test" not in serialized
    assert "super-secret" not in serialized
    assert "Private Child" not in serialized
    assert "kid" not in serialized
    assert "REAL_ACCOUNT_ID_VALUE" not in serialized
    assert "RAW_KITAFINO_HTML_CAPTURE" not in serialized


def test_diagnostics_runtime_shape_without_snapshot() -> None:
    entry = SimpleNamespace(entry_id="entry-1", data={}, options={})
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": {COORDINATOR_KEY: object()}}})

    diagnostics = asyncio.run(async_get_config_entry_diagnostics(hass, entry))

    assert diagnostics["runtime"] == {
        "snapshot_present": False,
        "health": None,
        "last_successful_update": None,
        "fetched_at": None,
        "parser_version": None,
        "entry_count": 0,
        "configured_child_count": 0,
        "shared_source": True,
    }
