"""Diagnostics skeleton for Speiseplan."""

from __future__ import annotations

from typing import Any

from .const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    OPTION_CHILDREN,
    OPTION_SHARED_SOURCE,
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

    return {
        "domain": "speiseplan",
        "entry_id_present": bool(getattr(entry, "entry_id", None)),
        "username_configured": bool(data.get(CONF_USERNAME)),
        "password_configured": bool(data.get(CONF_PASSWORD)),
        "configured_child_count": configured_child_count,
        "shared_source": shared_source,
    }
