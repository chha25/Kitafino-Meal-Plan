"""Optional MQTT projection for Speiseplan."""

from __future__ import annotations

import json
import re
from typing import Any

from .const import FORBIDDEN_SECRET_MARKERS, OPTION_MQTT_ENABLED
from .models import ERROR_CODES, MealPlanSnapshot

MQTT_TOPIC_PREFIX = "speiseplan"
MQTT_RETAIN = False
MQTT_QOS = 0
SAFE_TOPIC_SEGMENT_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")
MAX_TOPIC_SEGMENT_LENGTH = 64
REDACTED_VALUE = "redacted"


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
    publish = publisher or _load_home_assistant_mqtt_publisher()
    if publish is None:
        return {
            "published": False,
            "reason": "mqtt_unavailable",
            "topic": topic,
        }

    messages = build_snapshot_messages(entry_id=entry_id, snapshot=snapshot)
    try:
        for message_topic, payload in messages:
            await publish(hass, message_topic, payload, MQTT_QOS, MQTT_RETAIN)
    except Exception:
        return {
            "published": False,
            "reason": "publish_failed",
            "topic": topic,
        }

    return {
        "published": True,
        "topic": topic,
        "topics": [message_topic for message_topic, _ in messages],
    }


def build_snapshot_topic(entry_id: str | None) -> str:
    """Return the stable snapshot topic for a config entry."""
    safe_entry_id = _safe_topic_segment(entry_id or "unknown")
    return f"{MQTT_TOPIC_PREFIX}/{safe_entry_id}/snapshot"


def build_health_topic(entry_id: str | None) -> str:
    """Return the stable health topic for a config entry."""
    safe_entry_id = _safe_topic_segment(entry_id or "unknown")
    return f"{MQTT_TOPIC_PREFIX}/{safe_entry_id}/health"


def build_entry_topic(
    entry_id: str | None,
    *,
    source: str,
    week: str,
    day: str,
) -> str:
    """Return the stable topic for one meal entry."""
    safe_entry_id = _safe_topic_segment(entry_id or "unknown")
    return (
        f"{MQTT_TOPIC_PREFIX}/{safe_entry_id}/meal/"
        f"{_safe_topic_segment(source)}/"
        f"{_safe_topic_segment(week)}/"
        f"{_safe_topic_segment(day)}"
    )


def build_snapshot_messages(
    *,
    entry_id: str | None,
    snapshot: MealPlanSnapshot,
) -> list[tuple[str, str]]:
    """Build all MQTT topic/payload pairs for a snapshot."""
    messages = [
        (
            build_snapshot_topic(entry_id),
            json.dumps(build_snapshot_payload(snapshot), sort_keys=True),
        ),
        (
            build_health_topic(entry_id),
            json.dumps(build_health_payload(snapshot), sort_keys=True),
        ),
    ]
    messages.extend(
        (
            build_entry_topic(
                entry_id,
                source=entry.child_key,
                week=entry.week_kind,
                day=entry.weekday,
            ),
            json.dumps(build_entry_payload(entry), sort_keys=True),
        )
        for entry in snapshot.entries
    )
    return messages


def build_snapshot_payload(snapshot: MealPlanSnapshot) -> dict[str, Any]:
    """Build a sanitized MQTT payload from the canonical snapshot."""
    return {
        "health": build_health_payload(snapshot),
        "fetched_at": _safe_payload_string(snapshot.fetched_at),
        "last_successful_update": _safe_payload_string(snapshot.last_successful_update),
        "shared_source": snapshot.shared_source,
        "parser_version": _safe_payload_string(snapshot.parser_version),
        "configured_child_count": len(snapshot.children),
        "entries": [build_entry_payload(entry) for entry in snapshot.entries],
    }


def build_health_payload(snapshot: MealPlanSnapshot) -> dict[str, Any]:
    """Build a sanitized health/status MQTT payload."""
    return {
        "state": snapshot.health.state,
        "last_error": (
            snapshot.health.last_error
            if snapshot.health.last_error in ERROR_CODES
            else "unknown_error"
        ),
        "last_successful_update": _safe_payload_string(
            snapshot.health.last_successful_update
        ),
        "fetched_at": _safe_payload_string(snapshot.health.fetched_at),
        "shared_source": snapshot.shared_source,
        "parser_version": _safe_payload_string(snapshot.parser_version),
    }


def build_entry_payload(entry: Any) -> dict[str, Any]:
    """Build a sanitized meal-entry MQTT payload."""
    source = _safe_public_identifier(entry.child_key)
    return {
        "source": source,
        "week": _safe_public_identifier(entry.week_kind),
        "day": _safe_public_identifier(entry.weekday),
        "meal_text": _safe_payload_string(entry.meal_text),
        "source_date": _safe_payload_string(entry.source_date),
        "fetched_at": _safe_payload_string(entry.fetched_at),
        "stale": entry.stale,
        "shared_source": entry.shared_source,
        "iso_year": entry.iso_year,
        "iso_week": entry.iso_week,
    }


def _safe_topic_segment(value: str) -> str:
    """Return a stable MQTT topic segment without unsafe characters."""
    if any(marker in value for marker in FORBIDDEN_SECRET_MARKERS):
        return "unknown"
    cleaned = SAFE_TOPIC_SEGMENT_PATTERN.sub("_", value).strip("_")
    return cleaned[:MAX_TOPIC_SEGMENT_LENGTH] if cleaned else "unknown"


def _safe_public_identifier(value: str) -> str:
    """Return a public identifier safe for payloads and topics."""
    return _safe_topic_segment(value)


def _safe_payload_string(value: str | None) -> str | None:
    """Return a payload string only when it contains no known secret marker."""
    if value is None:
        return None
    if any(marker in value for marker in FORBIDDEN_SECRET_MARKERS):
        return REDACTED_VALUE
    lowered = value.lower()
    if any(
        marker in lowered
        for marker in (
            "password",
            "cookie",
            "token",
            "raw_html",
            "account_id",
            "request_body",
            "response_body",
        )
    ):
        return REDACTED_VALUE
    return value


def _load_home_assistant_mqtt_publisher() -> Any | None:
    """Load Home Assistant MQTT publisher lazily for local import safety."""
    try:
        from homeassistant.components.mqtt import async_publish
    except ModuleNotFoundError:  # pragma: no cover - local tests without HA installed
        return None

    return async_publish
