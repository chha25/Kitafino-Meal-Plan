"""Canonical model contract for Speiseplan meal-plan data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .kitafino.errors import (
    ERROR_LOGIN_FAILED,
    ERROR_NETWORK,
    ERROR_PARSE,
    ERROR_UNKNOWN,
)

WEEK_KINDS = ("current", "next")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")
SOURCE_KINDS = ("shared", "child")
HEALTH_STATES = (
    "ok",
    "stale",
    "login_failed",
    "network_error",
    "parse_error",
    "unknown_error",
)
ERROR_CODES = (ERROR_LOGIN_FAILED, ERROR_NETWORK, ERROR_PARSE, ERROR_UNKNOWN)


def _validate_str(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _validate_optional_str(value: Any, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string or None")
    return value


def _validate_int(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _validate_bool(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _require_str(data: dict[str, Any], key: str) -> str:
    return _validate_str(data.get(key), key)


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    return _validate_optional_str(data.get(key), key)


def _require_int(data: dict[str, Any], key: str) -> int:
    return _validate_int(data.get(key), key)


def _require_bool(data: dict[str, Any], key: str) -> bool:
    return _validate_bool(data.get(key), key)


def _validate_choice(value: str, key: str, choices: tuple[str, ...]) -> str:
    if value not in choices:
        raise ValueError(f"{key} must be one of: {', '.join(choices)}")
    return value


def _require_dict_items(items: list[Any], key: str) -> list[dict[str, Any]]:
    invalid_indexes = [
        index for index, item in enumerate(items) if not isinstance(item, dict)
    ]
    if invalid_indexes:
        raise ValueError(f"{key} items must be dictionaries")
    return items


@dataclass(frozen=True)
class Child:
    """Configured child label metadata."""

    child_key: str
    display_name: str
    source_kind: str = "shared"

    def __post_init__(self) -> None:
        """Validate child metadata."""
        _validate_str(self.child_key, "child_key")
        _validate_str(self.display_name, "display_name")
        _validate_choice(
            _validate_str(self.source_kind, "source_kind"),
            "source_kind",
            SOURCE_KINDS,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize child metadata."""
        return {
            "child_key": self.child_key,
            "display_name": self.display_name,
            "source_kind": self.source_kind,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Child:
        """Deserialize child metadata."""
        source_kind_value = data.get("source_kind", "shared")
        source_kind = _validate_choice(
            _validate_str(source_kind_value, "source_kind"),
            "source_kind",
            SOURCE_KINDS,
        )
        return cls(
            child_key=_require_str(data, "child_key"),
            display_name=_require_str(data, "display_name"),
            source_kind=source_kind,
        )


@dataclass(frozen=True)
class MealEntry:
    """A normalized meal-plan entry for one source, week, and weekday."""

    child_key: str
    week_kind: str
    iso_year: int
    iso_week: int
    weekday: str
    meal_text: str
    source_date: str | None
    fetched_at: str
    stale: bool
    shared_source: bool

    def __post_init__(self) -> None:
        """Validate entry dimensions."""
        _validate_str(self.child_key, "child_key")
        _validate_choice(
            _validate_str(self.week_kind, "week_kind"),
            "week_kind",
            WEEK_KINDS,
        )
        _validate_int(self.iso_year, "iso_year")
        _validate_int(self.iso_week, "iso_week")
        _validate_choice(_validate_str(self.weekday, "weekday"), "weekday", WEEKDAYS)
        _validate_str(self.meal_text, "meal_text")
        _validate_optional_str(self.source_date, "source_date")
        _validate_str(self.fetched_at, "fetched_at")
        _validate_bool(self.stale, "stale")
        _validate_bool(self.shared_source, "shared_source")
        if self.iso_year < 1:
            raise ValueError("iso_year must be greater than 0")
        if self.iso_week < 1 or self.iso_week > 53:
            raise ValueError("iso_week must be between 1 and 53")

    @property
    def is_shared_current(self) -> bool:
        """Return whether this entry is part of the MVP shared current week set."""
        return self.shared_source and self.child_key == "shared" and self.week_kind == "current"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entry to a deterministic dictionary."""
        return {
            "child_key": self.child_key,
            "week_kind": self.week_kind,
            "iso_year": self.iso_year,
            "iso_week": self.iso_week,
            "weekday": self.weekday,
            "meal_text": self.meal_text,
            "source_date": self.source_date,
            "fetched_at": self.fetched_at,
            "stale": self.stale,
            "shared_source": self.shared_source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MealEntry:
        """Deserialize a meal entry."""
        week_kind = _validate_choice(
            _require_str(data, "week_kind"),
            "week_kind",
            WEEK_KINDS,
        )
        weekday = _validate_choice(_require_str(data, "weekday"), "weekday", WEEKDAYS)
        return cls(
            child_key=_require_str(data, "child_key"),
            week_kind=week_kind,
            iso_year=_require_int(data, "iso_year"),
            iso_week=_require_int(data, "iso_week"),
            weekday=weekday,
            meal_text=_require_str(data, "meal_text"),
            source_date=_optional_str(data, "source_date"),
            fetched_at=_require_str(data, "fetched_at"),
            stale=_require_bool(data, "stale"),
            shared_source=_require_bool(data, "shared_source"),
        )


@dataclass(frozen=True)
class HealthStatus:
    """Health and freshness metadata for the snapshot."""

    state: str
    last_error: str | None = None
    last_successful_update: str | None = None
    fetched_at: str | None = None

    def __post_init__(self) -> None:
        """Validate health status fields."""
        _validate_choice(_validate_str(self.state, "state"), "state", HEALTH_STATES)
        _validate_optional_str(
            self.last_successful_update,
            "last_successful_update",
        )
        _validate_optional_str(self.fetched_at, "fetched_at")
        if self.last_error is not None:
            _validate_choice(
                _validate_str(self.last_error, "last_error"),
                "last_error",
                ERROR_CODES,
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize health metadata."""
        return {
            "state": self.state,
            "last_error": self.last_error,
            "last_successful_update": self.last_successful_update,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HealthStatus:
        """Deserialize health metadata."""
        return cls(
            state=_validate_choice(_require_str(data, "state"), "state", HEALTH_STATES),
            last_error=_optional_str(data, "last_error"),
            last_successful_update=_optional_str(data, "last_successful_update"),
            fetched_at=_optional_str(data, "fetched_at"),
        )


@dataclass(frozen=True)
class MealPlanSnapshot:
    """Canonical cross-layer meal-plan snapshot."""

    health: HealthStatus
    children: list[Child] = field(default_factory=list)
    entries: list[MealEntry] = field(default_factory=list)
    fetched_at: str | None = None
    last_successful_update: str | None = None
    shared_source: bool = True
    parser_version: str | None = None

    def __post_init__(self) -> None:
        """Validate snapshot composition."""
        if not isinstance(self.health, HealthStatus):
            raise ValueError("health must be a HealthStatus")
        if not isinstance(self.children, list):
            raise ValueError("children must be a list")
        if not all(isinstance(child, Child) for child in self.children):
            raise ValueError("children items must be Child instances")
        if not isinstance(self.entries, list):
            raise ValueError("entries must be a list")
        if not all(isinstance(entry, MealEntry) for entry in self.entries):
            raise ValueError("entries items must be MealEntry instances")
        _validate_optional_str(self.fetched_at, "fetched_at")
        _validate_optional_str(
            self.last_successful_update,
            "last_successful_update",
        )
        _validate_bool(self.shared_source, "shared_source")
        _validate_optional_str(self.parser_version, "parser_version")

    def to_dict(self) -> dict[str, Any]:
        """Serialize snapshot data for storage, diagnostics, sensors, and MQTT."""
        return {
            "health": self.health.to_dict(),
            "children": [child.to_dict() for child in self.children],
            "entries": [entry.to_dict() for entry in self.entries],
            "fetched_at": self.fetched_at,
            "last_successful_update": self.last_successful_update,
            "shared_source": self.shared_source,
            "parser_version": self.parser_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MealPlanSnapshot:
        """Deserialize a snapshot."""
        health_data = data.get("health")
        if not isinstance(health_data, dict):
            raise ValueError("health must be a dictionary")

        children_data = data.get("children", [])
        entries_data = data.get("entries", [])
        if not isinstance(children_data, list):
            raise ValueError("children must be a list")
        if not isinstance(entries_data, list):
            raise ValueError("entries must be a list")

        return cls(
            health=HealthStatus.from_dict(health_data),
            children=[
                Child.from_dict(child)
                for child in _require_dict_items(children_data, "children")
            ],
            entries=[
                MealEntry.from_dict(entry)
                for entry in _require_dict_items(entries_data, "entries")
            ],
            fetched_at=_optional_str(data, "fetched_at"),
            last_successful_update=_optional_str(data, "last_successful_update"),
            shared_source=_validate_bool(data.get("shared_source", True), "shared_source"),
            parser_version=_optional_str(data, "parser_version"),
        )

    @classmethod
    def empty(
        cls,
        *,
        fetched_at: str | None,
        health_state: str,
        last_error: str | None = None,
    ) -> MealPlanSnapshot:
        """Build an empty snapshot with health metadata."""
        return cls(
            health=HealthStatus(
                state=health_state,
                last_error=last_error,
                fetched_at=fetched_at,
            ),
            fetched_at=fetched_at,
            shared_source=True,
        )
