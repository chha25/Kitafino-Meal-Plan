"""Speiseplan Home Assistant integration skeleton."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN
from .services import async_setup_services

PLATFORMS: tuple[str, ...] = ("sensor",)


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up Speiseplan from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"entry": entry}
    await async_setup_services(hass)
    config_entries = getattr(hass, "config_entries", None)
    forward_setups = getattr(config_entries, "async_forward_entry_setups", None)
    if callable(forward_setups):
        await forward_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload a Speiseplan config entry."""
    domain_data = hass.data.get(DOMAIN, {})
    domain_data.pop(entry.entry_id, None)
    return True
