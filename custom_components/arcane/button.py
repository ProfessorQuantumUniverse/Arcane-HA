"""Button platform for the Arcane integration."""

from __future__ import annotations

import logging

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
from .const import (
    CONF_ALLOW_CONTROL,
    CONF_PRUNE_BUTTON,
    CONF_REDEPLOY_BUTTONS,
    DOMAIN,
    PRUNE_OFF,
    PRUNE_UNUSED,
)
from .entity import ArcaneContainerEntity, ArcaneEnvironmentEntity, ArcaneProjectEntity
from .helpers import action_error, async_setup_entities
from .permissions import (
    CONTAINER_ACTION_PERMISSIONS,
    PERM_SYSTEM_PRUNE,
    PROJECT_ACTION_PERMISSIONS,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

RESTART_BUTTON = ButtonEntityDescription(
    key="restart",
    translation_key="restart",
    device_class=ButtonDeviceClass.RESTART,
)

REDEPLOY_BUTTON = ButtonEntityDescription(
    key="redeploy",
    translation_key="redeploy",
)

PRUNE_BUTTON = ButtonEntityDescription(
    key="prune",
    translation_key="prune",
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

    redeploy = coordinator.option(CONF_REDEPLOY_BUTTONS)
    prune = coordinator.option(CONF_PRUNE_BUTTON) != PRUNE_OFF

    async_setup_entities(
        coordinator,
        async_add_entities,
        environments=(
            (
                lambda environment_id: [
                    ArcanePruneButton(coordinator, environment_id, PRUNE_BUTTON)
                ]
            )
            if prune
            else None
        ),
        containers=lambda environment_id, name: [
            ArcaneContainerButton(coordinator, environment_id, name, RESTART_BUTTON),
            *(
                [
                    ArcaneContainerButton(
                        coordinator, environment_id, name, REDEPLOY_BUTTON
                    )
                ]
                if redeploy
                else []
            ),
        ],
        projects=lambda environment_id, project_id: [
            ArcaneProjectButton(
                coordinator, environment_id, project_id, RESTART_BUTTON
            ),
            *(
                [
                    ArcaneProjectButton(
                        coordinator, environment_id, project_id, REDEPLOY_BUTTON
                    )
                ]
                if redeploy
                else []
            ),
        ],
    )


class ArcaneContainerButton(ArcaneContainerEntity, ButtonEntity):
    """Run a container action that has no state of its own."""

    async def async_press(self) -> None:
        """Run the action this button stands for."""
        action = self.entity_description.key
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


class ArcaneProjectButton(ArcaneProjectEntity, ButtonEntity):
    """Run a compose project action that has no state of its own."""

    async def async_press(self) -> None:
        """Run the action this button stands for."""
        action = self.entity_description.key
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


class ArcanePruneButton(ArcaneEnvironmentEntity, ButtonEntity):
    """Remove unused images, networks and build cache from an environment.

    Containers and volumes are never pruned. Both hold state a user cannot get
    back, which is not something a single button press should be able to do.
    """

    async def async_press(self) -> None:
        """Run the prune."""
        aggressive = self.coordinator.option(CONF_PRUNE_BUTTON) == PRUNE_UNUSED
        try:
            result = await self.coordinator.client.async_prune(
                self.environment_id, unused_images=aggressive
            )
        except ArcaneError as err:
            raise action_error(
                self.coordinator,
                err,
                permission=PERM_SYSTEM_PRUNE,
                action_key="prune",
                placeholders={
                    "name": self.environment.name if self.environment else ""
                },
            ) from err
        _LOGGER.debug(
            "Prune of environment %s returned %s", self.environment_id, result
        )
        await self.coordinator.async_request_refresh()
