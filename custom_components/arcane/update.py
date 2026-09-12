"""Update platform for the Arcane integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ArcaneConfigEntry
from .api import ArcaneError
from .const import CONF_ALLOW_CONTROL, CONF_UPDATE_ENTITIES, DOMAIN
from .entity import ArcaneContainerEntity
from .helpers import async_setup_entities

PARALLEL_UPDATES = 1

CONTAINER_UPDATE = UpdateEntityDescription(
    key="image_update",
    translation_key="image_update",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArcaneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Arcane update entities."""
    coordinator = entry.runtime_data
    if not coordinator.option(CONF_UPDATE_ENTITIES):
        return

    async_setup_entities(
        coordinator,
        async_add_entities,
        containers=lambda environment_id, name: [
            ArcaneContainerUpdate(coordinator, environment_id, name, CONTAINER_UPDATE)
        ],
    )


class ArcaneContainerUpdate(ArcaneContainerEntity, UpdateEntity):
    """Report and install a newer image for a container.

    Installing runs Arcane's redeploy, which pulls the image the container was
    created from and recreates the container with the same configuration.
    """

    @property
    def supported_features(self) -> UpdateEntityFeature:
        """Return whether this entity may install the update."""
        if self.coordinator.option(CONF_ALLOW_CONTROL):
            return UpdateEntityFeature.INSTALL
        return UpdateEntityFeature(0)

    @property
    def installed_version(self) -> str | None:
        """Return the version the container currently runs."""
        return self.container.installed_version if self.container else None

    @property
    def latest_version(self) -> str | None:
        """Return the newest version Arcane found for the image."""
        return self.container.latest_version if self.container else None

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Pull the newer image and recreate the container."""
        if (container := self.container) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="container_not_found",
                translation_placeholders={"name": self.container_name},
            )
        try:
            await self.coordinator.client.async_container_action(
                self.environment_id, container.id, "redeploy"
            )
        except ArcaneError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="container_action_failed",
                translation_placeholders={
                    "action": "redeploy",
                    "name": self.container_name,
                    "error": str(err),
                },
            ) from err
        await self.coordinator.async_request_refresh()
