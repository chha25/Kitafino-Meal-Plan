"""Tests for coordinator refresh, stale policy, and snapshot cache."""

from __future__ import annotations

import asyncio
import json

import pytest

from custom_components.speiseplan.const import FORBIDDEN_SECRET_MARKERS
from custom_components.speiseplan.coordinator import (
    SpeiseplanDataUpdateCoordinator,
)
from custom_components.speiseplan.kitafino.errors import (
    KitafinoCannotConnectError,
    KitafinoInvalidAuthError,
    KitafinoParseError,
)
from custom_components.speiseplan.models import Child, MealEntry, MealPlanSnapshot
from custom_components.speiseplan.storage import SnapshotStore


FETCHED_AT = "2026-07-12T06:00:00+02:00"
SECOND_FETCHED_AT = "2026-07-12T07:00:00+02:00"
RAW_HTML = "<html>RAW_KITAFINO_HTML_CAPTURE parent@example.test</html>"


class SequenceClock:
    """Deterministic timestamp source."""

    def __init__(self, *values: str) -> None:
        self._values = list(values)

    def __call__(self) -> str:
        if not self._values:
            raise AssertionError("Clock exhausted")
        return self._values.pop(0)


def _entry(*, fetched_at: str = FETCHED_AT, stale: bool = False) -> MealEntry:
    return MealEntry(
        child_key="shared",
        week_kind="current",
        iso_year=2026,
        iso_week=29,
        weekday="monday",
        meal_text="Pasta",
        source_date=None,
        fetched_at=fetched_at,
        stale=stale,
        shared_source=True,
    )


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


def test_successful_refresh_stores_fresh_snapshot_and_sanitized_cache() -> None:
    store = SnapshotStore()

    async def fetch_source() -> str:
        return RAW_HTML

    def parse_source(source: str, *, fetched_at: str) -> list[MealEntry]:
        assert source == RAW_HTML
        return [_entry(fetched_at=fetched_at)]

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=fetch_source,
        parse_source=parse_source,
        store=store,
        clock=SequenceClock(FETCHED_AT),
        children=[Child(child_key="kind_1", display_name="Kind 1")],
        parser_version="kitafino-html-v1",
    )

    snapshot = _run(coordinator.async_refresh())

    assert isinstance(snapshot, MealPlanSnapshot)
    assert coordinator.snapshot == snapshot
    assert snapshot.health.state == "ok"
    assert snapshot.health.last_error is None
    assert snapshot.children == [Child(child_key="kind_1", display_name="Kind 1")]
    assert snapshot.entries == [_entry()]
    assert snapshot.last_successful_update == FETCHED_AT
    assert snapshot.parser_version == "kitafino-html-v1"

    cached = _run(store.async_load())
    assert cached is not None
    assert cached.children == []
    assert cached.entries == snapshot.entries
    assert cached.health == snapshot.health
    serialized_cache = json.dumps(store.raw_data, sort_keys=True)
    assert RAW_HTML not in serialized_cache
    assert "parent@example.test" not in serialized_cache
    assert "Kind 1" not in serialized_cache
    assert "kind_1" not in serialized_cache


@pytest.mark.parametrize(
    ("exception", "expected_error"),
    [
        (KitafinoInvalidAuthError(), "login_failed"),
        (KitafinoCannotConnectError(), "network_error"),
        (KitafinoParseError(), "parse_error"),
        (RuntimeError("boom RAW_KITAFINO_HTML_CAPTURE"), "unknown_error"),
    ],
)
def test_failed_refresh_with_prior_snapshot_keeps_entries_as_stale(
    exception: Exception,
    expected_error: str,
) -> None:
    store = SnapshotStore()

    async def successful_fetch() -> str:
        return RAW_HTML

    def parse_source(source: str, *, fetched_at: str) -> list[MealEntry]:
        return [_entry(fetched_at=fetched_at)]

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=successful_fetch,
        parse_source=parse_source,
        store=store,
        clock=SequenceClock(FETCHED_AT, SECOND_FETCHED_AT),
    )
    _run(coordinator.async_refresh())

    async def failing_fetch() -> str:
        raise exception

    coordinator.fetch_source = failing_fetch
    stale_snapshot = _run(coordinator.async_refresh())

    assert stale_snapshot.health.state == "stale"
    assert stale_snapshot.health.last_error == expected_error
    assert stale_snapshot.health.last_successful_update == FETCHED_AT
    assert stale_snapshot.fetched_at == SECOND_FETCHED_AT
    assert stale_snapshot.last_successful_update == FETCHED_AT
    assert stale_snapshot.entries == [_entry(stale=True)]
    assert _run(store.async_load()).health.state == "ok"


@pytest.mark.parametrize(
    ("exception", "expected_state"),
    [
        (KitafinoInvalidAuthError(), "login_failed"),
        (KitafinoCannotConnectError(), "network_error"),
        (KitafinoParseError(), "parse_error"),
        (RuntimeError("boom RAW_KITAFINO_HTML_CAPTURE"), "unknown_error"),
    ],
)
def test_failed_refresh_without_prior_snapshot_exposes_error_health(
    exception: Exception,
    expected_state: str,
) -> None:
    async def failing_fetch() -> str:
        raise exception

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=failing_fetch,
        parse_source=lambda source, *, fetched_at: [],
        store=SnapshotStore(),
        clock=SequenceClock(FETCHED_AT),
    )

    snapshot = _run(coordinator.async_refresh())

    assert snapshot.health.state == expected_state
    assert snapshot.health.last_error == expected_state
    assert snapshot.entries == []
    assert RAW_HTML not in json.dumps(snapshot.to_dict(), sort_keys=True)


def test_coordinator_restores_sanitized_cached_snapshot() -> None:
    store = SnapshotStore()
    expected = MealPlanSnapshot.empty(fetched_at=FETCHED_AT, health_state="ok")
    _run(store.async_save(expected))

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=lambda: RAW_HTML,
        parse_source=lambda source, *, fetched_at: [],
        store=store,
        clock=SequenceClock(FETCHED_AT),
    )

    restored = _run(coordinator.async_load_cached_snapshot())

    assert restored == expected
    assert coordinator.snapshot == expected


def test_store_rejects_malformed_snapshot_data() -> None:
    store = SnapshotStore(raw_data={"health": "broken", "shared_source": True})

    with pytest.raises(ValueError):
        _run(store.async_load())


def test_public_snapshot_and_cache_are_secret_safe() -> None:
    store = SnapshotStore()

    async def fetch_source() -> str:
        return "REAL_KITAFINO_PASSWORD_VALUE RAW_KITAFINO_HTML_CAPTURE"

    def parse_source(source: str, *, fetched_at: str) -> list[MealEntry]:
        return [_entry(fetched_at=fetched_at)]

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=fetch_source,
        parse_source=parse_source,
        store=store,
        clock=SequenceClock(FETCHED_AT),
    )

    snapshot = _run(coordinator.async_refresh())
    public_data = json.dumps(
        {
            "snapshot": snapshot.to_dict(),
            "cache": store.raw_data,
        },
        sort_keys=True,
    )

    for marker in FORBIDDEN_SECRET_MARKERS:
        assert marker not in public_data
    assert "username" not in public_data.lower()
    assert "password" not in public_data.lower()
    assert "cookie" not in public_data.lower()
    assert "raw_html" not in public_data.lower()
    assert "account_id" not in public_data.lower()
