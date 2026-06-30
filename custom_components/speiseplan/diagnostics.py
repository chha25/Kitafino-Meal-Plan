"""Diagnostics skeleton for Speiseplan."""

from __future__ import annotations

from typing import Any


async def async_get_config_entry_diagnostics(hass: Any, entry: Any) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    return {
        "domain": "speiseplan",
        "entry_id_present": bool(getattr(entry, "entry_id", None)),
    }
