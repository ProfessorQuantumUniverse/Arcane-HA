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
from .const import CONF_HEALTH_SENSORS
from .coordinator import ArcaneCoordinator
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

HEALTH_BINARY_SENSOR = ArcaneContainerBinarySensorDescription(
    key="healthy",
    translation_key="container_healthy",
    value_fn=lambda container: container.is_healthy is True,
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


def _container_descriptions(
    coordinator: ArcaneCoordinator, environment_id: str, name: str
) -> tuple[ArcaneContainerBinarySensorDescription, ...]:
    """Return the binary sensors this container should get.

    The health sensor is only added for containers that actually define a
    health check, so the others do not gain an entity that is always off.
    """
    if not coordinator.option(CONF_HEALTH_SENSORS):
        return CONTAINER_BINARY_SENSORS
    environment = coordinator.data.environments.get(environment_id)
    container = environment.containers.get(name) if environment else None
    if container is None or container.health is None:
        return CONTAINER_BINARY_SENSORS
    return (*CONTAINER_BINARY_SENSORS, HEALTH_BINARY_SENSOR)


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
            for description in _container_descriptions(
                coordinator, environment_id, name
            )
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
