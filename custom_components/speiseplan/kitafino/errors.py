"""Typed Kitafino error skeletons for Speiseplan."""

from __future__ import annotations


class KitafinoError(Exception):
    """Base error for Kitafino integration failures."""


class KitafinoInvalidAuthError(KitafinoError):
    """Credentials were rejected by Kitafino."""


class KitafinoCannotConnectError(KitafinoError):
    """Kitafino could not be reached for validation."""


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
