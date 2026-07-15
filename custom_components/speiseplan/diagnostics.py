"""Diagnostics skeleton for Speiseplan."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    FORBIDDEN_SECRET_MARKERS,
    OPTION_CHILDREN,
    OPTION_MQTT_ENABLED,
    OPTION_SHARED_SOURCE,
    OPTION_UPDATE_TIME,
)
from .kitafino.errors import ERROR_UNKNOWN
from .models import ERROR_CODES, MealPlanSnapshot
from .mqtt import REDACTED_VALUE
from .services import COORDINATOR_KEY

SENSITIVE_DIAGNOSTIC_TERMS = (
    "password",
    "passwort",
    "cookie",
    "secret",
    "token",
    "raw_html",
    "account_id",
    "credential",
    "request_body",
    "response_body",
)


async def async_get_config_entry_diagnostics(hass: Any, entry: Any) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    data = getattr(entry, "data", {}) or {}
    options = getattr(entry, "options", {}) or {}
    children = options.get(OPTION_CHILDREN, [])
    configured_child_count = len(children) if isinstance(children, list) else 0
    shared_source = options.get(OPTION_SHARED_SOURCE, True)
    if not isinstance(shared_source, bool):
        shared_source = True
    mqtt_enabled = options.get(OPTION_MQTT_ENABLED, False)
    if not isinstance(mqtt_enabled, bool):
        mqtt_enabled = False
    update_time = options.get(OPTION_UPDATE_TIME)
    if not isinstance(update_time, str):
        update_time = None
    snapshot = _coordinator_snapshot(hass, entry)

    return {
        "domain": "speiseplan",
        "version": _integration_version(),
        "entry_id_present": bool(getattr(entry, "entry_id", None)),
        "username_configured": bool(data.get(CONF_USERNAME)),
        "password_configured": bool(data.get(CONF_PASSWORD)),
        "update_time": update_time,
        "mqtt_enabled": mqtt_enabled,
        "configured_child_count": configured_child_count,
        "shared_source": shared_source,
        "runtime": _snapshot_diagnostics(snapshot),
    }


def _coordinator_snapshot(hass: Any, entry: Any) -> MealPlanSnapshot | None:
    """Return the current coordinator snapshot without exposing coordinator internals."""
    entry_id = getattr(entry, "entry_id", None)
    domain_data = getattr(hass, "data", {}).get(DOMAIN, {}) if hass is not None else {}
    if not isinstance(entry_id, str) or not isinstance(domain_data, dict):
        return None
    entry_data = domain_data.get(entry_id)
    if not isinstance(entry_data, dict):
        return None
    coordinator = entry_data.get(COORDINATOR_KEY)
    snapshot = getattr(coordinator, "snapshot", None)
    if isinstance(snapshot, MealPlanSnapshot):
        return snapshot
    return None


def _snapshot_diagnostics(snapshot: MealPlanSnapshot | None) -> dict[str, Any]:
    """Project a snapshot into a redacted diagnostics summary."""
    if snapshot is None:
        return {
            "snapshot_present": False,
            "health": None,
            "last_successful_update": None,
            "fetched_at": None,
            "parser_version": None,
            "entry_count": 0,
            "configured_child_count": 0,
            "shared_source": True,
        }

    return {
        "snapshot_present": True,
        "health": {
            "state": snapshot.health.state,
            "last_error": (
                snapshot.health.last_error
                if snapshot.health.last_error in ERROR_CODES
                else ERROR_UNKNOWN
            ),
            "last_successful_update": _safe_diagnostic_string(
                snapshot.health.last_successful_update
            ),
            "fetched_at": _safe_diagnostic_string(snapshot.health.fetched_at),
        },
        "last_successful_update": _safe_diagnostic_string(
            snapshot.last_successful_update
        ),
        "fetched_at": _safe_diagnostic_string(snapshot.fetched_at),
        "parser_version": _safe_diagnostic_string(snapshot.parser_version),
        "entry_count": len(snapshot.entries),
        "configured_child_count": len(snapshot.children),
        "shared_source": snapshot.shared_source,
    }


def _integration_version() -> str | None:
    """Read integration version from the manifest."""
    manifest_path = Path(__file__).with_name("manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    version = manifest.get("version")
    return version if isinstance(version, str) else None


def _safe_diagnostic_string(value: str | None) -> str | None:
    """Return a diagnostics string only when it has no sensitive markers."""
    if value is None:
        return None
    if any(marker in value for marker in FORBIDDEN_SECRET_MARKERS):
        return REDACTED_VALUE
    lowered = value.lower()
    if any(term in lowered for term in SENSITIVE_DIAGNOSTIC_TERMS):
        return REDACTED_VALUE
    if "@" in value:
        return REDACTED_VALUE
    return value
