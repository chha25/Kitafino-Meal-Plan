"""Optional MQTT projection skeleton for Speiseplan."""

from __future__ import annotations

from typing import Any


async def async_publish_snapshot(hass: Any, snapshot: Any) -> None:
    """Publish sanitized snapshot data in later stories."""
