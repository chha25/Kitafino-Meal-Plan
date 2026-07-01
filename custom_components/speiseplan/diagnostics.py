"""Diagnostics skeleton for Speiseplan."""

from __future__ import annotations

from typing import Any

from .const import CONF_PASSWORD, CONF_USERNAME


async def async_get_config_entry_diagnostics(hass: Any, entry: Any) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    data = getattr(entry, "data", {}) or {}

    return {
        "domain": "speiseplan",
        "entry_id_present": bool(getattr(entry, "entry_id", None)),
        "username_configured": bool(data.get(CONF_USERNAME)),
        "password_configured": bool(data.get(CONF_PASSWORD)),
    }
