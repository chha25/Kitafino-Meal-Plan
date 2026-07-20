"""Sensor platform for Speiseplan."""

from __future__ import annotations

from typing import Any

from .const import (
    CHILD_CURRENT_ENTITY_ID_TEMPLATE,
    DOMAIN,
    SHARED_CURRENT_ENTITY_ID_TEMPLATE,
    WEEKDAYS,
)
from .models import MealEntry, MealPlanSnapshot
from .services import COORDINATOR_KEY

try:
    from homeassistant.components.sensor import SensorEntity
except ModuleNotFoundError:  # pragma: no cover - local tests without HA installed
    SensorEntity = object  # type: ignore[assignment,misc]

HEALTH_ENTITY_ID = "sensor.speiseplan_health"


class SpeiseplanHealthSensor(SensorEntity):  # type: ignore[misc]
    """Integration health and freshness sensor."""

    def __init__(self, *, coordinator: Any, child_slug: str | None = None) -> None:
        """Create a health sensor reading coordinator snapshot state."""
        self.coordinator = coordinator
        self.child_slug = child_slug
        self._attr_entity_id = (
            f"sensor.speiseplan_{child_slug}_health" if child_slug else HEALTH_ENTITY_ID
        )
        self._attr_unique_id = (
            f"speiseplan_{child_slug}_health" if child_slug else "speiseplan_health"
        )
        self._attr_name = (
            f"Speiseplan {child_slug} Health" if child_slug else "Speiseplan Health"
        )

    @property
    def entity_id(self) -> str:
        """Return the stable entity ID."""
        return self._attr_entity_id

    @entity_id.setter
    def entity_id(self, value: str) -> None:
        """Allow Home Assistant to assign the entity registry ID."""
        self._attr_entity_id = value

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
            attributes = {
                "last_successful_update": None,
                "last_error": None,
                "configured_child_count": 0,
                "shared_source": self.child_slug is None,
                "parser_version": None,
                "fetched_at": None,
            }
            if self.child_slug is not None:
                attributes["child_key"] = self.child_slug
            return attributes

        attributes = {
            "last_successful_update": snapshot.last_successful_update,
            "last_error": snapshot.health.last_error,
            "configured_child_count": len(snapshot.children),
            "shared_source": snapshot.shared_source,
            "parser_version": snapshot.parser_version,
            "fetched_at": snapshot.fetched_at,
        }
        if self.child_slug is not None:
            attributes["child_key"] = self.child_slug
            attributes["shared_source"] = False
        return attributes

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

    @entity_id.setter
    def entity_id(self, value: str) -> None:
        """Allow Home Assistant to assign the entity registry ID."""
        self._attr_entity_id = value

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


class SpeiseplanChildCurrentMealSensor(SpeiseplanSharedCurrentMealSensor):
    """Current-week sensor owned by one child config entry."""

    def __init__(self, *, coordinator: Any, weekday: str, child_slug: str) -> None:
        super().__init__(coordinator=coordinator, weekday=weekday)
        self.child_slug = child_slug
        self._attr_entity_id = CHILD_CURRENT_ENTITY_ID_TEMPLATE.format(
            slug=child_slug,
            weekday=weekday,
        )
        self._attr_unique_id = f"speiseplan_{child_slug}_current_{weekday}"
        self._attr_name = f"Speiseplan {child_slug} Current Week {weekday.title()}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Always retain child ownership, including unavailable states."""
        attributes = super().extra_state_attributes
        if self._entry is None:
            return {
                **attributes,
                "child_key": self.child_slug,
                "shared_source": False,
            }
        return attributes

    @property
    def _entry(self) -> MealEntry | None:
        snapshot = self._snapshot
        if snapshot is None:
            return None
        for entry in snapshot.entries:
            if (
                not entry.shared_source
                and entry.child_key == self.child_slug
                and entry.week_kind == "current"
                and entry.weekday == self.weekday
            ):
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
    child_slug = getattr(coordinator, "child_slug", None)
    if isinstance(child_slug, str) and child_slug:
        return [
            SpeiseplanHealthSensor(coordinator=coordinator, child_slug=child_slug),
            *[
                SpeiseplanChildCurrentMealSensor(
                    coordinator=coordinator,
                    weekday=weekday,
                    child_slug=child_slug,
                )
                for weekday in WEEKDAYS
            ],
        ]
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
