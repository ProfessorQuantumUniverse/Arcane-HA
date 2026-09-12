"""Binary sensor platform for the Arcane integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ArcaneConfigEntry
from .entity import (
    ArcaneContainerEntity,
    ArcaneEnvironmentEntity,
    ArcaneProjectEntity,
)
from .helpers import async_setup_entities
from .models import ArcaneContainer, ArcaneEnvironment, ArcaneProject

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ArcaneEnvironmentBinarySensorDescription(BinarySensorEntityDescription):
    """Describes an Arcane environment binary sensor."""

    value_fn: Callable[[ArcaneEnvironment], bool]


@dataclass(frozen=True, kw_only=True)
class ArcaneContainerBinarySensorDescription(BinarySensorEntityDescription):
    """Describes an Arcane container binary sensor."""

    value_fn: Callable[[ArcaneContainer], bool]


@dataclass(frozen=True, kw_only=True)
class ArcaneProjectBinarySensorDescription(BinarySensorEntityDescription):
    """Describes an Arcane compose project binary sensor."""

    value_fn: Callable[[ArcaneProject], bool]


ENVIRONMENT_BINARY_SENSORS: tuple[ArcaneEnvironmentBinarySensorDescription, ...] = (
    ArcaneEnvironmentBinarySensorDescription(
        key="online",
        translation_key="environment_online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda environment: environment.is_online,
    ),
)

CONTAINER_BINARY_SENSORS: tuple[ArcaneContainerBinarySensorDescription, ...] = (
    ArcaneContainerBinarySensorDescription(
        key="running",
        translation_key="container_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda container: container.is_running,
    ),
    ArcaneContainerBinarySensorDescription(
        key="update_available",
        translation_key="update_available",
        device_class=BinarySensorDeviceClass.UPDATE,
        value_fn=lambda container: container.update_available,
    ),
)

PROJECT_BINARY_SENSORS: tuple[ArcaneProjectBinarySensorDescription, ...] = (
    ArcaneProjectBinarySensorDescription(
        key="running",
        translation_key="project_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda project: project.is_running,
    ),
    ArcaneProjectBinarySensorDescription(
        key="update_available",
        translation_key="update_available",
        device_class=BinarySensorDeviceClass.UPDATE,
        value_fn=lambda project: project.update_available,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArcaneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Arcane binary sensors."""
    coordinator = entry.runtime_data

    async_setup_entities(
        coordinator,
        async_add_entities,
        environments=lambda environment_id: [
            ArcaneEnvironmentBinarySensor(coordinator, environment_id, description)
            for description in ENVIRONMENT_BINARY_SENSORS
        ],
        containers=lambda environment_id, name: [
            ArcaneContainerBinarySensor(coordinator, environment_id, name, description)
            for description in CONTAINER_BINARY_SENSORS
        ],
        projects=lambda environment_id, project_id: [
            ArcaneProjectBinarySensor(
                coordinator, environment_id, project_id, description
            )
            for description in PROJECT_BINARY_SENSORS
        ],
    )


class ArcaneEnvironmentBinarySensor(ArcaneEnvironmentEntity, BinarySensorEntity):
    """A binary sensor reporting the state of an environment."""

    entity_description: ArcaneEnvironmentBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        if (environment := self.environment) is None:
            return None
        return self.entity_description.value_fn(environment)


class ArcaneContainerBinarySensor(ArcaneContainerEntity, BinarySensorEntity):
    """A binary sensor reporting the state of a container."""

    entity_description: ArcaneContainerBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        if (container := self.container) is None:
            return None
        return self.entity_description.value_fn(container)


class ArcaneProjectBinarySensor(ArcaneProjectEntity, BinarySensorEntity):
    """A binary sensor reporting the state of a compose project."""

    entity_description: ArcaneProjectBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        if (project := self.project) is None:
            return None
        return self.entity_description.value_fn(project)
