"""Tests for coordinator refresh, stale policy, and snapshot cache."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
import logging

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
from custom_components.speiseplan.models import (
    Child,
    HealthStatus,
    MealEntry,
    MealPlanSnapshot,
)
from custom_components.speiseplan.operational_logging import RedactedOperationalLogger
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


def _entry(
    *,
    fetched_at: str = FETCHED_AT,
    stale: bool = False,
    weekday: str = "monday",
    meal_text: str = "Pasta",
    iso_year: int = 2026,
    iso_week: int = 29,
) -> MealEntry:
    return MealEntry(
        child_key="shared",
        week_kind="current",
        iso_year=iso_year,
        iso_week=iso_week,
        weekday=weekday,
        meal_text=meal_text,
        source_date=None,
        fetched_at=fetched_at,
        stale=stale,
        shared_source=True,
    )


def _child_entry(
    child_key: str,
    *,
    fetched_at: str = FETCHED_AT,
    stale: bool = False,
) -> MealEntry:
    return MealEntry(
        child_key=child_key,
        week_kind="current",
        iso_year=2026,
        iso_week=29,
        weekday="monday",
        meal_text=f"{child_key} Pasta",
        source_date=None,
        fetched_at=fetched_at,
        stale=stale,
        shared_source=False,
    )


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


async def _fetch_source() -> str:
    return RAW_HTML


def test_overlapping_refreshes_are_serialized_and_cannot_overwrite_out_of_order() -> None:
    async def scenario() -> None:
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        active_fetches = 0
        max_active_fetches = 0
        sources = iter(("first", "second"))

        async def fetch_source() -> str:
            nonlocal active_fetches, max_active_fetches
            source = next(sources)
            active_fetches += 1
            max_active_fetches = max(max_active_fetches, active_fetches)
            if source == "first":
                first_started.set()
                await release_first.wait()
            active_fetches -= 1
            return source

        def parse_source(source: str, *, fetched_at: str) -> list[MealEntry]:
            return [_entry(fetched_at=fetched_at, meal_text=source)]

        coordinator = SpeiseplanDataUpdateCoordinator(
            fetch_source=fetch_source,
            parse_source=parse_source,
            clock=SequenceClock(FETCHED_AT, SECOND_FETCHED_AT),
        )
        first = asyncio.create_task(coordinator.async_refresh())
        await first_started.wait()
        second = asyncio.create_task(coordinator.async_refresh())
        await asyncio.sleep(0)
        assert max_active_fetches == 1
        release_first.set()
        await asyncio.gather(first, second)

        assert max_active_fetches == 1
        assert coordinator.snapshot is not None
        assert coordinator.snapshot.entries[0].meal_text == "second"

    _run(scenario())


def test_storage_failure_does_not_replace_or_notify_snapshot() -> None:
    prior = MealPlanSnapshot(
        health=HealthStatus(state="ok"),
        entries=[_entry(meal_text="prior")],
    )

    class FailingStore(SnapshotStore):
        async def async_save(self, snapshot: MealPlanSnapshot) -> None:
            raise RuntimeError("storage failed")

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: [
            _entry(fetched_at=fetched_at, meal_text="new")
        ],
        store=FailingStore(),
        clock=SequenceClock(FETCHED_AT),
    )
    coordinator.snapshot = prior
    notifications = 0

    def listener() -> None:
        nonlocal notifications
        notifications += 1

    coordinator.async_add_listener(listener)

    with pytest.raises(RuntimeError, match="storage failed"):
        _run(coordinator.async_refresh())

    assert coordinator.snapshot is prior
    assert notifications == 0


def test_success_is_logged_after_storage_listeners_and_projection() -> None:
    calls: list[str] = []

    class RecordingStore(SnapshotStore):
        async def async_save(self, snapshot: MealPlanSnapshot) -> None:
            calls.append("store")
            await super().async_save(snapshot)

    class RecordingLogger(RedactedOperationalLogger):
        def log_success(self, **kwargs: object) -> bool:
            calls.append("log_success")
            assert kwargs == {
                "entry_id": "entry-1",
                "phase": "manual_refresh",
                "entry_count": 1,
            }
            return True

    async def projection(snapshot: MealPlanSnapshot) -> None:
        calls.append("projection")

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: [_entry(fetched_at=fetched_at)],
        store=RecordingStore(),
        clock=SequenceClock(FETCHED_AT),
        config_entry_id="entry-1",
        operational_logger=RecordingLogger(),
        snapshot_update_callback=projection,
    )
    coordinator.async_add_listener(lambda: calls.append("listener"))

    _run(coordinator.async_refresh(phase="manual_refresh"))

    assert calls == ["store", "listener", "projection", "log_success"]


@pytest.mark.parametrize("failure_point", ["fetch", "parse", "store", "projection"])
def test_exception_before_refresh_completion_prevents_success_log(
    failure_point: str,
) -> None:
    calls: list[str] = []

    class MaybeFailingStore(SnapshotStore):
        async def async_save(self, snapshot: MealPlanSnapshot) -> None:
            if failure_point == "store":
                raise RuntimeError("store failed")
            await super().async_save(snapshot)

    class RecordingLogger(RedactedOperationalLogger):
        def log_success(self, **kwargs: object) -> bool:
            calls.append("log_success")
            return True

    async def projection(snapshot: MealPlanSnapshot) -> None:
        if failure_point == "projection":
            raise RuntimeError("projection failed")

    async def fetch_source() -> str:
        if failure_point == "fetch":
            raise RuntimeError("fetch failed")
        return RAW_HTML

    def parse_source(source: str, *, fetched_at: str) -> list[MealEntry]:
        if failure_point == "parse":
            raise RuntimeError("parse failed")
        return [_entry(fetched_at=fetched_at)]

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=fetch_source,
        parse_source=parse_source,
        store=MaybeFailingStore(),
        clock=SequenceClock(FETCHED_AT),
        operational_logger=RecordingLogger(),
        snapshot_update_callback=projection,
    )

    if failure_point in ("fetch", "parse"):
        snapshot = _run(coordinator.async_refresh())
        assert snapshot.health.state == "unknown_error"
    else:
        with pytest.raises(RuntimeError, match=f"{failure_point} failed"):
            _run(coordinator.async_refresh())

    assert calls == []


def test_success_logger_exception_does_not_fail_completed_refresh(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("speiseplan.test.success-logger-isolation")

    class FailingSuccessLogger(RedactedOperationalLogger):
        def log_success(self, **kwargs: object) -> bool:
            raise RuntimeError("RAW_KITAFINO_HTML_CAPTURE logger secret")

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: [_entry(fetched_at=fetched_at)],
        clock=SequenceClock(FETCHED_AT),
        operational_logger=FailingSuccessLogger(logger=logger),
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        snapshot = _run(coordinator.async_refresh())

    assert snapshot.health.state == "ok"
    assert coordinator.snapshot is snapshot
    assert "RAW_KITAFINO_HTML_CAPTURE" not in caplog.text
    assert "logger secret" not in caplog.text


def test_listener_failure_isolated_from_later_listeners_and_projection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []
    logger = logging.getLogger("speiseplan.test.listener-isolation")

    async def projection(snapshot: MealPlanSnapshot) -> None:
        calls.append("projection")

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: [_entry(fetched_at=fetched_at)],
        clock=SequenceClock(FETCHED_AT),
        snapshot_update_callback=projection,
        operational_logger=RedactedOperationalLogger(logger=logger),
    )

    def failing_listener() -> None:
        calls.append("failing")
        raise RuntimeError("RAW_KITAFINO_HTML_CAPTURE callback secret")

    coordinator.async_add_listener(failing_listener)
    coordinator.async_add_listener(lambda: calls.append("healthy"))

    with caplog.at_level(logging.WARNING, logger=logger.name):
        _run(coordinator.async_refresh())

    assert sorted(calls) == ["failing", "healthy", "projection"]
    assert "failure_class=unknown_error" in caplog.text
    assert "RAW_KITAFINO_HTML_CAPTURE" not in caplog.text
    assert "callback secret" not in caplog.text


def test_listener_failure_prevents_success_log() -> None:
    calls: list[str] = []

    class RecordingLogger(RedactedOperationalLogger):
        def log_success(self, **kwargs: object) -> bool:
            calls.append("log_success")
            return True

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: [_entry(fetched_at=fetched_at)],
        clock=SequenceClock(FETCHED_AT),
        operational_logger=RecordingLogger(),
    )

    def failing_listener() -> None:
        raise RuntimeError("listener failed")

    coordinator.async_add_listener(failing_listener)
    _run(coordinator.async_refresh())

    assert calls == []


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
    ("child_slug", "shared_source", "parsed", "expected"),
    [
        (None, True, _entry(stale=True), _entry(stale=False)),
        (
            "lena",
            False,
            _child_entry("parser", stale=True),
            replace(_child_entry("parser", stale=False), child_key="lena"),
        ),
    ],
)
def test_successful_refresh_always_marks_parsed_entries_fresh(
    child_slug: str | None,
    shared_source: bool,
    parsed: MealEntry,
    expected: MealEntry,
) -> None:
    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: [parsed],
        clock=SequenceClock(FETCHED_AT),
        child_slug=child_slug,
        shared_source=shared_source,
    )

    assert _run(coordinator.async_refresh()).entries == [expected]


def test_successful_refresh_ignores_malformed_persisted_cache() -> None:
    fresh = _entry(weekday="wednesday")
    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: [fresh],
        store=SnapshotStore(raw_data={"health": "broken", "shared_source": True}),
        clock=SequenceClock(FETCHED_AT),
    )

    snapshot = _run(coordinator.async_refresh())

    assert snapshot.health.state == "ok"
    assert snapshot.entries == [fresh]


def test_successful_empty_refresh_with_invalid_timestamp_does_not_retain() -> None:
    prior = MealPlanSnapshot(
        health=MealPlanSnapshot.empty(fetched_at=FETCHED_AT, health_state="ok").health,
        entries=[_entry()],
    )
    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: [],
        store=SnapshotStore(raw_data=prior.to_dict()),
        clock=SequenceClock("not-an-iso-timestamp"),
    )

    snapshot = _run(coordinator.async_refresh())

    assert snapshot.health.state == "ok"
    assert snapshot.entries == []


def test_successful_partial_refresh_retains_complete_known_week() -> None:
    store = SnapshotStore()
    responses = [
        [_entry(weekday=day, meal_text=f"old {day}") for day in (
            "monday", "tuesday", "wednesday", "thursday", "friday"
        )],
        [
            _entry(
                fetched_at=SECOND_FETCHED_AT,
                weekday=day,
                meal_text=f"fresh {day}",
            )
            for day in ("wednesday", "thursday", "friday")
        ],
    ]

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: responses.pop(0),
        store=store,
        clock=SequenceClock(FETCHED_AT, SECOND_FETCHED_AT),
    )
    _run(coordinator.async_refresh())
    snapshot = _run(coordinator.async_refresh())

    assert snapshot.health.state == "ok"
    assert [(entry.weekday, entry.meal_text, entry.stale) for entry in snapshot.entries] == [
        ("monday", "old monday", True),
        ("tuesday", "old tuesday", True),
        ("wednesday", "fresh wednesday", False),
        ("thursday", "fresh thursday", False),
        ("friday", "fresh friday", False),
    ]
    assert _run(store.async_load()).entries == snapshot.entries


def test_successful_empty_refresh_retains_valid_known_week_as_stale() -> None:
    same_week_refresh = "2026-07-13T07:00:00+02:00"
    store = SnapshotStore()
    prior = MealPlanSnapshot(
        health=MealPlanSnapshot.empty(fetched_at=FETCHED_AT, health_state="ok").health,
        entries=[_entry(weekday="monday"), _entry(weekday="friday")],
        fetched_at=FETCHED_AT,
        last_successful_update=FETCHED_AT,
    )
    _run(store.async_save(prior))
    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: [],
        store=store,
        clock=SequenceClock(same_week_refresh),
    )

    snapshot = _run(coordinator.async_refresh())

    assert snapshot.health.state == "ok"
    assert snapshot.entries == [
        _entry(stale=True, weekday="monday"),
        _entry(stale=True, weekday="friday"),
    ]
    assert _run(store.async_load()).entries == snapshot.entries


def test_first_partial_refresh_exposes_only_fresh_entries() -> None:
    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: [
            _entry(fetched_at=fetched_at, weekday="wednesday")
        ],
        clock=SequenceClock(FETCHED_AT),
    )

    snapshot = _run(coordinator.async_refresh())

    assert snapshot.entries == [_entry(weekday="wednesday")]


def test_successful_refresh_does_not_retain_previous_iso_week_or_year() -> None:
    prior_entries = [
        _entry(iso_week=28),
        _entry(iso_year=2025, iso_week=29, weekday="tuesday"),
    ]
    store = SnapshotStore(
        raw_data=MealPlanSnapshot(
            health=MealPlanSnapshot.empty(fetched_at=FETCHED_AT, health_state="ok").health,
            entries=prior_entries,
        ).to_dict()
    )
    fresh = _entry(fetched_at=SECOND_FETCHED_AT, weekday="wednesday")
    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: [fresh],
        store=store,
        clock=SequenceClock(SECOND_FETCHED_AT),
    )

    assert _run(coordinator.async_refresh()).entries == [fresh]


def test_successful_empty_refresh_does_not_retain_previous_week() -> None:
    prior = MealPlanSnapshot(
        health=MealPlanSnapshot.empty(fetched_at=FETCHED_AT, health_state="ok").health,
        entries=[_entry(iso_week=29)],
    )
    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: [],
        store=SnapshotStore(raw_data=prior.to_dict()),
        clock=SequenceClock("2026-07-20T07:00:00+02:00"),
    )

    assert _run(coordinator.async_refresh()).entries == []


def test_child_success_retains_only_exact_owned_entries() -> None:
    owner = Child("lena", "lena", "child")
    owned = _child_entry("lena")
    store = SnapshotStore(
        raw_data=MealPlanSnapshot(
            health=MealPlanSnapshot.empty(fetched_at=FETCHED_AT, health_state="ok").health,
            entries=[owned, _child_entry("max")],
            shared_source=False,
        ).to_dict()
    )
    fresh = replace(_child_entry("ignored", fetched_at=SECOND_FETCHED_AT), weekday="tuesday")
    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: [fresh],
        store=store,
        clock=SequenceClock(SECOND_FETCHED_AT),
        children=[owner],
        child_slug="lena",
        shared_source=False,
    )

    snapshot = _run(coordinator.async_refresh())

    assert snapshot.entries == [replace(fresh, child_key="lena")]


def test_child_success_retains_exact_owned_same_week_entry() -> None:
    owner = Child("lena", "lena", "child")
    owned = _child_entry("lena")
    store = SnapshotStore(
        raw_data=MealPlanSnapshot(
            health=MealPlanSnapshot.empty(fetched_at=FETCHED_AT, health_state="ok").health,
            children=[owner],
            entries=[owned],
            shared_source=False,
        ).to_dict()
    )
    fresh = replace(_child_entry("parser", fetched_at=SECOND_FETCHED_AT), weekday="tuesday")
    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=_fetch_source,
        parse_source=lambda source, *, fetched_at: [fresh],
        store=store,
        clock=SequenceClock(SECOND_FETCHED_AT),
        children=[owner],
        child_slug="lena",
        shared_source=False,
    )
    coordinator.snapshot = MealPlanSnapshot(
        health=MealPlanSnapshot.empty(fetched_at=FETCHED_AT, health_state="ok").health,
        children=[owner],
        entries=[owned],
        shared_source=False,
    )

    snapshot = _run(coordinator.async_refresh())

    assert snapshot.entries == [
        replace(owned, stale=True),
        replace(fresh, child_key="lena"),
    ]


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


@pytest.mark.parametrize("cached_entry", [_entry(), _child_entry("max")])
def test_child_failure_discards_shared_or_foreign_cached_entry(
    cached_entry: MealEntry,
) -> None:
    cached = MealPlanSnapshot(
        health=MealPlanSnapshot.empty(
            fetched_at=FETCHED_AT,
            health_state="ok",
        ).health,
        entries=[cached_entry],
        fetched_at=FETCHED_AT,
        last_successful_update=FETCHED_AT,
        shared_source=cached_entry.shared_source,
    )
    store = SnapshotStore()
    _run(store.async_save(cached))

    async def failing_fetch() -> str:
        raise KitafinoCannotConnectError()

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=failing_fetch,
        parse_source=lambda source, *, fetched_at: [],
        store=store,
        clock=SequenceClock(SECOND_FETCHED_AT),
        children=[Child("lena", "lena", "child")],
        child_slug="lena",
        shared_source=False,
    )

    assert _run(coordinator.async_load_cached_snapshot()) is None
    snapshot = _run(coordinator.async_refresh())

    assert snapshot.health.state == "network_error"
    assert snapshot.entries == []
    assert snapshot.shared_source is False
    assert snapshot.children == [Child("lena", "lena", "child")]


def test_child_failure_discards_unattributed_empty_shared_cache() -> None:
    store = SnapshotStore()
    _run(
        store.async_save(
            MealPlanSnapshot.empty(fetched_at=FETCHED_AT, health_state="ok")
        )
    )

    async def failing_fetch() -> str:
        raise KitafinoCannotConnectError()

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=failing_fetch,
        parse_source=lambda source, *, fetched_at: [],
        store=store,
        clock=SequenceClock(SECOND_FETCHED_AT),
        children=[Child("lena", "lena", "child")],
        child_slug="lena",
        shared_source=False,
    )

    assert _run(coordinator.async_load_cached_snapshot()) is None
    snapshot = _run(coordinator.async_refresh())
    assert snapshot.entries == []
    assert snapshot.health.state == "network_error"
    assert snapshot.shared_source is False


def test_child_failure_reuses_in_memory_empty_snapshot_with_exact_owner() -> None:
    owner = Child("lena", "lena", "child")

    async def failing_fetch() -> str:
        raise KitafinoCannotConnectError()

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=failing_fetch,
        parse_source=lambda source, *, fetched_at: [],
        clock=SequenceClock(SECOND_FETCHED_AT),
        children=[owner],
        child_slug="lena",
        shared_source=False,
    )
    coordinator.snapshot = MealPlanSnapshot(
        health=MealPlanSnapshot.empty(
            fetched_at=FETCHED_AT,
            health_state="ok",
        ).health,
        children=[owner],
        entries=[],
        fetched_at=FETCHED_AT,
        last_successful_update=FETCHED_AT,
        shared_source=False,
    )

    snapshot = _run(coordinator.async_refresh())

    assert snapshot.health.state == "stale"
    assert snapshot.entries == []
    assert snapshot.children == [owner]
    assert snapshot.shared_source is False


def test_child_rejects_persisted_empty_snapshot_after_children_are_stripped() -> None:
    owner = Child("lena", "lena", "child")
    store = SnapshotStore()
    _run(
        store.async_save(
            MealPlanSnapshot(
                health=MealPlanSnapshot.empty(
                    fetched_at=FETCHED_AT,
                    health_state="ok",
                ).health,
                children=[owner],
                entries=[],
                fetched_at=FETCHED_AT,
                last_successful_update=FETCHED_AT,
                shared_source=False,
            )
        )
    )
    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=lambda: RAW_HTML,
        parse_source=lambda source, *, fetched_at: [],
        store=store,
        clock=SequenceClock(SECOND_FETCHED_AT),
        children=[owner],
        child_slug="lena",
        shared_source=False,
    )

    assert _run(coordinator.async_load_cached_snapshot()) is None


def test_legacy_coordinator_rejects_child_owned_cache() -> None:
    child_snapshot = MealPlanSnapshot(
        health=MealPlanSnapshot.empty(
            fetched_at=FETCHED_AT,
            health_state="ok",
        ).health,
        children=[Child("lena", "lena", "child")],
        entries=[_child_entry("lena")],
        fetched_at=FETCHED_AT,
        last_successful_update=FETCHED_AT,
        shared_source=False,
    )
    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=lambda: RAW_HTML,
        parse_source=lambda source, *, fetched_at: [],
        store=SnapshotStore(raw_data=child_snapshot.to_dict()),
        clock=SequenceClock(SECOND_FETCHED_AT),
    )

    assert _run(coordinator.async_load_cached_snapshot()) is None


def test_child_failure_rejects_mixed_owner_cache_without_relabeling() -> None:
    owned_entry = _child_entry("lena")
    cached = MealPlanSnapshot(
        health=MealPlanSnapshot.empty(
            fetched_at=FETCHED_AT,
            health_state="ok",
        ).health,
        entries=[owned_entry, _child_entry("max")],
        fetched_at=FETCHED_AT,
        last_successful_update=FETCHED_AT,
        shared_source=False,
    )
    store = SnapshotStore()
    _run(store.async_save(cached))

    async def failing_fetch() -> str:
        raise KitafinoCannotConnectError()

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=failing_fetch,
        parse_source=lambda source, *, fetched_at: [],
        store=store,
        clock=SequenceClock(SECOND_FETCHED_AT),
        children=[Child("lena", "lena", "child")],
        child_slug="lena",
        shared_source=False,
    )
    restored = _run(coordinator.async_load_cached_snapshot())
    snapshot = _run(coordinator.async_refresh())

    assert restored is None
    assert snapshot.entries == []
    assert snapshot.health.state == "network_error"


def test_child_failure_reuses_exact_owned_cache_without_relabeling() -> None:
    owned_entry = _child_entry("lena")
    cached = MealPlanSnapshot(
        health=MealPlanSnapshot.empty(
            fetched_at=FETCHED_AT,
            health_state="ok",
        ).health,
        entries=[owned_entry],
        fetched_at=FETCHED_AT,
        last_successful_update=FETCHED_AT,
        shared_source=False,
    )
    store = SnapshotStore()
    _run(store.async_save(cached))

    async def failing_fetch() -> str:
        raise KitafinoCannotConnectError()

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=failing_fetch,
        parse_source=lambda source, *, fetched_at: [],
        store=store,
        clock=SequenceClock(SECOND_FETCHED_AT),
        children=[Child("lena", "lena", "child")],
        child_slug="lena",
        shared_source=False,
    )

    restored = _run(coordinator.async_load_cached_snapshot())
    snapshot = _run(coordinator.async_refresh())

    assert restored is not None
    assert restored.entries == [owned_entry]
    assert snapshot.entries == [_child_entry("lena", stale=True)]


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
