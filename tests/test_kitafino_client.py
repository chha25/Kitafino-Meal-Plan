"""Tests for Kitafino login and source fetching."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.speiseplan.kitafino.client import (
    MEAL_PLAN_URL,
    KitafinoClient,
    KitafinoTransportRequest,
    KitafinoTransportResult,
)
from custom_components.speiseplan.kitafino.errors import (
    KitafinoCannotConnectError,
    KitafinoInvalidAuthError,
)


USERNAME = "parent@example.test"
PASSWORD = "super-secret"
SOURCE_HTML = "<html><body>Montag: Pasta</body></html>"


class FakeTransport:
    """Configurable Kitafino transport for client tests."""

    def __init__(
        self,
        result: KitafinoTransportResult | None = None,
        exception: BaseException | None = None,
    ) -> None:
        self.result = result
        self.exception = exception
        self.requests: list[KitafinoTransportRequest] = []

    async def __call__(
        self,
        request: KitafinoTransportRequest,
    ) -> KitafinoTransportResult:
        self.requests.append(request)
        if self.exception is not None:
            raise self.exception
        if self.result is None:
            raise AssertionError("FakeTransport needs result or exception")
        return self.result


def _result(
    *,
    login_status: int = 200,
    login_url: str = "https://app.kitafino.de/sys_k2/index.php",
    login_text: str = "Willkommen",
    source_status: int = 200,
    source_url: str = MEAL_PLAN_URL,
    source_text: str = SOURCE_HTML,
) -> KitafinoTransportResult:
    return KitafinoTransportResult(
        login_status=login_status,
        login_url=login_url,
        login_text=login_text,
        source_status=source_status,
        source_url=source_url,
        source_text=source_text,
    )


def test_fetch_meal_plan_source_logs_in_and_returns_source_text() -> None:
    transport = FakeTransport(_result())
    client = KitafinoClient(USERNAME, PASSWORD, transport=transport)

    source = asyncio.run(client.async_fetch_meal_plan_source())

    assert source == SOURCE_HTML
    assert transport.requests == [
        KitafinoTransportRequest(
            username=USERNAME,
            password=PASSWORD,
            login_url="https://auth.kitafino.de/sys_k2/index.php?action=do_login",
            meal_plan_url="https://user.kitafino.de/sys_k2/index.php?action=bestellen",
            fetch_source=True,
        )
    ]


def test_fetch_trims_credentials_before_transport_call() -> None:
    transport = FakeTransport(_result())
    client = KitafinoClient(f" {USERNAME} ", f" {PASSWORD} ", transport=transport)

    asyncio.run(client.async_fetch_meal_plan_source())

    assert transport.requests[0].username == USERNAME
    assert transport.requests[0].password == PASSWORD


def test_validate_credentials_uses_login_only_transport_request() -> None:
    transport = FakeTransport(_result(source_text=""))
    client = KitafinoClient(USERNAME, PASSWORD, transport=transport)

    asyncio.run(client.async_validate_credentials())

    assert len(transport.requests) == 1
    assert transport.requests[0].fetch_source is False


@pytest.mark.parametrize(
    "result",
    [
        _result(login_status=401),
        _result(login_status=403),
        _result(login_url="https://auth.kitafino.de/sys_k2/index.php?action=login"),
        _result(login_text='<input name="passwort" type="password">'),
        _result(source_status=401),
        _result(source_status=403),
        _result(source_url="https://auth.kitafino.de/sys_k2/index.php?action=login"),
    ],
)
def test_fetch_maps_login_or_authenticated_access_failure_to_invalid_auth(
    result: KitafinoTransportResult,
) -> None:
    client = KitafinoClient(USERNAME, PASSWORD, transport=FakeTransport(result))

    with pytest.raises(KitafinoInvalidAuthError) as err:
        asyncio.run(client.async_fetch_meal_plan_source())

    assert USERNAME not in str(err.value)
    assert PASSWORD not in str(err.value)


@pytest.mark.parametrize(
    "result",
    [
        _result(login_status=500),
        _result(source_status=500),
        KitafinoTransportResult(
            login_status=200,
            login_url="https://app.kitafino.de/sys_k2/index.php",
            login_text="Willkommen",
        ),
    ],
)
def test_fetch_maps_service_failures_to_cannot_connect(
    result: KitafinoTransportResult,
) -> None:
    client = KitafinoClient(USERNAME, PASSWORD, transport=FakeTransport(result))

    with pytest.raises(KitafinoCannotConnectError) as err:
        asyncio.run(client.async_fetch_meal_plan_source())

    assert USERNAME not in str(err.value)
    assert PASSWORD not in str(err.value)
    assert SOURCE_HTML not in str(err.value)


def test_fetch_treats_missing_source_text_as_cannot_connect() -> None:
    client = KitafinoClient(
        USERNAME,
        PASSWORD,
        transport=FakeTransport(_result(source_text=None)),
    )

    with pytest.raises(KitafinoCannotConnectError) as err:
        asyncio.run(client.async_fetch_meal_plan_source())

    assert err.value.stage == "meal_plan"
    assert err.value.reason == "missing_content"
    assert err.value.http_status is None


def test_fetch_does_not_treat_do_login_final_url_as_auth_failure() -> None:
    client = KitafinoClient(
        USERNAME,
        PASSWORD,
        transport=FakeTransport(_result(login_url="https://auth.kitafino.de/sys_k2/index.php?action=do_login")),
    )

    assert asyncio.run(client.async_fetch_meal_plan_source()) == SOURCE_HTML


def test_fetch_does_not_treat_plain_password_word_as_auth_failure() -> None:
    client = KitafinoClient(
        USERNAME,
        PASSWORD,
        transport=FakeTransport(_result(login_text="Bitte Passwort regelmaessig aendern")),
    )

    assert asyncio.run(client.async_fetch_meal_plan_source()) == SOURCE_HTML


@pytest.mark.parametrize(
    "exception",
    [
        TimeoutError("timed out with secret"),
        asyncio.TimeoutError("timed out with secret"),
        OSError("network failed with secret"),
    ],
)
def test_fetch_maps_transport_exceptions_without_leaking_details(
    exception: BaseException,
) -> None:
    transport = FakeTransport(exception=exception)
    client = KitafinoClient(USERNAME, PASSWORD, transport=transport)

    with pytest.raises(KitafinoCannotConnectError) as err:
        asyncio.run(client.async_fetch_meal_plan_source())

    assert str(err.value) == ""
    assert err.value.__cause__ is None
    assert err.value.__context__ is None
    assert err.value.stage == "transport"
    assert err.value.reason == (
        "timeout" if isinstance(exception, TimeoutError) else "transport"
    )


def test_fetch_classifies_meal_plan_http_status() -> None:
    client = KitafinoClient(
        USERNAME,
        PASSWORD,
        transport=FakeTransport(_result(source_status=503)),
    )

    with pytest.raises(KitafinoCannotConnectError) as err:
        asyncio.run(client.async_fetch_meal_plan_source())

    assert err.value.stage == "meal_plan"
    assert err.value.reason == "http_status"
    assert err.value.http_status == 503


def test_fetch_prioritizes_http_status_over_missing_error_body() -> None:
    client = KitafinoClient(
        USERNAME,
        PASSWORD,
        transport=FakeTransport(_result(source_status=503, source_text=None)),
    )

    with pytest.raises(KitafinoCannotConnectError) as err:
        asyncio.run(client.async_fetch_meal_plan_source())

    assert err.value.stage == "meal_plan"
    assert err.value.reason == "http_status"
    assert err.value.http_status == 503


def test_fetch_rejects_blank_credentials_before_transport_call() -> None:
    transport = FakeTransport(_result())
    client = KitafinoClient(" ", PASSWORD, transport=transport)

    with pytest.raises(KitafinoInvalidAuthError):
        asyncio.run(client.async_fetch_meal_plan_source())

    assert transport.requests == []
