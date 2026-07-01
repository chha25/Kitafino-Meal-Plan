"""Config flow for Speiseplan."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .const import (
    CHILD_SLUG_MAX_LENGTH,
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


CHILD_SLUG_PATTERN = re.compile(r"^[a-z0-9_]+$")
UPDATE_TIME_PATTERN = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


def _user_schema_dict() -> dict[Any, type[str]]:
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
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): password_field,
        }

    return {
        CONF_USERNAME: str,
        CONF_PASSWORD: str,
    }


def get_user_schema_keys() -> tuple[str, str]:
    """Return user-step schema keys for local tests."""
    return (CONF_USERNAME, CONF_PASSWORD)


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


async def async_validate_user_input(
    user_input: dict[str, Any],
    *,
    validator: CredentialValidator | None = None,
) -> ValidationResult:
    """Validate submitted credentials and map failures to safe form errors."""
    username = user_input.get(CONF_USERNAME)
    password = user_input.get(CONF_PASSWORD)
    if not isinstance(username, str) or not isinstance(password, str):
        return ValidationResult(data={}, errors={"base": "invalid_auth"})

    data = {
        CONF_USERNAME: username.strip(),
        CONF_PASSWORD: password,
    }
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
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            if reason := get_duplicate_setup_abort_reason(
                bool(self._async_current_entries())
            ):
                return self.async_abort(reason=reason)

            if user_input is not None:
                result = await async_validate_user_input(user_input)
                if not result.errors:
                    return self.async_create_entry(
                        title=DEFAULT_TITLE,
                        data=result.data,
                    )

                return self.async_show_form(
                    step_id="user",
                    data_schema=build_user_schema(),
                    errors=result.errors,
                )

            return self.async_show_form(step_id="user", data_schema=build_user_schema())

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
            if user_input is not None:
                result = normalize_options_input(user_input)
                if not result.errors:
                    return self.async_create_entry(title="", data=result.data)

                return self.async_show_form(
                    step_id="init",
                    data_schema=build_options_schema(
                        {**current_options, **user_input}
                    ),
                    errors=result.errors,
                )

            return self.async_show_form(
                step_id="init",
                data_schema=build_options_schema(current_options),
            )
