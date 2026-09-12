"""The Arcane integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_URL, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ArcaneClient
from .const import DOMAIN
from .coordinator import ArcaneCoordinator

_LOGGER = logging.getLogger(__name__)

type ArcaneConfigEntry = ConfigEntry[ArcaneCoordinator]

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]


async def async_setup_entry(hass: HomeAssistant, entry: ArcaneConfigEntry) -> bool:
    """Set up Arcane from a config entry."""
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, True)
    if not verify_ssl:
        _LOGGER.warning(
            "Certificate verification is disabled for %s. The API key is sent "
            "over a connection that is not authenticated",
            entry.data[CONF_URL],
        )

    try:
        client = ArcaneClient(
            async_get_clientsession(hass, verify_ssl=verify_ssl),
            entry.data[CONF_URL],
            entry.data[CONF_API_KEY],
        )
    except ValueError as err:
        raise ConfigEntryError(str(err)) from err

    coordinator = ArcaneCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ArcaneConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: ArcaneConfigEntry) -> None:
    """Reload the entry so changed options take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: ArcaneConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow removing devices for resources Arcane no longer reports."""
    known: set[str] = set()
    for environment_id, environment in entry.runtime_data.data.environments.items():
        prefix = f"{entry.entry_id}_{environment_id}"
        known.add(prefix)
        known.update(f"{prefix}_container_{name}" for name in environment.containers)
        known.update(f"{prefix}_project_{key}" for key in environment.projects)

    return not any(
        identifier in known
        for domain, identifier in device_entry.identifiers
        if domain == DOMAIN
    )
