"""Config flow for Speiseplan."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .const import (
    CHILD_SLUG_MAX_LENGTH,
    CHILD_SLUG_RESERVED,
    CONF_CHILD_SLUG,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_MQTT_ENABLED,
    DEFAULT_SHARED_SOURCE,
    DEFAULT_TITLE,
    DEFAULT_UPDATE_TIME,
    DOMAIN,
    OPTION_CHILDREN,
    OPTION_CHILDREN_TEXT,
    OPTION_MQTT_ENABLED,
    OPTION_SHARED_SOURCE,
    OPTION_UPDATE_TIME,
)
from .kitafino.client import CredentialValidator, KitafinoClient
from .kitafino.errors import (
    KitafinoCannotConnectError,
    KitafinoInvalidAuthError,
    KitafinoValidationError,
)

try:
    from homeassistant import config_entries
    from homeassistant.helpers import selector
    import voluptuous as vol
except ModuleNotFoundError:  # pragma: no cover - local scaffold without HA installed
    config_entries = None  # type: ignore[assignment]
    selector = None  # type: ignore[assignment]
    vol = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating submitted config-flow credentials."""

    data: dict[str, str]
    errors: dict[str, str]


@dataclass(frozen=True)
class ChildrenParseResult:
    """Result of parsing manually configured child rows."""

    children: list[dict[str, str]]
    errors: dict[str, str]


@dataclass(frozen=True)
class OptionsValidationResult:
    """Result of validating submitted options."""

    data: dict[str, Any]
    errors: dict[str, str]


@dataclass(frozen=True)
class CredentialUpdateResult:
    """Result of validating a credential update for an existing entry."""

    entry_data: dict[str, Any]
    data_updates: dict[str, str]
    errors: dict[str, str]
    action: str


CHILD_SLUG_PATTERN = re.compile(r"^[a-z0-9_]+$")
UPDATE_TIME_PATTERN = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
OPTION_KEYS = {
    OPTION_CHILDREN,
    OPTION_CHILDREN_TEXT,
    OPTION_UPDATE_TIME,
    OPTION_MQTT_ENABLED,
    OPTION_SHARED_SOURCE,
}


def _user_schema_dict() -> dict[Any, Any]:
    """Return the config-flow schema mapping."""
    if vol is not None:
        password_field: Any = str
        if selector is not None:
            password_field = selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.PASSWORD,
                )
            )

        return {
            vol.Required(CONF_CHILD_SLUG): str,
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): password_field,
        }

    return {
        CONF_CHILD_SLUG: str,
        CONF_USERNAME: str,
        CONF_PASSWORD: str,
    }


def get_user_schema_keys() -> tuple[str, str, str]:
    """Return user-step schema keys for local tests."""
    return (CONF_CHILD_SLUG, CONF_USERNAME, CONF_PASSWORD)


def normalize_child_slug(value: Any) -> str | None:
    """Return a valid new-entry slug, reserving legacy shared identity."""
    if not isinstance(value, str):
        return None
    slug = value.strip()
    if (
        not slug
        or len(slug) > CHILD_SLUG_MAX_LENGTH
        or slug in CHILD_SLUG_RESERVED
        or CHILD_SLUG_PATTERN.fullmatch(slug) is None
    ):
        return None
    return slug


def child_unique_id(slug: str) -> str:
    """Return the stable config-entry identity for a validated slug."""
    return f"{DOMAIN}:{slug}"


def config_entry_unique_id(entry: Any) -> str:
    """Return an existing identity or derive the compatible identity fallback."""
    unique_id = getattr(entry, "unique_id", None)
    if isinstance(unique_id, str) and unique_id:
        return unique_id
    data = getattr(entry, "data", {}) or {}
    slug = normalize_child_slug(data.get(CONF_CHILD_SLUG))
    return child_unique_id(slug) if slug is not None else DOMAIN


def configured_child_slugs(entries: list[Any]) -> set[str]:
    """Collect normalized new-entry slugs without inspecting credentials."""
    slugs: set[str] = set()
    for entry in entries:
        data = getattr(entry, "data", {}) or {}
        slug = normalize_child_slug(data.get(CONF_CHILD_SLUG))
        if slug is not None:
            slugs.add(slug)
    return slugs


def get_duplicate_setup_abort_reason(has_current_entries: bool) -> str | None:
    """Return the abort reason for duplicate setup attempts."""
    if has_current_entries:
        return "already_configured"

    return None


def build_user_schema() -> Any:
    """Build the Home Assistant config-flow schema."""
    if vol is None:
        return _user_schema_dict()

    return vol.Schema(_user_schema_dict())


