"""Speiseplan Home Assistant integration skeleton."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

try:
    from homeassistant.helpers.event import async_track_time_change
except ModuleNotFoundError:  # pragma: no cover - local tests without HA installed
    async_track_time_change = None  # type: ignore[assignment]

from .config_flow import build_default_options, normalize_child_slug
from .const import (
    CONF_CHILD_SLUG,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    OPTION_CHILDREN,
    OPTION_SHARED_SOURCE,
    OPTION_UPDATE_TIME,
)
from .coordinator import SpeiseplanDataUpdateCoordinator
from .kitafino.client import KitafinoClient, KitafinoTransport
from .kitafino.parser import KitafinoParser
from .models import Child
from .mqtt import async_schedule_publish_if_enabled
from .services import COORDINATOR_KEY, async_setup_services
from .storage import SnapshotStore

PLATFORMS: tuple[str, ...] = ("sensor",)
SCHEDULE_UNSUB_KEY = "schedule_unsub"
OPTIONS_UNSUB_KEY = "options_unsub"


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
    snapshot = await coordinator.async_refresh(phase="setup")
    runtime_data = {
        "entry": entry,
        COORDINATOR_KEY: coordinator,
    }
    hass.data[DOMAIN][entry.entry_id] = runtime_data
    try:
        schedule_unsub = _schedule_daily_refresh(hass, entry, coordinator)
        if schedule_unsub is not None:
            runtime_data[SCHEDULE_UNSUB_KEY] = schedule_unsub
        add_update_listener = getattr(entry, "add_update_listener", None)
        if callable(add_update_listener):
            runtime_data[OPTIONS_UNSUB_KEY] = add_update_listener(_async_reload_entry)
        await async_setup_services(hass)
        config_entries = getattr(hass, "config_entries", None)
        forward_setups = getattr(config_entries, "async_forward_entry_setups", None)
        if callable(forward_setups):
            await forward_setups(entry, PLATFORMS)
        coordinator.snapshot_update_callback = (
            lambda updated_snapshot: async_schedule_publish_if_enabled(
                hass,
                entry,
                updated_snapshot,
            )
        )
        await async_schedule_publish_if_enabled(hass, entry, snapshot)
    except Exception:
        _cleanup_runtime_callbacks(runtime_data)
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload a Speiseplan config entry."""
    config_entries = getattr(hass, "config_entries", None)
    unload_platforms = getattr(config_entries, "async_unload_platforms", None)
    if callable(unload_platforms):
        unload_ok = await unload_platforms(entry, PLATFORMS)
        if not unload_ok:
            return False

    domain_data = hass.data.get(DOMAIN, {})
    runtime_data = domain_data.pop(entry.entry_id, None)
    if isinstance(runtime_data, dict):
        _cleanup_runtime_callbacks(runtime_data)
    return True


def _schedule_daily_refresh(
    hass: Any,
    entry: Any,
    coordinator: SpeiseplanDataUpdateCoordinator,
) -> Any:
    """Schedule one refresh per day in Home Assistant local time."""
    if not hasattr(hass, "bus") or async_track_time_change is None:
        return None

    options = _options_with_defaults(getattr(entry, "options", {}) or {})
    configured_time = time.fromisoformat(options[OPTION_UPDATE_TIME])

    active = True

    async def async_scheduled_refresh(now: datetime) -> None:
        if not active:
            return
        await coordinator.async_refresh(phase="scheduled_refresh")

    unsubscribe_schedule = async_track_time_change(
        hass,
        async_scheduled_refresh,
        hour=configured_time.hour,
        minute=configured_time.minute,
        second=0,
    )

    def unsubscribe() -> None:
        nonlocal active
        active = False
        unsubscribe_schedule()

    return unsubscribe


def _cleanup_runtime_callbacks(runtime_data: dict[str, Any]) -> None:
    """Run all runtime cleanup handles independently."""
    for key in (SCHEDULE_UNSUB_KEY, OPTIONS_UNSUB_KEY):
        unsubscribe = runtime_data.get(key)
        if callable(unsubscribe):
            try:
                unsubscribe()
            except Exception:
                continue


async def _async_reload_entry(hass: Any, entry: Any) -> None:
    """Reload an entry when options such as its daily time change."""
    await hass.config_entries.async_reload(entry.entry_id)


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
    stored_child_slug = data.get(CONF_CHILD_SLUG)
    child_slug = normalize_child_slug(stored_child_slug)
    if CONF_CHILD_SLUG in data and (
        child_slug is None or stored_child_slug != child_slug
    ):
        raise ValueError("Invalid child slug in config entry")
    is_child_entry = child_slug is not None
    if is_child_entry:
        shared_source = False

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
            child_key=child_slug if child_slug is not None else "shared",
            shared_source=shared_source,
        )

    return SpeiseplanDataUpdateCoordinator(
        fetch_source=client.async_fetch_meal_plan_source,
        parse_source=parse_source,
        store=store or SnapshotStore(),
        clock=clock,
        children=(
            [Child(child_key=child_slug, display_name=child_slug, source_kind="child")]
            if child_slug is not None
            else _children_from_options(options[OPTION_CHILDREN])
        ),
        parser_version=parser.parser_version,
        shared_source=shared_source,
        config_entry_id=getattr(entry, "entry_id", None),
        child_slug=child_slug,
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
