"""Config flow for Speiseplan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .const import CONF_PASSWORD, CONF_USERNAME, DEFAULT_TITLE, DOMAIN
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
