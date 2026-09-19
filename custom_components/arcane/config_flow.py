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
    CONF_ENTITY_PREFIX,
    CONF_ENVIRONMENTS,
    CONF_EVENTS,
    CONF_HEALTH_SENSORS,
    CONF_HOST_STATS,
    CONF_INCLUDE_HIDDEN,
    CONF_INCLUDE_INTERNAL,
    CONF_MONITOR_CONTAINERS,
    CONF_MONITOR_PROJECTS,
    CONF_MONITOR_RESOURCES,
    CONF_NEST_CONTAINERS,
    CONF_PRUNE_BUTTON,
    CONF_REDEPLOY_BUTTONS,
    CONF_UPDATE_ENTITIES,
    DEFAULT_OPTIONS,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    PRUNE_MODES,
)
from .permissions import format_permissions, required_permissions

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

# The API key is deliberately optional here and never suggested back: filling
# the stored key into the form would hand it to the browser for no reason.
STEP_RECONFIGURE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        ),
        vol.Optional(CONF_API_KEY): TextSelector(
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
            # An empty key field means "keep the one already stored".
            if not user_input.get(CONF_API_KEY):
                user_input[CONF_API_KEY] = entry.data[CONF_API_KEY]
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
                STEP_RECONFIGURE_DATA_SCHEMA,
                {
                    CONF_URL: entry.data[CONF_URL],
                    CONF_VERIFY_SSL: entry.data.get(CONF_VERIFY_SSL, True),
                },
            ),
            errors=errors,
        )


class ArcaneOptionsFlow(OptionsFlow):
    """Let the user tune what is polled, what exists and what may be pressed."""

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

    def _save(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        """Merge one section into the stored options."""
        options = {**DEFAULT_OPTIONS, **self.config_entry.options, **user_input}
        options[CONF_SCAN_INTERVAL] = int(options[CONF_SCAN_INTERVAL])
        return self.async_create_entry(data=options)

    def _form(self, step_id: str, schema: vol.Schema) -> ConfigFlowResult:
        """Show one section, filled in with the values in use."""
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                schema, {**DEFAULT_OPTIONS, **self.config_entry.options}
            ),
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the groups of options."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["polling", "entities", "control", "permissions"],
        )

    async def async_step_permissions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """List the API key permissions the options in use need.

        Arcane refuses a call the key is not allowed to make, which otherwise
        only shows up as an empty sensor or a failed button press. The list is
        built from the options, so it names exactly what the enabled parts
        need, and what Arcane has already refused is called out on top.
        """
        if user_input is not None:
            return await self.async_step_init()

        options = {**DEFAULT_OPTIONS, **self.config_entry.options}
        needed = required_permissions(options)
        coordinator = getattr(self.config_entry, "runtime_data", None)
        missing = coordinator.missing_permissions if coordinator is not None else []

        return self.async_show_form(
            step_id="permissions",
            data_schema=vol.Schema({}),
            description_placeholders={
                "monitoring": format_permissions(needed.monitoring),
                "control": format_permissions(needed.control),
                "missing": format_permissions(missing),
            },
        )

    async def async_step_polling(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the polling options."""
        if user_input is not None:
            return self._save(user_input)

        return self._form(
            "polling",
            vol.Schema(
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
                    vol.Required(CONF_HOST_STATS): bool,
                    vol.Required(CONF_INCLUDE_INTERNAL): bool,
                    vol.Required(CONF_INCLUDE_HIDDEN): bool,
                }
            ),
        )

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the entity options."""
        if user_input is not None:
            return self._save(user_input)

        return self._form(
            "entities",
            vol.Schema(
                {
                    vol.Required(CONF_UPDATE_ENTITIES): bool,
                    vol.Required(CONF_HEALTH_SENSORS): bool,
                    vol.Required(CONF_ENTITY_PREFIX): bool,
                    vol.Required(CONF_NEST_CONTAINERS): bool,
                    vol.Required(CONF_EVENTS): bool,
                }
            ),
        )

    async def async_step_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show what Home Assistant may change on the Docker host."""
        if user_input is not None:
            return self._save(user_input)

        return self._form(
            "control",
            vol.Schema(
                {
                    vol.Required(CONF_ALLOW_CONTROL): bool,
                    vol.Required(CONF_REDEPLOY_BUTTONS): bool,
                    vol.Required(CONF_PRUNE_BUTTON): SelectSelector(
                        SelectSelectorConfig(
                            options=PRUNE_MODES,
                            translation_key="prune_button",
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )
