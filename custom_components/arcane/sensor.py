"""Sensor platform for the Arcane integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import ArcaneConfigEntry
from .const import CONTAINER_STATES, PROJECT_STATES
from .entity import (
    ArcaneContainerEntity,
    ArcaneEnvironmentEntity,
    ArcaneProjectEntity,
)
from .helpers import async_setup_entities
from .models import ArcaneContainer, ArcaneEnvironment, ArcaneProject

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ArcaneEnvironmentSensorDescription(SensorEntityDescription):
    """Describes an Arcane environment sensor."""

    value_fn: Callable[[ArcaneEnvironment], StateType]


@dataclass(frozen=True, kw_only=True)
class ArcaneContainerSensorDescription(SensorEntityDescription):
    """Describes an Arcane container sensor."""

    value_fn: Callable[[ArcaneContainer], StateType | datetime]


@dataclass(frozen=True, kw_only=True)
class ArcaneProjectSensorDescription(SensorEntityDescription):
    """Describes an Arcane compose project sensor."""

    value_fn: Callable[[ArcaneProject], StateType]


def _enum_value(value: str, options: list[str]) -> str | None:
    """Return the value only when it is a known enum option."""
    normalized = value.strip().lower().replace(" ", "_")
    return normalized if normalized in options else None


ENVIRONMENT_SENSORS: tuple[ArcaneEnvironmentSensorDescription, ...] = (
    ArcaneEnvironmentSensorDescription(
        key="containers_running",
        translation_key="containers_running",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.containers_running,
    ),
    ArcaneEnvironmentSensorDescription(
        key="containers_stopped",
        translation_key="containers_stopped",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.containers_stopped,
    ),
    ArcaneEnvironmentSensorDescription(
        key="containers_total",
        translation_key="containers_total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.containers_total,
    ),
    ArcaneEnvironmentSensorDescription(
        key="containers_update_available",
        translation_key="containers_update_available",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.containers_with_update,
    ),
    ArcaneEnvironmentSensorDescription(
        key="projects_running",
        translation_key="projects_running",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.projects_running,
    ),
    ArcaneEnvironmentSensorDescription(
        key="projects_total",
        translation_key="projects_total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.projects_total,
    ),
    ArcaneEnvironmentSensorDescription(
        key="images_total",
        translation_key="images_total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.image_counts.get("totalImages"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="images_unused",
        translation_key="images_unused",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.image_counts.get("imagesUnused"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="images_size",
        translation_key="images_size",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.image_counts.get("totalImageSize"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="volumes_total",
        translation_key="volumes_total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.volume_counts.get("total"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="volumes_unused",
        translation_key="volumes_unused",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.volume_counts.get("unused"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="networks_total",
        translation_key="networks_total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.network_counts.get("total"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="docker_version",
        translation_key="docker_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda environment: environment.docker_version,
    ),
)

CONTAINER_SENSORS: tuple[ArcaneContainerSensorDescription, ...] = (
    ArcaneContainerSensorDescription(
        key="state",
        translation_key="container_state",
        device_class=SensorDeviceClass.ENUM,
        options=CONTAINER_STATES,
        value_fn=lambda container: _enum_value(container.state, CONTAINER_STATES),
    ),
    ArcaneContainerSensorDescription(
        key="status",
        translation_key="container_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda container: container.status,
    ),
    ArcaneContainerSensorDescription(
        key="image",
        translation_key="container_image",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda container: container.image,
    ),
    ArcaneContainerSensorDescription(
        key="created",
        translation_key="container_created",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda container: container.created,
    ),
)

PROJECT_SENSORS: tuple[ArcaneProjectSensorDescription, ...] = (
    ArcaneProjectSensorDescription(
        key="status",
        translation_key="project_status",
        device_class=SensorDeviceClass.ENUM,
        options=PROJECT_STATES,
        value_fn=lambda project: _enum_value(project.status, PROJECT_STATES),
    ),
    ArcaneProjectSensorDescription(
        key="services_running",
        translation_key="services_running",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda project: project.running_count,
    ),
    ArcaneProjectSensorDescription(
        key="services_total",
        translation_key="services_total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda project: project.service_count,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArcaneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Arcane sensors."""
    coordinator = entry.runtime_data

    async_setup_entities(
        coordinator,
        async_add_entities,
        environments=lambda environment_id: [
            ArcaneEnvironmentSensor(coordinator, environment_id, description)
            for description in ENVIRONMENT_SENSORS
        ],
        containers=lambda environment_id, name: [
            ArcaneContainerSensor(coordinator, environment_id, name, description)
            for description in CONTAINER_SENSORS
        ],
        projects=lambda environment_id, project_id: [
            ArcaneProjectSensor(coordinator, environment_id, project_id, description)
            for description in PROJECT_SENSORS
        ],
    )


class ArcaneEnvironmentSensor(ArcaneEnvironmentEntity, SensorEntity):
    """A sensor reporting an aggregate value of an environment."""

    entity_description: ArcaneEnvironmentSensorDescription

    @property
    def native_value(self) -> StateType:
        """Return the current value."""
        if (environment := self.environment) is None:
            return None
        return self.entity_description.value_fn(environment)


class ArcaneContainerSensor(ArcaneContainerEntity, SensorEntity):
    """A sensor reporting a property of a container."""

    entity_description: ArcaneContainerSensorDescription

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current value."""
        if (container := self.container) is None:
            return None
        return self.entity_description.value_fn(container)


class ArcaneProjectSensor(ArcaneProjectEntity, SensorEntity):
    """A sensor reporting a property of a compose project."""

    entity_description: ArcaneProjectSensorDescription

    @property
    def native_value(self) -> StateType:
        """Return the current value."""
        if (project := self.project) is None:
            return None
        return self.entity_description.value_fn(project)
