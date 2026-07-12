"""Speiseplan Home Assistant integration skeleton."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .config_flow import build_default_options
from .const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    OPTION_CHILDREN,
    OPTION_SHARED_SOURCE,
)
from .coordinator import SpeiseplanDataUpdateCoordinator
from .kitafino.client import KitafinoClient, KitafinoTransport
from .kitafino.parser import KitafinoParser
from .models import Child
from .services import COORDINATOR_KEY, async_setup_services
from .storage import SnapshotStore

PLATFORMS: tuple[str, ...] = ("sensor",)


async def async_setup_entry(
    hass: Any,
    entry: Any,
    *,
    kitafino_transport: KitafinoTransport | None = None,
) -> bool:
    """Set up Speiseplan from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    coordinator = build_runtime_coordinator(
        entry,
        kitafino_transport=kitafino_transport,
    )
    await coordinator.async_load_cached_snapshot()
    await coordinator.async_refresh()
    hass.data[DOMAIN][entry.entry_id] = {
        "entry": entry,
        COORDINATOR_KEY: coordinator,
    }
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


def build_runtime_coordinator(
    entry: Any,
    *,
    kitafino_transport: KitafinoTransport | None = None,
    store: SnapshotStore | None = None,
) -> SpeiseplanDataUpdateCoordinator:
    """Build the runtime coordinator for a config entry."""
    data = getattr(entry, "data", {}) or {}
    options = _options_with_defaults(getattr(entry, "options", {}) or {})
    username = data.get(CONF_USERNAME, "")
    password = data.get(CONF_PASSWORD, "")
    client = KitafinoClient(
        username if isinstance(username, str) else "",
        password if isinstance(password, str) else "",
        transport=kitafino_transport,
    )
    parser = KitafinoParser()
    shared_source = options[OPTION_SHARED_SOURCE]

    def clock() -> str:
        return datetime.now().astimezone().isoformat()

    def parse_source(source: str, *, fetched_at: str) -> Any:
        parsed_time = datetime.fromisoformat(fetched_at)
        iso_calendar = parsed_time.isocalendar()
        return parser.parse_current_week(
            source,
            fetched_at=fetched_at,
            iso_year=iso_calendar.year,
            iso_week=iso_calendar.week,
            shared_source=shared_source,
        )

    return SpeiseplanDataUpdateCoordinator(
        fetch_source=client.async_fetch_meal_plan_source,
        parse_source=parse_source,
        store=store or SnapshotStore(),
        clock=clock,
        children=_children_from_options(options[OPTION_CHILDREN]),
        parser_version=parser.parser_version,
        shared_source=shared_source,
    )


def _options_with_defaults(options: dict[str, Any]) -> dict[str, Any]:
    defaults = build_default_options()
    defaults.update(
        {
            key: value
            for key, value in options.items()
            if key in defaults
        }
    )
    if not isinstance(defaults[OPTION_CHILDREN], list):
        defaults[OPTION_CHILDREN] = []
    if not isinstance(defaults[OPTION_SHARED_SOURCE], bool):
        defaults[OPTION_SHARED_SOURCE] = True
    return defaults


def _children_from_options(children: list[Any]) -> list[Child]:
    configured_children: list[Child] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        name = child.get("name")
        slug = child.get("slug")
        if not isinstance(name, str) or not isinstance(slug, str):
            continue
        if not name or not slug:
            continue
        configured_children.append(
            Child(
                child_key=slug,
                display_name=name,
                source_kind="shared",
            )
        )
    return configured_children
