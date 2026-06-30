"""Config flow skeleton for Speiseplan."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN

try:
    from homeassistant import config_entries
    import voluptuous as vol
except ModuleNotFoundError:  # pragma: no cover - local scaffold without HA installed
    config_entries = None  # type: ignore[assignment]
    vol = None  # type: ignore[assignment]


if config_entries is not None:

    class SpeiseplanConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
        """Handle a config flow for Speiseplan."""

        VERSION = 1

        async def async_step_user(
            self, user_input: dict[str, Any] | None = None
        ) -> Any:
            """Show the setup shell without persisting unvalidated data."""
            if self._async_current_entries():
                return self.async_abort(reason="already_configured")

            if user_input is not None:
                return self.async_abort(reason="not_implemented")

            return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

else:

    class SpeiseplanConfigFlow:
        """Import-safe placeholder used when Home Assistant is unavailable."""

        VERSION = 1
