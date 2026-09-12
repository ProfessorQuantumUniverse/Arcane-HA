"""Button platform for the Arcane integration."""

from __future__ import annotations

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ArcaneConfigEntry
from .api import ArcaneError
from .const import CONF_ALLOW_CONTROL, DOMAIN
from .entity import ArcaneContainerEntity, ArcaneProjectEntity
from .helpers import async_setup_entities

PARALLEL_UPDATES = 1

CONTAINER_RESTART_BUTTON = ButtonEntityDescription(
    key="restart",
    translation_key="restart",
    device_class=ButtonDeviceClass.RESTART,
)

PROJECT_RESTART_BUTTON = ButtonEntityDescription(
    key="restart",
    translation_key="restart",
    device_class=ButtonDeviceClass.RESTART,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArcaneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Arcane buttons."""
    coordinator = entry.runtime_data
    if not coordinator.option(CONF_ALLOW_CONTROL):
        return

    async_setup_entities(
        coordinator,
        async_add_entities,
        containers=lambda environment_id, name: [
            ArcaneContainerRestartButton(
                coordinator, environment_id, name, CONTAINER_RESTART_BUTTON
            )
        ],
        projects=lambda environment_id, project_id: [
            ArcaneProjectRestartButton(
                coordinator, environment_id, project_id, PROJECT_RESTART_BUTTON
            )
        ],
    )


class ArcaneContainerRestartButton(ArcaneContainerEntity, ButtonEntity):
    """Restart a container."""

    async def async_press(self) -> None:
        """Restart the container."""
        if (container := self.container) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="container_not_found",
                translation_placeholders={"name": self.container_name},
            )
        try:
            await self.coordinator.client.async_container_action(
                self.environment_id, container.id, "restart"
            )
        except ArcaneError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="container_action_failed",
                translation_placeholders={
                    "action": "restart",
                    "name": self.container_name,
                    "error": str(err),
                },
            ) from err
        await self.coordinator.async_request_refresh()


class ArcaneProjectRestartButton(ArcaneProjectEntity, ButtonEntity):
    """Restart every service of a compose project."""

    async def async_press(self) -> None:
        """Restart the project."""
        try:
            await self.coordinator.client.async_project_action(
                self.environment_id, self.project_id, "restart"
            )
        except ArcaneError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="project_action_failed",
                translation_placeholders={
                    "action": "restart",
                    "name": self.project.name if self.project else self.project_id,
                    "error": str(err),
                },
            ) from err
        await self.coordinator.async_request_refresh()
