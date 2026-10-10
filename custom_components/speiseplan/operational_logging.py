"""Redacted operational logging helpers for Speiseplan."""

from __future__ import annotations

import logging
import re
from time import monotonic
from typing import Callable

from .const import DOMAIN
from .kitafino.errors import (
    ERROR_LOGIN_FAILED,
    ERROR_NETWORK,
    ERROR_PARSE,
    ERROR_UNKNOWN,
    SAFE_FAILURE_REASONS,
    SAFE_REQUEST_STAGES,
)

_LOGGER = logging.getLogger(__package__ or DOMAIN)
DEFAULT_LOG_DEDUP_INTERVAL_SECONDS = 300.0
DEFAULT_SUCCESS_LOG_INTERVAL_SECONDS = 3600.0
SAFE_PHASES = (
    "setup",
    "refresh",
    "scheduled_refresh",
    "manual_refresh",
    "config_validation",
)
SAFE_FAILURE_CLASSES = (
    ERROR_LOGIN_FAILED,
    ERROR_NETWORK,
    ERROR_PARSE,
    ERROR_UNKNOWN,
)
SAFE_ENTRY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

Clock = Callable[[], float]


class RedactedOperationalLogger:
    """Write useful operational logs without secret-bearing details."""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        clock: Clock = monotonic,
        dedup_interval_seconds: float = DEFAULT_LOG_DEDUP_INTERVAL_SECONDS,
    ) -> None:
        """Create a redacted logger with simple per-event de-duplication."""
        self.logger = logger or _LOGGER
        self.clock = clock
        self.dedup_interval_seconds = dedup_interval_seconds
        self._last_logged_by_key: dict[tuple[str, str, str, str, str, int | None], float] = {}
        self._last_success_logged_by_key: dict[tuple[str, str], float] = {}

    def log_failure(
        self,
        *,
        entry_id: str | None,
        phase: str,
        failure_class: str,
        request_stage: object = None,
        failure_reason: object = None,
        http_status: object = None,
    ) -> bool:
        """Log a redacted failure event and return whether it was emitted."""
        safe_entry_id = _safe_entry_id(entry_id)
        safe_phase = _safe_phase(phase)
        safe_failure_class = (
            failure_class
            if type(failure_class) is str
            and failure_class in SAFE_FAILURE_CLASSES
            else ERROR_UNKNOWN
        )
        (
            safe_request_stage,
            safe_failure_reason,
            safe_http_status,
        ) = _safe_diagnostics(
            safe_failure_class,
            request_stage,
            failure_reason,
            http_status,
        )
        key = (
            safe_entry_id,
            safe_phase,
            safe_failure_class,
            safe_request_stage,
            safe_failure_reason,
            safe_http_status,
        )
        now = self.clock()
        last_logged = self._last_logged_by_key.get(key)
        if (
            last_logged is not None
            and now - last_logged < self.dedup_interval_seconds
        ):
            return False

        self._last_logged_by_key[key] = now
        self.logger.warning(
            "Speiseplan operation failed: entry_id=%s phase=%s failure_class=%s "
            "request_stage=%s failure_reason=%s http_status=%s",
            safe_entry_id,
            safe_phase,
            safe_failure_class,
            safe_request_stage,
            safe_failure_reason,
            safe_http_status if safe_http_status is not None else "none",
        )
        return True

    def log_success(
        self,
        *,
        entry_id: object,
        phase: object,
        entry_count: object,
    ) -> bool:
        """Log a rate-limited, allow-listed successful refresh event."""
        safe_entry_id = _safe_entry_id(entry_id)
        safe_phase = _safe_phase(phase)
        safe_entry_count = (
            entry_count
            if type(entry_count) is int and entry_count >= 0
            else 0
        )
        key = (safe_entry_id, safe_phase)
        now = self.clock()
        last_logged = self._last_success_logged_by_key.get(key)
        if (
            last_logged is not None
            and now - last_logged < DEFAULT_SUCCESS_LOG_INTERVAL_SECONDS
        ):
            return False

        self._last_success_logged_by_key[key] = now
        self.logger.info(
            "Speiseplan operation succeeded: entry_id=%s phase=%s "
            "health=ok entry_count=%s",
            safe_entry_id,
            safe_phase,
            safe_entry_count,
        )
        return True


def _safe_entry_id(entry_id: object) -> str:
    """Return an entry identifier safe enough for operational logs."""
    if type(entry_id) is not str:
        return "unknown"
    if not SAFE_ENTRY_ID_PATTERN.fullmatch(entry_id):
        return "unknown"
    return entry_id


def _safe_phase(phase: object) -> str:
    """Return only an exact allow-listed phase string."""
    if type(phase) is not str or phase not in SAFE_PHASES:
        return "unknown"
    return phase


def _safe_diagnostics(
    failure_class: str,
    request_stage: object,
    failure_reason: object,
    http_status: object,
) -> tuple[str, str, int | None]:
    """Return a coherent failure-class-specific tuple or no evidence."""
    unknown = ("unknown", "unknown", None)
    if type(request_stage) is not str or request_stage not in SAFE_REQUEST_STAGES:
        return unknown
    if type(failure_reason) is not str or failure_reason not in SAFE_FAILURE_REASONS:
        return unknown
    safe_status = (
        http_status
        if type(http_status) is int and 100 <= http_status <= 599
        else None
    )

    if failure_class == ERROR_LOGIN_FAILED:
        if (
            request_stage in ("login", "meal_plan")
            and failure_reason == "http_status"
            and safe_status in (401, 403)
        ):
            return request_stage, failure_reason, safe_status
        if (
            request_stage in ("login", "meal_plan")
            and failure_reason == "login_page"
            and safe_status == 200
        ):
            return request_stage, failure_reason, safe_status
        return unknown

    if failure_class != ERROR_NETWORK:
        return unknown
    if failure_reason in ("timeout", "transport") and http_status is None:
        return request_stage, failure_reason, None
    if (
        request_stage in ("login", "meal_plan")
        and failure_reason == "http_status"
        and safe_status is not None
        and safe_status not in (200, 401, 403)
    ):
        return request_stage, failure_reason, safe_status
    if (
        request_stage == "meal_plan"
        and failure_reason in ("incomplete_response", "missing_content")
        and http_status is None
    ):
        return request_stage, failure_reason, None
    return unknown


DEFAULT_OPERATIONAL_LOGGER = RedactedOperationalLogger()
