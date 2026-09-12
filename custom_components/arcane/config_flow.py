"""Config flow for the Arcane integration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_KEY, CONF_URL, CONF_VERIFY_SSL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    ArcaneAuthenticationError,
    ArcaneClient,
    ArcaneConnectionError,
    ArcaneError,
    ArcanePermissionError,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        ),
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_VERIFY_SSL, default=True): bool,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


def _normalize_url(url: str) -> str:
    """Return the instance URL without a trailing slash and with a scheme."""
    url = url.strip().rstrip("/")
    if "://" not in url:
        url = f"http://{url}"
    return url


class ArcaneConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Arcane config flow."""

    VERSION = 1

    def _async_url_taken(self, url: str, entry_id: str) -> bool:
        """Return whether another entry already points at this instance."""
        return any(
            entry.entry_id != entry_id and entry.data.get(CONF_URL) == url
            for entry in self._async_current_entries()
        )

    async def _async_validate(self, data: dict[str, Any]) -> tuple[str, str | None]:
        """Check the credentials and return the instance name and version.

        Raises the API errors so the calling step can map them onto form
        errors.
        """
        client = ArcaneClient(
            async_get_clientsession(self.hass, verify_ssl=data[CONF_VERIFY_SSL]),
            data[CONF_URL],
            data[CONF_API_KEY],
        )
        version = await client.async_get_version()
        # Listing environments also proves the key carries usable permissions.
        await client.async_get_environments()
        host = urlparse(data[CONF_URL]).hostname or data[CONF_URL]
        return host, version.get("currentVersion")

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_URL] = _normalize_url(user_input[CONF_URL])
            self._async_abort_entries_match({CONF_URL: user_input[CONF_URL]})
            try:
                host, _version = await self._async_validate(user_input)
            except ArcaneAuthenticationError:
                errors["base"] = "invalid_auth"
            except ArcanePermissionError:
                errors["base"] = "insufficient_permissions"
            except ArcaneConnectionError:
                errors["base"] = "cannot_connect"
            except ArcaneError:
                errors["base"] = "unknown"
            except Exception:
                _LOGGER.exception("Unexpected error while connecting to Arcane")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=host, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle a new API key after the old one stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for and verify a new API key."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            data = {**entry.data, **user_input}
            try:
                await self._async_validate(data)
            except ArcaneAuthenticationError:
                errors["base"] = "invalid_auth"
            except ArcanePermissionError:
                errors["base"] = "insufficient_permissions"
            except ArcaneConnectionError:
                errors["base"] = "cannot_connect"
            except ArcaneError:
                errors["base"] = "unknown"
            except Exception:
                _LOGGER.exception("Unexpected error while connecting to Arcane")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={"url": entry.data[CONF_URL]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the URL, API key or TLS verification of an entry."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            user_input[CONF_URL] = _normalize_url(user_input[CONF_URL])
            if self._async_url_taken(user_input[CONF_URL], entry.entry_id):
                return self.async_abort(reason="already_configured")
            try:
                await self._async_validate(user_input)
            except ArcaneAuthenticationError:
                errors["base"] = "invalid_auth"
            except ArcanePermissionError:
                errors["base"] = "insufficient_permissions"
            except ArcaneConnectionError:
                errors["base"] = "cannot_connect"
            except ArcaneError:
                errors["base"] = "unknown"
            except Exception:
                _LOGGER.exception("Unexpected error while connecting to Arcane")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(entry, data=user_input)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input or dict(entry.data)
            ),
            errors=errors,
        )
