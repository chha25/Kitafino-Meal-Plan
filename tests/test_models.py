"""Tests for canonical Speiseplan meal-plan models."""

from __future__ import annotations

import json

import pytest

from custom_components.speiseplan.const import FORBIDDEN_SECRET_MARKERS
from custom_components.speiseplan.kitafino.errors import (
    ERROR_LOGIN_FAILED,
    ERROR_NETWORK,
    ERROR_PARSE,
    ERROR_UNKNOWN,
    KitafinoCannotConnectError,
    KitafinoInvalidAuthError,
    KitafinoParseError,
    KitafinoUnknownError,
    error_code,
)
from custom_components.speiseplan.models import (
    Child,
    HealthStatus,
    MealEntry,
    MealPlanSnapshot,
)


FETCHED_AT = "2026-07-01T06:00:00+02:00"


def test_meal_entry_serializes_required_fields() -> None:
    entry = MealEntry(
        child_key="shared",
        week_kind="current",
        iso_year=2026,
        iso_week=27,
        weekday="monday",
        meal_text="Pasta with tomato sauce",
        source_date="2026-07-01",
        fetched_at=FETCHED_AT,
        stale=False,
        shared_source=True,
    )

    assert entry.to_dict() == {
        "child_key": "shared",
        "week_kind": "current",
        "iso_year": 2026,
        "iso_week": 27,
        "weekday": "monday",
        "meal_text": "Pasta with tomato sauce",
        "source_date": "2026-07-01",
        "fetched_at": FETCHED_AT,
        "stale": False,
        "shared_source": True,
    }
    assert MealEntry.from_dict(entry.to_dict()) == entry


def test_snapshot_round_trip_preserves_public_data() -> None:
    snapshot = MealPlanSnapshot(
        health=HealthStatus(
            state="ok",
            last_error=None,
            last_successful_update=FETCHED_AT,
            fetched_at=FETCHED_AT,
        ),
        children=[
            Child(child_key="shared", display_name="Shared", source_kind="shared")
        ],
        entries=[
            MealEntry(
                child_key="shared",
                week_kind="current",
                iso_year=2026,
                iso_week=27,
                weekday="tuesday",
                meal_text="Rice and vegetables",
                source_date=None,
                fetched_at=FETCHED_AT,
                stale=False,
                shared_source=True,
            )
        ],
        fetched_at=FETCHED_AT,
        last_successful_update=FETCHED_AT,
        shared_source=True,
        parser_version="kitafino-html-v1",
    )

    serialized = snapshot.to_dict()

    assert MealPlanSnapshot.from_dict(serialized) == snapshot
    assert json.loads(json.dumps(serialized)) == serialized


def test_snapshot_distinguishes_shared_current_and_future_child_entries() -> None:
    shared_current = MealEntry(
        child_key="shared",
        week_kind="current",
        iso_year=2026,
        iso_week=27,
        weekday="wednesday",
        meal_text="Soup",
        source_date=None,
        fetched_at=FETCHED_AT,
        stale=False,
        shared_source=True,
    )
    child_next = MealEntry(
        child_key="kind_1",
        week_kind="next",
        iso_year=2026,
        iso_week=28,
        weekday="wednesday",
        meal_text="Future meal",
        source_date=None,
        fetched_at=FETCHED_AT,
        stale=False,
        shared_source=False,
    )

    assert shared_current.is_shared_current is True
    assert child_next.is_shared_current is False
    assert child_next.week_kind == "next"
    assert child_next.child_key == "kind_1"


def test_serialized_snapshot_contains_no_forbidden_secret_markers() -> None:
    snapshot = MealPlanSnapshot.empty(
        fetched_at=FETCHED_AT,
        health_state="unknown_error",
        last_error="unknown_error",
    )
    serialized = json.dumps(snapshot.to_dict(), sort_keys=True)

    for marker in FORBIDDEN_SECRET_MARKERS:
        assert marker not in serialized
    assert "username" not in serialized.lower()
    assert "password" not in serialized.lower()
    assert "cookie" not in serialized.lower()
    assert "raw_html" not in serialized.lower()
    assert "account_id" not in serialized.lower()


