"""Typed Kitafino error skeletons for Speiseplan."""

from __future__ import annotations

from typing import Literal

RequestStage = Literal["login", "meal_plan", "transport"]
FailureReason = Literal[
    "timeout",
    "transport",
    "http_status",
    "incomplete_response",
    "missing_content",
]

SAFE_REQUEST_STAGES = ("login", "meal_plan", "transport")
SAFE_FAILURE_REASONS = (
    "timeout",
    "transport",
    "http_status",
    "incomplete_response",
    "missing_content",
)


class KitafinoError(Exception):
    """Base error for Kitafino integration failures."""


class KitafinoInvalidAuthError(KitafinoError):
    """Credentials were rejected by Kitafino."""


class KitafinoCannotConnectError(KitafinoError):
    """Kitafino could not be reached for validation."""

    def __init__(
        self,
        *args: object,
        stage: RequestStage | None = None,
        reason: FailureReason | None = None,
        http_status: int | None = None,
    ) -> None:
        """Keep legacy arguments while carrying only validated diagnostics."""
        super().__init__(*args)
        self.stage = (
            stage
            if isinstance(stage, str) and stage in SAFE_REQUEST_STAGES
            else None
        )
        self.reason = (
            reason
            if isinstance(reason, str) and reason in SAFE_FAILURE_REASONS
            else None
        )
        self.http_status = (
            http_status
            if isinstance(http_status, int)
            and not isinstance(http_status, bool)
            and 100 <= http_status <= 599
            else None
        )


class KitafinoValidationError(KitafinoError):
    """Unexpected safe validation failure."""


class KitafinoParseError(KitafinoError):
    """Kitafino source data could not be parsed."""


class KitafinoUnknownError(KitafinoError):
    """Unexpected Kitafino integration failure."""


ERROR_LOGIN_FAILED = "login_failed"
ERROR_NETWORK = "network_error"
ERROR_PARSE = "parse_error"
ERROR_UNKNOWN = "unknown_error"


def error_code(error: BaseException) -> str:
    """Map a Kitafino exception to a stable public failure code."""
    if isinstance(error, KitafinoInvalidAuthError):
        return ERROR_LOGIN_FAILED
    if isinstance(error, KitafinoCannotConnectError):
        return ERROR_NETWORK
    if isinstance(error, KitafinoParseError):
        return ERROR_PARSE
    return ERROR_UNKNOWN
