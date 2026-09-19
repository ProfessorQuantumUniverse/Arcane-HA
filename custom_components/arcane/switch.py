"""Switch platform for the Arcane integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ArcaneConfigEntry
from .api import ArcaneError
from .const import CONF_ALLOW_CONTROL, DOMAIN
from .entity import ArcaneContainerEntity, ArcaneProjectEntity
from .helpers import action_error, async_setup_entities
from .permissions import CONTAINER_ACTION_PERMISSIONS, PROJECT_ACTION_PERMISSIONS

PARALLEL_UPDATES = 1

# Both switches are the primary entity of their device, so they inherit the
# device name instead of carrying one of their own.
CONTAINER_SWITCH = SwitchEntityDescription(
    key="container",
    device_class=SwitchDeviceClass.SWITCH,
)

PROJECT_SWITCH = SwitchEntityDescription(
    key="project",
    device_class=SwitchDeviceClass.SWITCH,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArcaneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Arcane switches."""
    coordinator = entry.runtime_data
    if not coordinator.option(CONF_ALLOW_CONTROL):
        return

    async_setup_entities(
        coordinator,
        async_add_entities,
        containers=lambda environment_id, name: [
            ArcaneContainerSwitch(coordinator, environment_id, name, CONTAINER_SWITCH)
        ],
        projects=lambda environment_id, project_id: [
            ArcaneProjectSwitch(coordinator, environment_id, project_id, PROJECT_SWITCH)
        ],
    )


class ArcaneContainerSwitch(ArcaneContainerEntity, SwitchEntity):
    """Start and stop a container."""

    _attr_name = None

    @property
    def is_on(self) -> bool | None:
        """Return whether the container is running."""
        if (container := self.container) is None:
            return None
        return container.is_running

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the container."""
        await self._async_action("start")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the container."""
        await self._async_action("stop")

    async def _async_action(self, action: str) -> None:
        """Run a container action and refresh the coordinator."""
        if (container := self.container) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="container_not_found",
                translation_placeholders={"name": self.container_name},
            )
        try:
            await self.coordinator.client.async_container_action(
                self.environment_id, container.id, action
            )
        except ArcaneError as err:
            raise action_error(
                self.coordinator,
                err,
                permission=CONTAINER_ACTION_PERMISSIONS[action],
                action_key="container_action",
                placeholders={"action": action, "name": self.container_name},
            ) from err
        await self.coordinator.async_request_refresh()


class ArcaneProjectSwitch(ArcaneProjectEntity, SwitchEntity):
    """Deploy and stop a compose project."""

    _attr_name = None

    @property
    def is_on(self) -> bool | None:
        """Return whether at least one service of the project runs."""
        if (project := self.project) is None:
            return None
        return project.is_running

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Deploy the project."""
        await self._async_action("up")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the project."""
        await self._async_action("down")

    async def _async_action(self, action: str) -> None:
        """Run a project action and refresh the coordinator."""
        try:
            await self.coordinator.client.async_project_action(
                self.environment_id, self.project_id, action
            )
        except ArcaneError as err:
            raise action_error(
                self.coordinator,
                err,
                permission=PROJECT_ACTION_PERMISSIONS[action],
                action_key="project_action",
                placeholders={
                    "action": action,
                    "name": self.project.name if self.project else self.project_id,
                },
            ) from err
        await self.coordinator.async_request_refresh()
