"""Tests for redacted operational logging."""

from __future__ import annotations

import asyncio
import logging

from custom_components.speiseplan.coordinator import SpeiseplanDataUpdateCoordinator
from custom_components.speiseplan.kitafino.errors import (
    KitafinoCannotConnectError,
    KitafinoInvalidAuthError,
    KitafinoParseError,
)
from custom_components.speiseplan.operational_logging import RedactedOperationalLogger
from custom_components.speiseplan.storage import SnapshotStore


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class UnsafeDiagnosticValue:
    """Compare like an allow-listed value while remaining unsafe and unhashable."""

    __hash__ = None

    def __eq__(self, other: object) -> bool:
        return other in ("login", "timeout")

    def __str__(self) -> str:
        return "REAL_SESSION_COOKIE_VALUE"


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


def _coordinator_with_error(
    error: Exception,
    *,
    logger: logging.Logger,
    clock: FakeClock | None = None,
) -> SpeiseplanDataUpdateCoordinator:
    async def fetch_source() -> str:
        raise error

    return SpeiseplanDataUpdateCoordinator(
        fetch_source=fetch_source,
        parse_source=lambda source, *, fetched_at: [],
        store=SnapshotStore(),
        clock=lambda: "2026-07-14T06:00:00+02:00",
        config_entry_id="entry-1",
        operational_logger=RedactedOperationalLogger(
            logger=logger,
            clock=clock or FakeClock(),
            dedup_interval_seconds=300,
        ),
    )


def test_logger_normalizes_unsafe_call_values(caplog: object) -> None:
    logger = logging.getLogger("speiseplan.test.logging.normalize")
    operational_logger = RedactedOperationalLogger(
        logger=logger,
        clock=FakeClock(),
    )

    with caplog.at_level(logging.WARNING, logger=logger.name):  # type: ignore[attr-defined]
        operational_logger.log_failure(
            entry_id="parent@example.test",
            phase="RAW_KITAFINO_HTML_CAPTURE",
            failure_class="cookie=REAL_SESSION_COOKIE_VALUE",
            request_stage="https://secret.example/login",
            failure_reason="cookie=REAL_SESSION_COOKIE_VALUE",
            http_status=True,
        )

    text = caplog.text  # type: ignore[attr-defined]
    assert "entry_id=unknown" in text
    assert "phase=unknown" in text
    assert "failure_class=unknown_error" in text
    assert "request_stage=unknown" in text
    assert "failure_reason=unknown" in text
    assert "http_status=none" in text
    assert "secret.example" not in text
    assert "parent@example.test" not in text
    assert "RAW_KITAFINO_HTML_CAPTURE" not in text
    assert "REAL_SESSION_COOKIE_VALUE" not in text


def test_logger_rejects_non_string_allowlist_lookalikes(caplog: object) -> None:
    logger = logging.getLogger("speiseplan.test.logging.object-normalize")
    operational_logger = RedactedOperationalLogger(logger=logger)
    unsafe = UnsafeDiagnosticValue()

    with caplog.at_level(logging.WARNING, logger=logger.name):  # type: ignore[attr-defined]
        operational_logger.log_failure(
            entry_id="entry-1",
            phase="setup",
            failure_class="network_error",
            request_stage=unsafe,
            failure_reason=unsafe,
        )

    text = caplog.text  # type: ignore[attr-defined]
    assert "request_stage=unknown" in text
    assert "failure_reason=unknown" in text
    assert "REAL_SESSION_COOKIE_VALUE" not in text


def test_connection_error_rejects_non_string_allowlist_lookalikes() -> None:
    unsafe = UnsafeDiagnosticValue()

    error = KitafinoCannotConnectError(
        stage=unsafe,  # type: ignore[arg-type]
        reason=unsafe,  # type: ignore[arg-type]
    )

    assert error.stage is None
    assert error.reason is None


def test_refresh_failure_logs_class_without_secret_details(
    caplog: object,
) -> None:
    logger = logging.getLogger("speiseplan.test.logging")
    coordinator = _coordinator_with_error(
        KitafinoCannotConnectError("RAW_KITAFINO_HTML_CAPTURE super-secret"),
        logger=logger,
    )

    with caplog.at_level(logging.WARNING, logger=logger.name):  # type: ignore[attr-defined]
        snapshot = _run(coordinator.async_refresh())

    text = caplog.text  # type: ignore[attr-defined]
    assert snapshot.health.state == "network_error"
    assert "entry_id=entry-1" in text
    assert "phase=refresh" in text
    assert "failure_class=network_error" in text
    assert "RAW_KITAFINO_HTML_CAPTURE" not in text
    assert "super-secret" not in text


