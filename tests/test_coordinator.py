"""Tests for coordinator scaffold import safety."""

from __future__ import annotations


def test_coordinator_scaffold_imports() -> None:
    from custom_components.speiseplan.coordinator import (
        SpeiseplanDataUpdateCoordinator,
    )

    assert SpeiseplanDataUpdateCoordinator.__name__ == "SpeiseplanDataUpdateCoordinator"


def test_stale_data_policy_scaffold_is_represented() -> None:
    from custom_components.speiseplan.coordinator import (
        SpeiseplanDataUpdateCoordinator,
    )

    assert "stale-state behavior" in SpeiseplanDataUpdateCoordinator.__doc__
