"""Sensor platform for Speiseplan."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN, SHARED_CURRENT_ENTITY_ID_TEMPLATE, WEEKDAYS
from .models import MealEntry, MealPlanSnapshot
from .services import COORDINATOR_KEY

try:
    from homeassistant.components.sensor import SensorEntity
except ModuleNotFoundError:  # pragma: no cover - local tests without HA installed
    SensorEntity = object  # type: ignore[assignment,misc]

HEALTH_ENTITY_ID = "sensor.speiseplan_health"


class SpeiseplanHealthSensor(SensorEntity):  # type: ignore[misc]
    """Integration health and freshness sensor."""

    def __init__(self, *, coordinator: Any) -> None:
        """Create a health sensor reading coordinator snapshot state."""
        self.coordinator = coordinator
        self._attr_entity_id = HEALTH_ENTITY_ID
        self._attr_unique_id = "speiseplan_health"
        self._attr_name = "Speiseplan Health"

    @property
    def entity_id(self) -> str:
        """Return the stable entity ID."""
        return self._attr_entity_id

    @property
    def unique_id(self) -> str:
        """Return the stable unique ID."""
        return self._attr_unique_id

    @property
    def name(self) -> str:
        """Return the friendly name."""
        return self._attr_name

    @property
    def native_value(self) -> str | None:
        """Return the current health state."""
        snapshot = self._snapshot
        if snapshot is None:
            return None
        return snapshot.health.state

    @property
    def available(self) -> bool:
        """Return whether health state is available."""
        return self._snapshot is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return safe health and freshness attributes."""
        snapshot = self._snapshot
        if snapshot is None:
            return {
                "last_successful_update": None,
                "last_error": None,
                "configured_child_count": 0,
                "shared_source": True,
                "parser_version": None,
                "fetched_at": None,
            }

        return {
            "last_successful_update": snapshot.last_successful_update,
            "last_error": snapshot.health.last_error,
            "configured_child_count": len(snapshot.children),
            "shared_source": snapshot.shared_source,
            "parser_version": snapshot.parser_version,
            "fetched_at": snapshot.fetched_at,
        }

    @property
    def _snapshot(self) -> MealPlanSnapshot | None:
        snapshot = getattr(self.coordinator, "snapshot", None)
        if isinstance(snapshot, MealPlanSnapshot):
            return snapshot
        return None


class SpeiseplanSharedCurrentMealSensor(SensorEntity):  # type: ignore[misc]
    """Shared-source current-week meal sensor."""

    def __init__(self, *, coordinator: Any, weekday: str) -> None:
        """Create a sensor for one shared current-week weekday."""
        self.coordinator = coordinator
        self.weekday = weekday
        self._attr_entity_id = SHARED_CURRENT_ENTITY_ID_TEMPLATE.format(
            weekday=weekday,
        )
        self._attr_unique_id = f"speiseplan_shared_current_{weekday}"
        self._attr_name = f"Speiseplan Shared Current Week {weekday.title()}"

    @property
    def entity_id(self) -> str:
        """Return the stable entity ID."""
        return self._attr_entity_id

    @property
    def unique_id(self) -> str:
        """Return the stable unique ID."""
        return self._attr_unique_id

    @property
    def name(self) -> str:
        """Return the friendly name."""
        return self._attr_name

    @property
    def native_value(self) -> str | None:
        """Return the meal text for this weekday."""
        entry = self._entry
        if entry is None:
            return None
        return entry.meal_text

    @property
    def available(self) -> bool:
        """Return whether this weekday has current meal data."""
        return self._entry is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return safe meal metadata attributes."""
        snapshot = self._snapshot
        entry = self._entry
        if entry is None:
            return {
                "weekday": self.weekday,
                "week_kind": "current",
                "shared_source": True,
                "stale": None,
                "last_successful_update": (
                    snapshot.last_successful_update if snapshot is not None else None
                ),
            }

        return {
            "child_key": entry.child_key,
            "week_kind": entry.week_kind,
            "iso_year": entry.iso_year,
            "iso_week": entry.iso_week,
            "weekday": entry.weekday,
            "source_date": entry.source_date,
            "last_successful_update": (
                snapshot.last_successful_update if snapshot is not None else None
            ),
            "stale": entry.stale,
            "shared_source": entry.shared_source,
        }

    @property
    def _snapshot(self) -> MealPlanSnapshot | None:
        snapshot = getattr(self.coordinator, "snapshot", None)
        if isinstance(snapshot, MealPlanSnapshot):
            return snapshot
        return None

    @property
    def _entry(self) -> MealEntry | None:
        snapshot = self._snapshot
        if snapshot is None:
            return None
        for entry in snapshot.entries:
            if entry.is_shared_current and entry.weekday == self.weekday:
                return entry
        return None


def build_shared_current_meal_sensors(
    coordinator: Any,
) -> list[SpeiseplanSharedCurrentMealSensor]:
    """Build one shared current-week meal sensor per weekday."""
    return [
        SpeiseplanSharedCurrentMealSensor(
            coordinator=coordinator,
            weekday=weekday,
        )
        for weekday in WEEKDAYS
    ]


def build_sensors(coordinator: Any) -> list[Any]:
    """Build all Speiseplan sensors for one coordinator."""
    return [
        SpeiseplanHealthSensor(coordinator=coordinator),
        *build_shared_current_meal_sensors(coordinator),
    ]


async def async_setup_entry(
    hass: Any,
    entry: Any,
    async_add_entities: Any,
) -> None:
    """Set up Speiseplan sensors for a config entry."""
    domain_data = getattr(hass, "data", {}).get(DOMAIN, {})
    entry_data = domain_data.get(entry.entry_id, {}) if isinstance(domain_data, dict) else {}
    coordinator = (
        entry_data.get(COORDINATOR_KEY) if isinstance(entry_data, dict) else None
    )
    if coordinator is None:
        async_add_entities([])
        return

    async_add_entities(build_sensors(coordinator))