def build_credential_update_schema() -> Any:
    """Build the Home Assistant credential update schema."""
    if vol is None:
        return {CONF_USERNAME: str, CONF_PASSWORD: str}
    schema = _user_schema_dict()
    return vol.Schema(
        {
            key: value
            for key, value in schema.items()
            if getattr(key, "schema", key) != CONF_CHILD_SLUG
        }
    )


def build_default_options() -> dict[str, Any]:
    """Return default options for a new config entry."""
    return {
        OPTION_CHILDREN: [],
        OPTION_UPDATE_TIME: DEFAULT_UPDATE_TIME,
        OPTION_MQTT_ENABLED: DEFAULT_MQTT_ENABLED,
        OPTION_SHARED_SOURCE: DEFAULT_SHARED_SOURCE,
    }


def _format_children_text(children: list[dict[str, str]]) -> str:
    """Format child dictionaries for the options form."""
    if not isinstance(children, list):
        return ""

    rows: list[str] = []
    for child in children:
        if not isinstance(child, dict):
            continue

        name = child.get("name")
        slug = child.get("slug")
        if isinstance(name, str) and isinstance(slug, str) and name and slug:
            rows.append(f"{name}:{slug}")

    return "\n".join(rows)


def options_with_defaults(existing_options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge existing options over stable defaults."""
    options = build_default_options()
    options[OPTION_CHILDREN_TEXT] = ""
    if existing_options:
        options.update(
            {
                key: value
                for key, value in existing_options.items()
                if key in options
            }
        )
        if not options.get(OPTION_CHILDREN_TEXT) and options.get(OPTION_CHILDREN):
            options[OPTION_CHILDREN_TEXT] = _format_children_text(
                options[OPTION_CHILDREN]
            )

    return options


def parse_children_text(children_text: str) -> ChildrenParseResult:
    """Parse one `Display Name:slug` child definition per line."""
    children: list[dict[str, str]] = []
    seen_slugs: set[str] = set()

    for raw_line in children_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if ":" not in line:
            return ChildrenParseResult(
                children=[],
                errors={"base": "invalid_child_row"},
            )

        name, slug = (part.strip() for part in line.split(":", 1))
        if not name:
            return ChildrenParseResult(
                children=[],
                errors={"base": "missing_child_name"},
            )

        if (
            not slug
            or len(slug) > CHILD_SLUG_MAX_LENGTH
            or CHILD_SLUG_PATTERN.fullmatch(slug) is None
        ):
            return ChildrenParseResult(
                children=[],
                errors={"base": "invalid_child_slug"},
            )

        if slug in seen_slugs:
            return ChildrenParseResult(
                children=[],
                errors={"base": "duplicate_child_slug"},
            )

        seen_slugs.add(slug)
        children.append({"name": name, "slug": slug})

    return ChildrenParseResult(children=children, errors={})


def normalize_options_input(user_input: dict[str, Any]) -> OptionsValidationResult:
    """Validate options form input and return normalized options."""
    options = options_with_defaults(user_input)
    update_time = options.get(OPTION_UPDATE_TIME)
    if not isinstance(update_time, str) or not UPDATE_TIME_PATTERN.fullmatch(
        update_time
    ):
        return OptionsValidationResult(data={}, errors={"base": "invalid_update_time"})

    children_text = options.get(OPTION_CHILDREN_TEXT, "")
    if not isinstance(children_text, str):
        return OptionsValidationResult(data={}, errors={"base": "invalid_child_row"})

    parsed_children = parse_children_text(children_text)
    if parsed_children.errors:
        return OptionsValidationResult(data={}, errors=parsed_children.errors)

    mqtt_enabled = options.get(OPTION_MQTT_ENABLED)
    shared_source = options.get(OPTION_SHARED_SOURCE)
    if not isinstance(mqtt_enabled, bool) or not isinstance(shared_source, bool):
        return OptionsValidationResult(data={}, errors={"base": "invalid_options"})

    return OptionsValidationResult(
        data={
            OPTION_CHILDREN: parsed_children.children,
            OPTION_UPDATE_TIME: update_time,
            OPTION_MQTT_ENABLED: mqtt_enabled,
            OPTION_SHARED_SOURCE: shared_source,
        },
        errors={},
    )


def _options_schema_dict(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Return the options schema mapping."""
    if vol is not None:
        return {
            vol.Optional(
                OPTION_CHILDREN_TEXT,
                default=defaults[OPTION_CHILDREN_TEXT],
            ): str,
            vol.Required(
                OPTION_UPDATE_TIME,
                default=defaults[OPTION_UPDATE_TIME],
            ): str,
            vol.Required(
                OPTION_MQTT_ENABLED,
                default=defaults[OPTION_MQTT_ENABLED],
            ): bool,
            vol.Required(
                OPTION_SHARED_SOURCE,
                default=defaults[OPTION_SHARED_SOURCE],
            ): bool,
        }

    return {
        OPTION_CHILDREN_TEXT: str,
        OPTION_UPDATE_TIME: str,
        OPTION_MQTT_ENABLED: bool,
        OPTION_SHARED_SOURCE: bool,
    }


def build_options_schema(existing_options: dict[str, Any] | None = None) -> Any:
    """Build the Home Assistant options-flow schema."""
    defaults = options_with_defaults(existing_options)
    schema_dict = _options_schema_dict(defaults)
    if vol is None:
        return schema_dict

    return vol.Schema(schema_dict)


def build_child_options_schema(
    existing_options: dict[str, Any] | None = None,
) -> Any:
    """Build child-entry options without legacy child/display-name controls."""
    defaults = options_with_defaults(existing_options)
    schema_dict: dict[Any, Any]
    if vol is None:
        schema_dict = {OPTION_UPDATE_TIME: str, OPTION_MQTT_ENABLED: bool}
    else:
        schema_dict = {
            vol.Required(
                OPTION_UPDATE_TIME,
                default=defaults[OPTION_UPDATE_TIME],
            ): str,
            vol.Required(
                OPTION_MQTT_ENABLED,
                default=defaults[OPTION_MQTT_ENABLED],
            ): bool,
        }
    return schema_dict if vol is None else vol.Schema(schema_dict)


def normalize_child_options_input(user_input: dict[str, Any]) -> OptionsValidationResult:
    """Validate only the non-identity options available to child entries."""
    options = options_with_defaults(user_input)
    update_time = options.get(OPTION_UPDATE_TIME)
    mqtt_enabled = options.get(OPTION_MQTT_ENABLED)
    if not isinstance(update_time, str) or not UPDATE_TIME_PATTERN.fullmatch(
        update_time
    ):
        return OptionsValidationResult(data={}, errors={"base": "invalid_update_time"})
    if not isinstance(mqtt_enabled, bool):
        return OptionsValidationResult(data={}, errors={"base": "invalid_options"})
    return OptionsValidationResult(
        data={OPTION_UPDATE_TIME: update_time, OPTION_MQTT_ENABLED: mqtt_enabled},
        errors={},
    )


async def async_validate_user_input(
    user_input: dict[str, Any],
    *,
    validator: CredentialValidator | None = None,
    require_child_slug: bool = False,
    existing_child_slugs: set[str] | None = None,
) -> ValidationResult:
    """Validate submitted credentials and map failures to safe form errors."""
    data: dict[str, str] = {}
    if require_child_slug:
        slug = normalize_child_slug(user_input.get(CONF_CHILD_SLUG))
        if slug is None:
            return ValidationResult(
                data={}, errors={CONF_CHILD_SLUG: "invalid_child_slug"}
            )
        if slug in (existing_child_slugs or set()):
            return ValidationResult(
                data={}, errors={CONF_CHILD_SLUG: "duplicate_child_slug"}
            )
        data[CONF_CHILD_SLUG] = slug

    username = user_input.get(CONF_USERNAME)
    password = user_input.get(CONF_PASSWORD)
    if not isinstance(username, str) or not isinstance(password, str):
        return ValidationResult(data={}, errors={"base": "invalid_auth"})

    data.update({CONF_USERNAME: username.strip(), CONF_PASSWORD: password})
    client = KitafinoClient(
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        validator=validator,
    )

    try:
        await client.async_validate_credentials()
    except KitafinoInvalidAuthError:
        return ValidationResult(data={}, errors={"base": "invalid_auth"})
    except KitafinoCannotConnectError:
        return ValidationResult(data={}, errors={"base": "cannot_connect"})
    except KitafinoValidationError:
        return ValidationResult(data={}, errors={"base": "unknown"})
    except Exception:  # pragma: no cover - defensive mapping for HA runtime
        return ValidationResult(data={}, errors={"base": "unknown"})

    return ValidationResult(data=data, errors={})


def merge_credential_update(
    existing_data: dict[str, Any],
    credential_data: dict[str, str],
) -> dict[str, Any]:
    """Merge credential updates into config-entry data without option keys."""
    safe_existing_data = {
        key: value
        for key, value in existing_data.items()
        if key not in OPTION_KEYS
    }
    return {**safe_existing_data, **credential_data}


async def async_validate_credential_update(
    existing_data: dict[str, Any],
    user_input: dict[str, Any],
    *,
    validator: CredentialValidator | None = None,
) -> CredentialUpdateResult:
    """Validate credentials for an existing config entry update."""
    result = await async_validate_user_input(user_input, validator=validator)
    if result.errors:
        return CredentialUpdateResult(
            entry_data={},
            data_updates={},
            errors=result.errors,
            action="show_form",
        )

    return CredentialUpdateResult(
        entry_data=merge_credential_update(existing_data, result.data),
        data_updates=result.data,
        errors={},
        action="update_existing_entry",
    )


if config_entries is not None:

    class SpeiseplanConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
        """Handle a config flow for Speiseplan."""

        VERSION = 1

        @staticmethod
        def async_get_options_flow(
            config_entry: Any,
        ) -> config_entries.OptionsFlow:
            """Create the options flow."""
            return SpeiseplanOptionsFlowHandler()

        async def async_step_user(
            self, user_input: dict[str, Any] | None = None
        ) -> Any:
            """Handle the initial user setup step."""
            if user_input is not None:
                result = await async_validate_user_input(
                    user_input,
                    require_child_slug=True,
                    existing_child_slugs=configured_child_slugs(
                        self._async_current_entries()
                    ),
                )
                if not result.errors:
                    slug = result.data[CONF_CHILD_SLUG]
                    await self.async_set_unique_id(child_unique_id(slug))
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=slug,
                        data=result.data,
                    )

                return self.async_show_form(
                    step_id="user",
                    data_schema=build_user_schema(),
                    errors=result.errors,
                )

            return self.async_show_form(step_id="user", data_schema=build_user_schema())

        async def async_step_reauth(
            self,
            entry_data: dict[str, Any],
        ) -> Any:
            """Handle a reauthentication request."""
            return await self.async_step_reauth_confirm()

        async def async_step_reauth_confirm(
            self,
            user_input: dict[str, Any] | None = None,
        ) -> Any:
            """Confirm and process reauthentication credentials."""
            if user_input is None:
                return self.async_show_form(
                    step_id="reauth_confirm",
                    data_schema=build_credential_update_schema(),
                )

            entry = self._get_reauth_entry()
            result = await async_validate_credential_update(entry.data, user_input)
            if result.errors:
                return self.async_show_form(
                    step_id="reauth_confirm",
                    data_schema=build_credential_update_schema(),
                    errors=result.errors,
                )

            await self.async_set_unique_id(config_entry_unique_id(entry))
            self._abort_if_unique_id_mismatch()
            self.hass.config_entries.async_update_entry(
                entry,
                data=result.entry_data,
            )
            return self.async_update_reload_and_abort(entry)

        async def async_step_reconfigure(
            self,
            user_input: dict[str, Any] | None = None,
        ) -> Any:
            """Handle credential reconfiguration for an existing entry."""
            if user_input is None:
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=build_credential_update_schema(),
                )

            entry = self._get_reconfigure_entry()
            result = await async_validate_credential_update(entry.data, user_input)
            if result.errors:
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=build_credential_update_schema(),
                    errors=result.errors,
                )

            await self.async_set_unique_id(config_entry_unique_id(entry))
            self._abort_if_unique_id_mismatch()
            self.hass.config_entries.async_update_entry(
                entry,
                data=result.entry_data,
            )
            return self.async_update_reload_and_abort(entry)

