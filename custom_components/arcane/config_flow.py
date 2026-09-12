"""Config flow for the Arcane integration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
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
    validate_url,
)
from .const import (
    CONF_ALLOW_CONTROL,
    CONF_ENVIRONMENTS,
    CONF_INCLUDE_HIDDEN,
    CONF_INCLUDE_INTERNAL,
    CONF_MONITOR_CONTAINERS,
    CONF_MONITOR_PROJECTS,
    CONF_MONITOR_RESOURCES,
    CONF_UPDATE_ENTITIES,
    DEFAULT_OPTIONS,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

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
    """Return the instance URL with a scheme and without a trailing slash.

    Raises ``ValueError`` for anything that is not a plain http or https
    address.
    """
    url = url.strip()
    if "://" not in url:
        url = f"http://{url}"
    return validate_url(url)


class ArcaneConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Arcane config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ArcaneOptionsFlow:
        """Return the options flow."""
        return ArcaneOptionsFlow()

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
        try:
            client = ArcaneClient(
                async_get_clientsession(self.hass, verify_ssl=data[CONF_VERIFY_SSL]),
                data[CONF_URL],
                data[CONF_API_KEY],
            )
        except ValueError as err:
            raise ArcaneAuthenticationError(str(err)) from err
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
            try:
                user_input[CONF_URL] = _normalize_url(user_input[CONF_URL])
            except ValueError:
                errors["base"] = "invalid_url"
        if user_input is not None and not errors:
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
            try:
                user_input[CONF_URL] = _normalize_url(user_input[CONF_URL])
            except ValueError:
                errors["base"] = "invalid_url"
            else:
                if self._async_url_taken(user_input[CONF_URL], entry.entry_id):
                    return self.async_abort(reason="already_configured")
        if user_input is not None and not errors:
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


class ArcaneOptionsFlow(OptionsFlow):
    """Let the user tune what is polled and what may be controlled."""

    async def _async_environment_options(self) -> list[SelectOptionDict]:
        """Return every environment that can be picked.

        The list is read from Arcane so environments added after setup show up.
        If the instance cannot be reached, the currently selected IDs are
        offered so an existing choice is never silently dropped.
        """
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is not None:
            try:
                environments = await coordinator.client.async_get_environments()
            except ArcaneError:
                environments = []
            if environments:
                return [
                    SelectOptionDict(
                        value=str(item["id"]),
                        label=str(item.get("name") or item["id"]),
                    )
                    for item in environments
                    if item.get("id") is not None
                ]
        return [
            SelectOptionDict(value=value, label=value)
            for value in self.config_entry.options.get(CONF_ENVIRONMENTS, [])
        ]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and store the options."""
        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            return self.async_create_entry(data=user_input)

        options = {**DEFAULT_OPTIONS, **self.config_entry.options}

        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=5,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_ENVIRONMENTS): SelectSelector(
                    SelectSelectorConfig(
                        options=await self._async_environment_options(),
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(CONF_MONITOR_CONTAINERS): bool,
                vol.Required(CONF_MONITOR_PROJECTS): bool,
                vol.Required(CONF_MONITOR_RESOURCES): bool,
                vol.Required(CONF_UPDATE_ENTITIES): bool,
                vol.Required(CONF_ALLOW_CONTROL): bool,
                vol.Required(CONF_INCLUDE_INTERNAL): bool,
                vol.Required(CONF_INCLUDE_HIDDEN): bool,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, options),
        )
