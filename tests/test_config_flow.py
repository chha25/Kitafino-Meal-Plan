"""Tests for Speiseplan config-flow metadata."""

from __future__ import annotations

import json
from pathlib import Path
import asyncio
from types import SimpleNamespace

import pytest

from custom_components.speiseplan.const import (
    CONF_CHILD_SLUG,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_TITLE,
    OPTION_CHILDREN,
    OPTION_CHILDREN_TEXT,
    OPTION_MQTT_ENABLED,
    OPTION_SHARED_SOURCE,
    OPTION_UPDATE_TIME,
    WEEKDAYS,
)
from custom_components.speiseplan.config_flow import (
    async_validate_user_input,
    async_validate_credential_update,
    build_credential_update_schema,
    build_child_options_schema,
    build_default_options,
    normalize_options_input,
    options_with_defaults,
    get_duplicate_setup_abort_reason,
    get_user_schema_keys,
    child_unique_id,
    config_entry_unique_id,
    configured_child_slugs,
    normalize_child_options_input,
    parse_children_text,
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


def test_release_metadata_is_consistent() -> None:
    manifest = json.loads(
        (ROOT / "custom_components/speiseplan/manifest.json").read_text()
    )
    hacs = json.loads((ROOT / "hacs.json").read_text())
    version = manifest["version"]
    readme = (ROOT / "README.md").read_text()
    changelog = (ROOT / "CHANGELOG.md").read_text()

    assert version == "1.1.1"
    assert hacs["version"] == version
    assert f"Version `{version}` is prepared" in readme
    assert changelog.index(f"## [{version}] - 2026-07-21") > changelog.index(
        "## [Unreleased]"
    )
    assert (
        f"[{version}]: https://github.com/chha25/Kitafino-Meal-Plan/"
        f"releases/tag/v{version}"
    ) in changelog
    assert (
        f"[Unreleased]: https://github.com/chha25/Kitafino-Meal-Plan/"
        f"compare/v{version}...HEAD"
    ) in changelog


def test_user_schema_exposes_immutable_slug_and_credentials() -> None:
    assert get_user_schema_keys() == (CONF_CHILD_SLUG, CONF_USERNAME, CONF_PASSWORD)


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


@pytest.mark.parametrize("slug", ["", "shared", "Lena", "bad-slug", "a" * 33])
def test_new_entry_rejects_invalid_or_reserved_slug_before_auth(slug: str) -> None:
    auth_called = False

    async def validator(username: str, password: str) -> None:
        nonlocal auth_called
        auth_called = True

    result = asyncio.run(
        async_validate_user_input(
            {
                CONF_CHILD_SLUG: slug,
                CONF_USERNAME: "parent@example.test",
                CONF_PASSWORD: "secret",
            },
            validator=validator,
            require_child_slug=True,
        )
    )

    assert result.errors == {CONF_CHILD_SLUG: "invalid_child_slug"}
    assert auth_called is False


def test_duplicate_normalized_slug_is_rejected_before_remote_auth() -> None:
    auth_called = False

    async def validator(username: str, password: str) -> None:
        nonlocal auth_called
        auth_called = True

    result = asyncio.run(
        async_validate_user_input(
            {
                CONF_CHILD_SLUG: " lena ",
                CONF_USERNAME: "same@example.test",
                CONF_PASSWORD: "same-secret",
            },
            validator=validator,
            require_child_slug=True,
            existing_child_slugs={"lena"},
        )
    )

    assert result.errors == {CONF_CHILD_SLUG: "duplicate_child_slug"}
    assert auth_called is False


def test_distinct_slugs_accept_identical_credentials_and_have_distinct_ids() -> None:
    async def validator(username: str, password: str) -> None:
        return None

    results = [
        asyncio.run(
            async_validate_user_input(
                {
                    CONF_CHILD_SLUG: slug,
                    CONF_USERNAME: "same@example.test",
                    CONF_PASSWORD: "same-secret",
                },
                validator=validator,
                require_child_slug=True,
                existing_child_slugs={"lena"} if slug == "max" else set(),
            )
        )
        for slug in ("lena", "max")
    ]

    assert [result.errors for result in results] == [{}, {}]
    assert child_unique_id("lena") != child_unique_id("max")
    entries = [SimpleNamespace(data=result.data) for result in results]
    assert configured_child_slugs(entries) == {"lena", "max"}


def test_missing_unique_id_fallback_uses_validated_slug_or_legacy_domain() -> None:
    child_entry = SimpleNamespace(
        unique_id=None,
        data={CONF_CHILD_SLUG: "lena"},
    )
    legacy_entry = SimpleNamespace(unique_id=None, data={})

    assert config_entry_unique_id(child_entry) == "speiseplan:lena"
    assert config_entry_unique_id(legacy_entry) == "speiseplan"


def test_existing_unique_id_wins_over_derived_fallback() -> None:
    entry = SimpleNamespace(
        unique_id="existing-id",
        data={CONF_CHILD_SLUG: "lena"},
    )

    assert config_entry_unique_id(entry) == "existing-id"


def test_child_options_exclude_legacy_names_and_shared_source() -> None:
    schema = build_child_options_schema()
    result = normalize_child_options_input(
        {
            OPTION_UPDATE_TIME: "07:30",
            OPTION_MQTT_ENABLED: True,
            OPTION_CHILDREN_TEXT: "Other:other",
            OPTION_SHARED_SOURCE: True,
        }
    )

    assert tuple(schema.keys()) == (OPTION_UPDATE_TIME, OPTION_MQTT_ENABLED)
    assert result.data == {
        OPTION_UPDATE_TIME: "07:30",
        OPTION_MQTT_ENABLED: True,
    }


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


def test_successful_credential_update_preserves_existing_non_option_data() -> None:
    async def validator(username: str, password: str) -> None:
        assert username == "new@example.test"
        assert password == "new-secret"

    result = asyncio.run(
        async_validate_credential_update(
            {
                CONF_USERNAME: "old@example.test",
                CONF_PASSWORD: "old-secret",
                CONF_CHILD_SLUG: "lena",
                "future_setup_key": "preserve-me",
                OPTION_CHILDREN: [{"name": "Kind", "slug": "kind"}],
                OPTION_UPDATE_TIME: "06:00",
            },
            {CONF_USERNAME: " new@example.test ", CONF_PASSWORD: "new-secret"},
            validator=validator,
        )
    )

    assert result.errors == {}
    assert result.action == "update_existing_entry"
    assert result.data_updates == {
        CONF_USERNAME: "new@example.test",
        CONF_PASSWORD: "new-secret",
    }
    assert result.entry_data == {
        CONF_USERNAME: "new@example.test",
        CONF_PASSWORD: "new-secret",
        CONF_CHILD_SLUG: "lena",
        "future_setup_key": "preserve-me",
    }
    assert OPTION_CHILDREN not in result.entry_data
    assert OPTION_UPDATE_TIME not in result.entry_data


def test_credential_update_failure_returns_safe_errors() -> None:
    async def validator(username: str, password: str) -> None:
        raise KitafinoInvalidAuthError()

    result = asyncio.run(
        async_validate_credential_update(
            {CONF_USERNAME: "old@example.test", CONF_PASSWORD: "old-secret"},
            {CONF_USERNAME: "new@example.test", CONF_PASSWORD: "bad-secret"},
            validator=validator,
        )
    )

    assert result.errors == {"base": "invalid_auth"}
    assert result.data_updates == {}
    assert result.entry_data == {}


def test_credential_update_schema_keys_match_credentials() -> None:
    schema = build_credential_update_schema()

    assert tuple(schema.keys()) == (CONF_USERNAME, CONF_PASSWORD)


def test_default_options_are_stable_and_secret_free() -> None:
    options = build_default_options()

    assert options == {
        OPTION_CHILDREN: [],
        OPTION_UPDATE_TIME: "06:00",
        OPTION_MQTT_ENABLED: False,
        OPTION_SHARED_SOURCE: True,
    }
    assert CONF_USERNAME not in options
    assert CONF_PASSWORD not in options


def test_parse_children_text_normalizes_child_rows() -> None:
    result = parse_children_text("Lena:lena\n Max Mustermann:max_1 ")

    assert result.children == [
        {"name": "Lena", "slug": "lena"},
        {"name": "Max Mustermann", "slug": "max_1"},
    ]
    assert result.errors == {}


def test_legacy_child_row_keeps_historical_shared_slug_saveable() -> None:
    result = parse_children_text("Household:shared")

    assert result.children == [{"name": "Household", "slug": "shared"}]
    assert result.errors == {}


@pytest.mark.parametrize(
    ("children_text", "error"),
    [
        ("NoSeparator", "invalid_child_row"),
        (":slug", "missing_child_name"),
        ("Name:Bad-Slug", "invalid_child_slug"),
        ("One:kind\nTwo:kind", "duplicate_child_slug"),
    ],
)
def test_parse_children_text_rejects_invalid_rows(
    children_text: str,
    error: str,
) -> None:
    result = parse_children_text(children_text)

    assert result.children == []
    assert result.errors == {"base": error}


def test_normalize_options_input_returns_safe_options_payload() -> None:
    result = normalize_options_input(
        {
            OPTION_CHILDREN_TEXT: "Kind 1:kind_1",
            OPTION_UPDATE_TIME: "06:30",
            OPTION_MQTT_ENABLED: True,
            OPTION_SHARED_SOURCE: True,
            CONF_USERNAME: "should-not-survive",
            CONF_PASSWORD: "should-not-survive",
        }
    )

    assert result.errors == {}
    assert result.data == {
        OPTION_CHILDREN: [{"name": "Kind 1", "slug": "kind_1"}],
        OPTION_UPDATE_TIME: "06:30",
        OPTION_MQTT_ENABLED: True,
        OPTION_SHARED_SOURCE: True,
    }
    assert CONF_USERNAME not in result.data
    assert CONF_PASSWORD not in result.data
    assert OPTION_CHILDREN_TEXT not in result.data


@pytest.mark.parametrize("update_time", ["6:00", "24:00", "12:99", "nope"])
def test_normalize_options_input_rejects_invalid_update_time(
    update_time: str,
) -> None:
    result = normalize_options_input({OPTION_UPDATE_TIME: update_time})

    assert result.errors == {"base": "invalid_update_time"}
    assert result.data == {}


@pytest.mark.parametrize(
    "user_input",
    [
        {OPTION_MQTT_ENABLED: "false"},
        {OPTION_SHARED_SOURCE: "false"},
        {OPTION_MQTT_ENABLED: 1},
        {OPTION_SHARED_SOURCE: 0},
    ],
)
def test_normalize_options_input_rejects_non_boolean_flags(
    user_input: dict[str, object],
) -> None:
    result = normalize_options_input(user_input)

    assert result.errors == {"base": "invalid_options"}
    assert result.data == {}


def test_options_with_defaults_reconstructs_form_child_text() -> None:
    options = options_with_defaults(
        {
            OPTION_CHILDREN: [
                {"name": "Kind 1", "slug": "kind_1"},
                {"name": "Kind 2", "slug": "kind_2"},
            ]
        }
    )

    assert options[OPTION_CHILDREN_TEXT] == "Kind 1:kind_1\nKind 2:kind_2"


def test_options_with_defaults_ignores_malformed_persisted_children() -> None:
    options = options_with_defaults({OPTION_CHILDREN: ["broken", object()]})

    assert options[OPTION_CHILDREN_TEXT] == ""


def test_options_with_defaults_preserves_submitted_values_for_retry() -> None:
    options = options_with_defaults(
        {
            OPTION_CHILDREN_TEXT: "Broken Row",
            OPTION_UPDATE_TIME: "6:00",
            OPTION_MQTT_ENABLED: False,
            OPTION_SHARED_SOURCE: True,
        }
    )

    assert options[OPTION_CHILDREN_TEXT] == "Broken Row"
    assert options[OPTION_UPDATE_TIME] == "6:00"


def test_translation_files_include_options_labels_and_errors() -> None:
    for language in ("en", "de"):
        translations = json.loads(
            (ROOT / f"custom_components/speiseplan/translations/{language}.json").read_text()
        )

        options = translations["options"]
        option_step = options["step"]["init"]
        for option_key in (
            OPTION_CHILDREN_TEXT,
            OPTION_UPDATE_TIME,
            OPTION_MQTT_ENABLED,
            OPTION_SHARED_SOURCE,
        ):
            assert option_key in option_step["data"]
            assert option_key in option_step["data_description"]

        for error_key in (
            "invalid_child_row",
            "missing_child_name",
            "invalid_child_slug",
            "duplicate_child_slug",
            "invalid_options",
            "invalid_update_time",
        ):
            assert error_key in options["error"]


def test_translation_files_include_reauth_and_reconfigure_strings() -> None:
    for language in ("en", "de"):
        translations = json.loads(
            (ROOT / f"custom_components/speiseplan/translations/{language}.json").read_text()
        )

        config = translations["config"]
        assert CONF_CHILD_SLUG in config["step"]["user"]["data"]
        assert "invalid_child_slug" in config["error"]
        assert "duplicate_child_slug" in config["error"]
        for step_key in ("reauth_confirm", "reconfigure"):
            step = config["step"][step_key]
            assert step["title"]
            assert step["description"]
            assert CONF_USERNAME in step["data"]
            assert CONF_PASSWORD in step["data"]

        for error_key in ("invalid_auth", "cannot_connect", "unknown"):
            assert error_key in config["error"]

        assert "reauth_successful" in config["abort"]
        assert "reconfigure_successful" in config["abort"]
        assert "unique_id_mismatch" in config["abort"]


def test_translation_files_include_entity_and_service_strings() -> None:
    for language in ("en", "de"):
        translations = json.loads(
            (ROOT / f"custom_components/speiseplan/translations/{language}.json").read_text()
        )

        sensors = translations["entity"]["sensor"]
        assert sensors["health"]["name"]
        for weekday in WEEKDAYS:
            key = f"shared_current_{weekday}"
            assert key in sensors
            assert sensors[key]["name"]
            assert "shared" in sensors[key]["name"].lower() or "gemeinsam" in sensors[key]["name"].lower()
            assert "current" in sensors[key]["name"].lower() or "aktuell" in sensors[key]["name"].lower()

        refresh = translations["services"]["refresh"]
        assert refresh["name"]
        assert refresh["description"]
        assert refresh["fields"]["entry_id"]["name"]
        assert refresh["fields"]["entry_id"]["description"]