def test_refresh_failure_logs_safe_network_diagnostics(caplog: object) -> None:
    logger = logging.getLogger("speiseplan.test.logging.diagnostics")
    coordinator = _coordinator_with_error(
        KitafinoCannotConnectError(
            "never log this",
            stage="meal_plan",
            reason="http_status",
            http_status=503,
        ),
        logger=logger,
    )

    with caplog.at_level(logging.WARNING, logger=logger.name):  # type: ignore[attr-defined]
        snapshot = _run(coordinator.async_refresh())

    text = caplog.text  # type: ignore[attr-defined]
    assert snapshot.health.state == "network_error"
    assert "request_stage=meal_plan" in text
    assert "failure_reason=http_status" in text
    assert "http_status=503" in text
    assert "never log this" not in text


def test_setup_refresh_failure_logs_setup_phase(caplog: object) -> None:
    logger = logging.getLogger("speiseplan.test.logging.setup")
    coordinator = _coordinator_with_error(
        KitafinoCannotConnectError("RAW_KITAFINO_HTML_CAPTURE"),
        logger=logger,
    )

    with caplog.at_level(logging.WARNING, logger=logger.name):  # type: ignore[attr-defined]
        _run(coordinator.async_refresh(phase="setup"))

    text = caplog.text  # type: ignore[attr-defined]
    assert "phase=setup" in text
    assert "failure_class=network_error" in text
    assert "RAW_KITAFINO_HTML_CAPTURE" not in text


def test_successful_refresh_does_not_log_warning(caplog: object) -> None:
    logger = logging.getLogger("speiseplan.test.logging.success")

    async def fetch_source() -> str:
        return "ok"

    coordinator = SpeiseplanDataUpdateCoordinator(
        fetch_source=fetch_source,
        parse_source=lambda source, *, fetched_at: [],
        store=SnapshotStore(),
        clock=lambda: "2026-07-14T06:00:00+02:00",
        config_entry_id="entry-1",
        operational_logger=RedactedOperationalLogger(
            logger=logger,
            clock=FakeClock(),
        ),
    )

    with caplog.at_level(logging.WARNING, logger=logger.name):  # type: ignore[attr-defined]
        snapshot = _run(coordinator.async_refresh())

    assert snapshot.health.state == "ok"
    assert caplog.text == ""  # type: ignore[attr-defined]


def test_refresh_failure_logs_distinct_failure_classes(caplog: object) -> None:
    logger = logging.getLogger("speiseplan.test.logging.classes")

    with caplog.at_level(logging.WARNING, logger=logger.name):  # type: ignore[attr-defined]
        _run(
            _coordinator_with_error(
                KitafinoInvalidAuthError("parent@example.test"),
                logger=logger,
            ).async_refresh()
        )
        _run(
            _coordinator_with_error(
                KitafinoParseError("RAW_KITAFINO_HTML_CAPTURE"),
                logger=logger,
            ).async_refresh()
        )
        _run(
            _coordinator_with_error(
                RuntimeError("cookie=REAL_SESSION_COOKIE_VALUE"),
                logger=logger,
            ).async_refresh()
        )

    text = caplog.text  # type: ignore[attr-defined]
    assert "failure_class=login_failed" in text
    assert "failure_class=parse_error" in text
    assert "failure_class=unknown_error" in text
    assert "parent@example.test" not in text
    assert "RAW_KITAFINO_HTML_CAPTURE" not in text
    assert "REAL_SESSION_COOKIE_VALUE" not in text


def test_refresh_failure_logs_are_deduplicated(caplog: object) -> None:
    logger = logging.getLogger("speiseplan.test.logging.dedup")
    clock = FakeClock()
    coordinator = _coordinator_with_error(
        KitafinoCannotConnectError("network detail"),
        logger=logger,
        clock=clock,
    )

    with caplog.at_level(logging.WARNING, logger=logger.name):  # type: ignore[attr-defined]
        _run(coordinator.async_refresh())
        clock.value = 60
        _run(coordinator.async_refresh())
        clock.value = 301
        _run(coordinator.async_refresh())

    assert caplog.text.count("failure_class=network_error") == 2  # type: ignore[attr-defined]


def test_distinct_safe_diagnostics_are_not_deduplicated(caplog: object) -> None:
    logger = logging.getLogger("speiseplan.test.logging.dedup.diagnostics")
    operational_logger = RedactedOperationalLogger(
        logger=logger,
        clock=FakeClock(),
    )

    with caplog.at_level(logging.WARNING, logger=logger.name):  # type: ignore[attr-defined]
        for status in (502, 503):
            operational_logger.log_failure(
                entry_id="entry-1",
                phase="setup",
                failure_class="network_error",
                request_stage="meal_plan",
                failure_reason="http_status",
                http_status=status,
            )

    assert caplog.text.count("failure_class=network_error") == 2  # type: ignore[attr-defined]
