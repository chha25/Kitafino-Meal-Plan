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
