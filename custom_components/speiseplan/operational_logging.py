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
)

_LOGGER = logging.getLogger(__package__ or DOMAIN)
DEFAULT_LOG_DEDUP_INTERVAL_SECONDS = 300.0
SAFE_PHASES = ("setup", "refresh", "manual_refresh", "config_validation")
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
        self._last_logged_by_key: dict[tuple[str, str, str], float] = {}

    def log_failure(
        self,
        *,
        entry_id: str | None,
        phase: str,
        failure_class: str,
    ) -> bool:
        """Log a redacted failure event and return whether it was emitted."""
        safe_entry_id = _safe_entry_id(entry_id)
        safe_phase = phase if phase in SAFE_PHASES else "unknown"
        safe_failure_class = (
            failure_class
            if failure_class in SAFE_FAILURE_CLASSES
            else ERROR_UNKNOWN
        )
        key = (safe_entry_id, safe_phase, safe_failure_class)
        now = self.clock()
        last_logged = self._last_logged_by_key.get(key)
        if (
            last_logged is not None
            and now - last_logged < self.dedup_interval_seconds
        ):
            return False

        self._last_logged_by_key[key] = now
        self.logger.warning(
            "Speiseplan operation failed: entry_id=%s phase=%s failure_class=%s",
            safe_entry_id,
            safe_phase,
            safe_failure_class,
        )
        return True


def _safe_entry_id(entry_id: str | None) -> str:
    """Return an entry identifier safe enough for operational logs."""
    if not isinstance(entry_id, str):
        return "unknown"
    if not SAFE_ENTRY_ID_PATTERN.fullmatch(entry_id):
        return "unknown"
    return entry_id


DEFAULT_OPERATIONAL_LOGGER = RedactedOperationalLogger()