def test_model_deserialization_rejects_invalid_enum_values() -> None:
    invalid = {
        "child_key": "shared",
        "week_kind": "future",
        "iso_year": 2026,
        "iso_week": 27,
        "weekday": "monday",
        "meal_text": "Meal",
        "source_date": None,
        "fetched_at": FETCHED_AT,
        "stale": False,
        "shared_source": True,
    }

    try:
        MealEntry.from_dict(invalid)
    except ValueError as err:
        assert "week_kind" in str(err)
    else:
        raise AssertionError("MealEntry.from_dict accepted invalid week_kind")


def test_model_constructors_reject_invalid_public_state() -> None:
    with pytest.raises(ValueError, match="child_key"):
        Child(child_key="", display_name="Shared", source_kind="shared")

    with pytest.raises(ValueError, match="iso_year"):
        MealEntry(
            child_key="shared",
            week_kind="current",
            iso_year=False,
            iso_week=27,
            weekday="monday",
            meal_text="Meal",
            source_date=None,
            fetched_at=FETCHED_AT,
            stale=False,
            shared_source=True,
        )

    with pytest.raises(ValueError, match="stale"):
        MealEntry(
            child_key="shared",
            week_kind="current",
            iso_year=2026,
            iso_week=27,
            weekday="monday",
            meal_text="Meal",
            source_date=None,
            fetched_at=FETCHED_AT,
            stale="false",
            shared_source=True,
        )


def test_snapshot_deserialization_rejects_malformed_list_items() -> None:
    snapshot = MealPlanSnapshot.empty(
        fetched_at=FETCHED_AT,
        health_state="ok",
    ).to_dict()
    snapshot["children"] = ["not-a-child"]

    with pytest.raises(ValueError, match="children"):
        MealPlanSnapshot.from_dict(snapshot)

    snapshot = MealPlanSnapshot.empty(
        fetched_at=FETCHED_AT,
        health_state="ok",
    ).to_dict()
    snapshot["entries"] = ["not-an-entry"]

    with pytest.raises(ValueError, match="entries"):
        MealPlanSnapshot.from_dict(snapshot)


def test_snapshot_deserialization_uses_safe_public_defaults() -> None:
    child = Child(child_key="shared", display_name="Shared").to_dict()
    child.pop("source_kind")
    snapshot = MealPlanSnapshot.empty(
        fetched_at=FETCHED_AT,
        health_state="ok",
    ).to_dict()
    snapshot["children"] = [child]
    snapshot.pop("shared_source")

    deserialized = MealPlanSnapshot.from_dict(snapshot)

    assert deserialized.shared_source is True
    assert deserialized.children[0].source_kind == "shared"


def test_unknown_secret_bearing_input_fields_are_not_serialized() -> None:
    snapshot = MealPlanSnapshot.empty(
        fetched_at=FETCHED_AT,
        health_state="ok",
    ).to_dict()
    snapshot["username"] = "REAL_KITAFINO_PASSWORD_VALUE"
    snapshot["raw_html"] = "RAW_KITAFINO_HTML_CAPTURE"
    snapshot["children"] = [
        {
            "child_key": "shared",
            "display_name": "Shared",
            "source_kind": "shared",
            "account_id": "REAL_ACCOUNT_ID_VALUE",
        }
    ]

    serialized = json.dumps(
        MealPlanSnapshot.from_dict(snapshot).to_dict(),
        sort_keys=True,
    )

    assert "username" not in serialized.lower()
    assert "raw_html" not in serialized.lower()
    assert "account_id" not in serialized.lower()
    for marker in FORBIDDEN_SECRET_MARKERS:
        assert marker not in serialized


def test_kitafino_errors_map_to_stable_failure_codes() -> None:
    assert error_code(KitafinoInvalidAuthError()) == ERROR_LOGIN_FAILED
    assert error_code(KitafinoCannotConnectError()) == ERROR_NETWORK
    assert error_code(KitafinoParseError()) == ERROR_PARSE
    assert error_code(KitafinoUnknownError()) == ERROR_UNKNOWN
    assert error_code(RuntimeError("boom")) == ERROR_UNKNOWN
