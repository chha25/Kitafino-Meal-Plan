"""Tests for sensor naming scaffold."""

from __future__ import annotations

from custom_components.speiseplan.const import (
    SHARED_CURRENT_ENTITY_ID_TEMPLATE,
    WEEKDAYS,
)


def test_shared_current_entity_id_template_is_stable() -> None:
    assert "monday" in WEEKDAYS
    assert (
        SHARED_CURRENT_ENTITY_ID_TEMPLATE.format(weekday="monday")
        == "sensor.speiseplan_shared_current_monday"
    )
