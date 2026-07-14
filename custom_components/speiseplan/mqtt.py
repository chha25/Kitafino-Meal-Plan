"""Optional MQTT projection for Speiseplan."""

from __future__ import annotations

import json
import re
from typing import Any

from .const import OPTION_MQTT_ENABLED
from .models import ERROR_CODES, MealPlanSnapshot

MQTT_TOPIC_PREFIX = "speiseplan"
MQTT_RETAIN = False
MQTT_QOS = 0
SAFE_TOPIC_SEGMENT_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")


async def async_publish_if_enabled(
    hass: Any,
    entry: Any,
    snapshot: MealPlanSnapshot | None,
    *,
    publisher: Any | None = None,
) -> dict[str, Any]:
    """Publish a snapshot only when MQTT is enabled for the config entry."""
    options = getattr(entry, "options", {}) or {}
    if options.get(OPTION_MQTT_ENABLED) is not True:
        return {"published": False, "reason": "disabled"}
    if snapshot is None:
        return {"published": False, "reason": "no_snapshot"}

    return await async_publish_snapshot(
        hass,
        entry_id=getattr(entry, "entry_id", None),
        snapshot=snapshot,
        publisher=publisher,
    )


async def async_publish_snapshot(
    hass: Any,
    *,
    entry_id: str | None,
    snapshot: MealPlanSnapshot,
    publisher: Any | None = None,
) -> dict[str, Any]:
    """Publish sanitized snapshot data through Home Assistant MQTT."""
    topic = build_snapshot_topic(entry_id)
    payload = json.dumps(build_snapshot_payload(snapshot), sort_keys=True)
    publish = publisher or _load_home_assistant_mqtt_publisher()
    if publish is None:
        return {
            "published": False,
            "reason": "mqtt_unavailable",
            "topic": topic,
        }

    try:
        await publish(hass, topic, payload, MQTT_QOS, MQTT_RETAIN)
    except Exception:
        return {
            "published": False,
            "reason": "publish_failed",
            "topic": topic,
        }

    return {
        "published": True,
        "topic": topic,
    }


def build_snapshot_topic(entry_id: str | None) -> str:
    """Return the stable snapshot topic for a config entry."""
    safe_entry_id = _safe_topic_segment(entry_id or "unknown")
    return f"{MQTT_TOPIC_PREFIX}/{safe_entry_id}/snapshot"


def build_snapshot_payload(snapshot: MealPlanSnapshot) -> dict[str, Any]:
    """Build a sanitized MQTT payload from the canonical snapshot."""
    return {
        "health": {
            "state": snapshot.health.state,
            "last_error": (
                snapshot.health.last_error
                if snapshot.health.last_error in ERROR_CODES
                else "unknown_error"
            ),
            "last_successful_update": snapshot.health.last_successful_update,
            "fetched_at": snapshot.health.fetched_at,
        },
        "fetched_at": snapshot.fetched_at,
        "last_successful_update": snapshot.last_successful_update,
        "shared_source": snapshot.shared_source,
        "parser_version": snapshot.parser_version,
        "configured_child_count": len(snapshot.children),
        "entries": [entry.to_dict() for entry in snapshot.entries],
    }


def _safe_topic_segment(value: str) -> str:
    """Return a stable MQTT topic segment without unsafe characters."""
    cleaned = SAFE_TOPIC_SEGMENT_PATTERN.sub("_", value).strip("_")
    return cleaned[:64] if cleaned else "unknown"


def _load_home_assistant_mqtt_publisher() -> Any | None:
    """Load Home Assistant MQTT publisher lazily for local import safety."""
    try:
        from homeassistant.components.mqtt import async_publish
    except ModuleNotFoundError:  # pragma: no cover - local tests without HA installed
        return None

    return async_publish
