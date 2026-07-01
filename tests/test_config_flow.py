"""Tests for Speiseplan config-flow metadata."""

from __future__ import annotations

import json
from pathlib import Path
import asyncio

import pytest

from custom_components.speiseplan.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_TITLE,
)
from custom_components.speiseplan.config_flow import (
    async_validate_user_input,
    get_duplicate_setup_abort_reason,
    get_user_schema_keys,
)
from custom_components.speiseplan.kitafino.client import KitafinoClient
from custom_components.speiseplan.kitafino.errors import (
    KitafinoCannotConnectError,
    KitafinoInvalidAuthError,
)


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_declares_config_flow() -> None:
    manifest = json.loads(
        (ROOT / "custom_components/speiseplan/manifest.json").read_text()
    )

    assert manifest["domain"] == "speiseplan"
    assert manifest["config_flow"] is True
    assert "homeassistant" not in manifest


def test_hacs_declares_minimum_home_assistant_version() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text())

    assert hacs["homeassistant"] == "2026.6.4"


def test_user_schema_exposes_username_and_password() -> None:
    assert get_user_schema_keys() == (CONF_USERNAME, CONF_PASSWORD)


def test_config_flow_uses_product_title_for_entry() -> None:
    assert DEFAULT_TITLE == "Kitafino Meal Plan"


def test_duplicate_setup_abort_reason_is_safe() -> None:
    assert get_duplicate_setup_abort_reason(True) == "already_configured"
    assert get_duplicate_setup_abort_reason(False) is None


def test_valid_credentials_return_redacted_entry_data() -> None:
    async def validator(username: str, password: str) -> None:
        assert username == "parent@example.test"
        assert password == "super-secret"

    result = asyncio.run(
        async_validate_user_input(
            {CONF_USERNAME: "parent@example.test", CONF_PASSWORD: "super-secret"},
            validator=validator,
        )
    )

    assert result.errors == {}
    assert result.data == {
        CONF_USERNAME: "parent@example.test",
        CONF_PASSWORD: "super-secret",
    }


def test_username_is_trimmed_before_storage() -> None:
    async def validator(username: str, password: str) -> None:
        assert username == "parent@example.test"
        assert password == "super-secret"

    result = asyncio.run(
        async_validate_user_input(
            {CONF_USERNAME: " parent@example.test ", CONF_PASSWORD: "super-secret"},
            validator=validator,
        )
    )

    assert result.data[CONF_USERNAME] == "parent@example.test"


@pytest.mark.parametrize(
    "user_input",
    [
        {},
        {CONF_USERNAME: "parent@example.test"},
        {CONF_PASSWORD: "super-secret"},
        {CONF_USERNAME: 123, CONF_PASSWORD: "super-secret"},
        {CONF_USERNAME: "parent@example.test", CONF_PASSWORD: object()},
    ],
)
def test_missing_or_malformed_credentials_return_invalid_auth(
    user_input: dict[str, object],
) -> None:
    result = asyncio.run(async_validate_user_input(user_input))

    assert result.errors == {"base": "invalid_auth"}
    assert result.data == {}


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("", "super-secret"),
        ("   ", "super-secret"),
        ("parent@example.test", ""),
        ("parent@example.test", "   "),
    ],
)
def test_client_rejects_blank_or_whitespace_credentials(
    username: str,
    password: str,
) -> None:
    client = KitafinoClient(username, password)

    with pytest.raises(KitafinoInvalidAuthError):
        asyncio.run(client.async_validate_credentials())


@pytest.mark.parametrize(
    ("exception", "expected_error"),
    [
        (KitafinoInvalidAuthError(), "invalid_auth"),
        (KitafinoCannotConnectError(), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
def test_validation_errors_map_to_safe_form_errors(
    exception: Exception, expected_error: str
) -> None:
    async def validator(username: str, password: str) -> None:
        raise exception

    result = asyncio.run(
        async_validate_user_input(
            {CONF_USERNAME: "parent@example.test", CONF_PASSWORD: "super-secret"},
            validator=validator,
        )
    )

    assert result.errors == {"base": expected_error}
    assert result.data == {}