else:

    class SpeiseplanConfigFlow:
        """Import-safe placeholder used when Home Assistant is unavailable."""

        VERSION = 1


if config_entries is not None:

    class SpeiseplanOptionsFlowHandler(config_entries.OptionsFlow):
        """Handle Speiseplan options."""

        async def async_step_init(
            self,
            user_input: dict[str, Any] | None = None,
        ) -> Any:
            """Manage Speiseplan options."""
            current_options = getattr(self.config_entry, "options", {}) or {}
            entry_data = getattr(self.config_entry, "data", {}) or {}
            is_child_entry = CONF_CHILD_SLUG in entry_data
            if user_input is not None:
                result = (
                    normalize_child_options_input(user_input)
                    if is_child_entry
                    else normalize_options_input(user_input)
                )
                if not result.errors:
                    return self.async_create_entry(title="", data=result.data)

                return self.async_show_form(
                    step_id="init",
                    data_schema=(
                        build_child_options_schema({**current_options, **user_input})
                        if is_child_entry
                        else build_options_schema({**current_options, **user_input})
                    ),
                    errors=result.errors,
                )

            return self.async_show_form(
                step_id="init",
                data_schema=(
                    build_child_options_schema(current_options)
                    if is_child_entry
                    else build_options_schema(current_options)
                ),
            )
