"""Kitafino client for Speiseplan."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .errors import (
    KitafinoCannotConnectError,
    KitafinoInvalidAuthError,
    KitafinoValidationError,
)

CredentialValidator = Callable[[str, str], Awaitable[None]]

LOGIN_URL = "https://auth.kitafino.de/sys_k2/index.php?action=do_login"
USER_AGENT = "Mozilla/5.0 (Home Assistant Kitafino Meal Plan)"
TIMEOUT_SECONDS = 15


class KitafinoClient:
    """Kitafino client facade used by config flow and later fetch stories."""

    def __init__(
        self,
        username: str,
        password: str,
        *,
        validator: CredentialValidator | None = None,
    ) -> None:
        """Create a client without performing network I/O."""
        self._username = username
        self._password = password
        self._validator = validator

    async def async_validate_credentials(self) -> None:
        """Validate credentials through injected validation or Kitafino login."""
        if not self._username.strip() or not self._password.strip():
            raise KitafinoInvalidAuthError()

        if self._validator is not None:
            await self._validator(self._username, self._password)
            return

        await self._async_login_check()

    async def _async_login_check(self) -> None:
        """Perform a memory-only login check against Kitafino."""
        try:
            import aiohttp
        except ModuleNotFoundError as err:  # pragma: no cover - HA provides aiohttp
            raise KitafinoValidationError() from err

        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        headers = {"User-Agent": USER_AGENT}
        payload = {
            "benutzername": self._username,
            "passwort": self._password,
            "login": "Anmelden",
        }

        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                headers=headers,
            ) as session:
                async with session.post(LOGIN_URL, data=payload) as response:
                    status = response.status
                    final_url = str(response.url)
                    text = await response.text()
        except (aiohttp.ClientError, TimeoutError, asyncio.TimeoutError) as err:
            raise KitafinoCannotConnectError() from err

        if status in (401, 403):
            raise KitafinoInvalidAuthError()

        if status != 200:
            raise KitafinoCannotConnectError()

        if "login" in final_url.lower() or "passwort" in text.lower():
            raise KitafinoInvalidAuthError()
