"""Sensor platform skeleton for Speiseplan."""

from __future__ import annotations

from typing import Any


async def async_setup_entry(
    hass: Any, entry: Any, async_add_entities: Any
) -> None:
    """Set up Speiseplan sensors for a config entry."""
    async_add_entities([])
