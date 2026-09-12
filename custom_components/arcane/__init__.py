"""The Arcane integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_URL, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ArcaneClient
from .const import DOMAIN
from .coordinator import ArcaneCoordinator

type ArcaneConfigEntry = ConfigEntry[ArcaneCoordinator]

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ArcaneConfigEntry) -> bool:
    """Set up Arcane from a config entry."""
    client = ArcaneClient(
        async_get_clientsession(hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, True)),
        entry.data[CONF_URL],
        entry.data[CONF_API_KEY],
    )

    coordinator = ArcaneCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ArcaneConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: ArcaneConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow removing devices for containers or projects Arcane no longer has."""
    known = {
        f"{entry.entry_id}_{environment_id}"
        for environment_id in entry.runtime_data.data.environments
    }
    for environment_id, environment in entry.runtime_data.data.environments.items():
        prefix = f"{entry.entry_id}_{environment_id}"
        known.update(f"{prefix}_container_{name}" for name in environment.containers)
        known.update(f"{prefix}_project_{key}" for key in environment.projects)

    return not any(
        identifier in known
        for domain, identifier in device_entry.identifiers
        if domain == DOMAIN
    )
