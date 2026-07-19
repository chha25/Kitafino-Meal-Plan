"""Kitafino client for Speiseplan."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from http.cookies import Morsel
from typing import Protocol
from urllib.parse import urlsplit

from .errors import (
    KitafinoCannotConnectError,
    KitafinoInvalidAuthError,
    KitafinoValidationError,
)

CredentialValidator = Callable[[str, str], Awaitable[None]]
KitafinoTransport = Callable[["KitafinoTransportRequest"], Awaitable["KitafinoTransportResult"]]

LOGIN_URL = "https://auth.kitafino.de/sys_k2/index.php?action=do_login"
MEAL_PLAN_URL = "https://user.kitafino.de/sys_k2/index.php?action=bestellen"
USER_AGENT = "Mozilla/5.0 (Home Assistant Kitafino Meal Plan)"
TIMEOUT_SECONDS = 15
_PHP_SESSION_COOKIE = "PHPSESSID"
_PARENT_COOKIE_DOMAIN = "kitafino.de"
_USER_COOKIE_DOMAIN = "user.kitafino.de"


class _CookieJar(Protocol):
    """Public cookie-jar operations used by session reconciliation."""

    def __iter__(self) -> Iterator[Morsel[str]]: ...

    def clear(
        self,
        predicate: Callable[[Morsel[str]], bool] | None = None,
    ) -> None: ...


def _cookie_path_matches(request_path: str, cookie_path: str) -> bool:
    """Return whether a cookie path applies to a request path."""
    normalized_path = cookie_path or "/"
    return (
        request_path == normalized_path
        or (
            request_path.startswith(normalized_path)
            and (
                normalized_path.endswith("/")
                or request_path[len(normalized_path) :].startswith("/")
            )
        )
    )


def _reconcile_session_cookie_collision(
    cookie_jar: _CookieJar,
    request_url: str,
) -> None:
    """Prefer the parent session only for an eligible duplicate state."""
    request_path = urlsplit(request_url).path or "/"
    eligible_sessions = [
        morsel
        for morsel in cookie_jar
        if morsel.key == _PHP_SESSION_COOKIE
        and _cookie_path_matches(request_path, morsel["path"])
    ]
    session_domains = {
        morsel["domain"].lstrip(".").lower() for morsel in eligible_sessions
    }
    if not {
        _PARENT_COOKIE_DOMAIN,
        _USER_COOKIE_DOMAIN,
    }.issubset(session_domains):
        return

    cookie_jar.clear(
        lambda morsel: (
            morsel.key == _PHP_SESSION_COOKIE
            and morsel["domain"].lstrip(".").lower() == _USER_COOKIE_DOMAIN
            and _cookie_path_matches(request_path, morsel["path"])
        )
    )


@dataclass(frozen=True)
class KitafinoTransportRequest:
    """Transport request for login and optional meal-plan source fetch."""

    username: str
    password: str
    login_url: str
    meal_plan_url: str
    fetch_source: bool


@dataclass(frozen=True)
class KitafinoTransportResult:
    """Transport result with raw response metadata kept inside client scope."""

    login_status: int
    login_url: str
    login_text: str
    source_status: int | None = None
    source_url: str | None = None
    source_text: str | None = None


class KitafinoClient:
    """Kitafino client facade used by config flow and later fetch stories."""

    def __init__(
        self,
        username: str,
        password: str,
        *,
        validator: CredentialValidator | None = None,
        transport: KitafinoTransport | None = None,
        login_url: str = LOGIN_URL,
        meal_plan_url: str = MEAL_PLAN_URL,
    ) -> None:
        """Create a client without performing network I/O."""
        self._username = username.strip()
        self._password = password.strip()
        self._validator = validator
        self._transport = transport
        self._login_url = login_url
        self._meal_plan_url = meal_plan_url

    async def async_validate_credentials(self) -> None:
        """Validate credentials through injected validation or Kitafino login."""
        self._validate_configured_credentials()

        if self._validator is not None:
            await self._validator(self._username, self._password)
            return

        result = await self._async_request(fetch_source=False)
        self._raise_for_login_result(result)

    async def async_fetch_meal_plan_source(self) -> str:
        """Login to Kitafino and return the meal-plan source text."""
        self._validate_configured_credentials()
        result = await self._async_request(fetch_source=True)
        self._raise_for_login_result(result)
        self._raise_for_source_result(result)
        if result.source_text is None:
            raise KitafinoCannotConnectError(
                stage="meal_plan", reason="missing_content"
            )
        return result.source_text

    def _validate_configured_credentials(self) -> None:
        """Validate local credential shape before touching the network."""
        if not self._username.strip() or not self._password.strip():
            raise KitafinoInvalidAuthError()

    async def _async_request(self, *, fetch_source: bool) -> KitafinoTransportResult:
        """Run the configured transport and normalize transport exceptions."""
        request = KitafinoTransportRequest(
            username=self._username,
            password=self._password,
            login_url=self._login_url,
            meal_plan_url=self._meal_plan_url,
            fetch_source=fetch_source,
        )

        failure_reason = "transport"
        try:
            if self._transport is not None:
                return await self._transport(request)
            return await self._async_aiohttp_transport(request)
        except (TimeoutError, asyncio.TimeoutError):
            failure_reason = "timeout"
        except OSError:
            pass

        raise KitafinoCannotConnectError(
            stage="transport", reason=failure_reason
        )

    def _raise_for_login_result(self, result: KitafinoTransportResult) -> None:
        """Map login response metadata to typed errors."""
        if result.login_status in (401, 403):
            raise KitafinoInvalidAuthError(
                stage="login",
                reason="http_status",
                http_status=result.login_status,
            )

        if result.login_status != 200:
            raise KitafinoCannotConnectError(
                stage="login",
                reason="http_status",
                http_status=result.login_status,
            )

        if self._looks_like_login_page(result.login_url, result.login_text):
            raise KitafinoInvalidAuthError(
                stage="login",
                reason="login_page",
                http_status=result.login_status,
            )

    def _raise_for_source_result(self, result: KitafinoTransportResult) -> None:
        """Map authenticated source response metadata to typed errors."""
        if (
            result.source_status is None
            or result.source_url is None
        ):
            raise KitafinoCannotConnectError(
                stage="meal_plan", reason="incomplete_response"
            )

        if result.source_status in (401, 403):
            raise KitafinoInvalidAuthError(
                stage="meal_plan",
                reason="http_status",
                http_status=result.source_status,
            )

        if result.source_status != 200:
            raise KitafinoCannotConnectError(
                stage="meal_plan",
                reason="http_status",
                http_status=result.source_status,
            )

        if result.source_text is None:
            raise KitafinoCannotConnectError(
                stage="meal_plan", reason="missing_content"
            )

        if self._looks_like_login_page(result.source_url, result.source_text or ""):
            raise KitafinoInvalidAuthError(
                stage="meal_plan",
                reason="login_page",
                http_status=result.source_status,
            )

    @staticmethod
    def _looks_like_login_page(url: str, text: str) -> bool:
        """Return whether response metadata indicates Kitafino login failure."""
        lowered_url = url.lower()
        lowered_text = text.lower()
        return (
            "action=login" in lowered_url
            or "name=\"passwort\"" in lowered_text
            or "id=\"passwort\"" in lowered_text
        )

    async def _async_login_check(self) -> None:
        """Perform a memory-only login check against Kitafino."""
        result = await self._async_request(fetch_source=False)
        self._raise_for_login_result(result)

    async def _async_aiohttp_transport(
        self,
        request: KitafinoTransportRequest,
    ) -> KitafinoTransportResult:
        """Perform Kitafino HTTP requests with a memory-only aiohttp session."""
        try:
            import aiohttp
        except ModuleNotFoundError as err:  # pragma: no cover - HA provides aiohttp
            raise KitafinoValidationError() from err

        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        headers = {"User-Agent": USER_AGENT}
        payload = {
            "benutzername": request.username,
            "passwort": request.password,
            "login": "Anmelden",
        }

        request_stage = "login"
        failure_reason = "transport"
        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                headers=headers,
            ) as session:
                async with session.post(request.login_url, data=payload) as response:
                    login_status = response.status
                    login_url = str(response.url)
                    login_text = await response.text(errors="replace")

                if not request.fetch_source:
                    return KitafinoTransportResult(
                        login_status=login_status,
                        login_url=login_url,
                        login_text=login_text,
                    )

                _reconcile_session_cookie_collision(
                    session.cookie_jar,
                    request.meal_plan_url,
                )
                request_stage = "meal_plan"
                async with session.get(request.meal_plan_url) as response:
                    source_status = response.status
                    source_url = str(response.url)
                    source_text = await response.text(errors="replace")

                return KitafinoTransportResult(
                    login_status=login_status,
                    login_url=login_url,
                    login_text=login_text,
                    source_status=source_status,
                    source_url=source_url,
                    source_text=source_text,
                )
        except (TimeoutError, asyncio.TimeoutError):
            failure_reason = "timeout"
        except (aiohttp.ClientError, OSError):
            pass

        raise KitafinoCannotConnectError(
            stage=request_stage, reason=failure_reason
        )
