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
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import ArcaneConfigEntry
from .const import (
    CONF_HEALTH_SENSORS,
    CONF_HOST_STATS,
    CONF_MONITOR_CONTAINERS,
    CONF_MONITOR_PROJECTS,
    CONF_MONITOR_RESOURCES,
    CONTAINER_STATES,
    PROJECT_STATES,
)
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
    #: Option that has to be on for this sensor to have anything to report.
    requires: str


@dataclass(frozen=True, kw_only=True)
class ArcaneContainerSensorDescription(SensorEntityDescription):
    """Describes an Arcane container sensor."""

    value_fn: Callable[[ArcaneContainer], StateType | datetime]


@dataclass(frozen=True, kw_only=True)
class ArcaneProjectSensorDescription(SensorEntityDescription):
    """Describes an Arcane compose project sensor."""

    value_fn: Callable[[ArcaneProject], StateType]


def _host(environment: ArcaneEnvironment, attribute: str) -> StateType:
    """Return a host statistics value, or None when no sample is available."""
    if environment.host_stats is None:
        return None
    return getattr(environment.host_stats, attribute)


def _enum_value(value: str, options: list[str]) -> str | None:
    """Return the value only when it is a known enum option."""
    normalized = value.strip().lower().replace(" ", "_")
    return normalized if normalized in options else None


ENVIRONMENT_SENSORS: tuple[ArcaneEnvironmentSensorDescription, ...] = (
    ArcaneEnvironmentSensorDescription(
        key="containers_running",
        requires=CONF_MONITOR_CONTAINERS,
        translation_key="containers_running",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.containers_running,
    ),
    ArcaneEnvironmentSensorDescription(
        key="containers_stopped",
        requires=CONF_MONITOR_CONTAINERS,
        translation_key="containers_stopped",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.containers_stopped,
    ),
    ArcaneEnvironmentSensorDescription(
        key="containers_total",
        requires=CONF_MONITOR_CONTAINERS,
        translation_key="containers_total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.containers_total,
    ),
    ArcaneEnvironmentSensorDescription(
        key="containers_update_available",
        requires=CONF_MONITOR_CONTAINERS,
        translation_key="containers_update_available",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.containers_with_update,
    ),
    ArcaneEnvironmentSensorDescription(
        key="projects_running",
        requires=CONF_MONITOR_PROJECTS,
        translation_key="projects_running",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.projects_running,
    ),
    ArcaneEnvironmentSensorDescription(
        key="projects_total",
        requires=CONF_MONITOR_PROJECTS,
        translation_key="projects_total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.projects_total,
    ),
    ArcaneEnvironmentSensorDescription(
        key="images_total",
        requires=CONF_MONITOR_RESOURCES,
        translation_key="images_total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.image_counts.get("totalImages"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="images_unused",
        requires=CONF_MONITOR_RESOURCES,
        translation_key="images_unused",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.image_counts.get("imagesUnused"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="images_size",
        requires=CONF_MONITOR_RESOURCES,
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
        requires=CONF_MONITOR_RESOURCES,
        translation_key="volumes_total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.volume_counts.get("total"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="volumes_unused",
        requires=CONF_MONITOR_RESOURCES,
        translation_key="volumes_unused",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.volume_counts.get("unused"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="networks_total",
        requires=CONF_MONITOR_RESOURCES,
        translation_key="networks_total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.network_counts.get("total"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="docker_version",
        requires=CONF_MONITOR_RESOURCES,
        translation_key="docker_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda environment: environment.docker_version,
    ),
    ArcaneEnvironmentSensorDescription(
        key="containers_unhealthy",
        requires=CONF_HEALTH_SENSORS,
        translation_key="containers_unhealthy",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: environment.containers_unhealthy,
    ),
    ArcaneEnvironmentSensorDescription(
        key="host_cpu",
        requires=CONF_HOST_STATS,
        translation_key="host_cpu",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: _host(environment, "cpu_percent"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="host_memory_percent",
        requires=CONF_HOST_STATS,
        translation_key="host_memory_percent",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: _host(environment, "memory_percent"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="host_memory_used",
        requires=CONF_HOST_STATS,
        translation_key="host_memory_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: _host(environment, "memory_used"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="host_memory_total",
        requires=CONF_HOST_STATS,
        translation_key="host_memory_total",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda environment: _host(environment, "memory_total"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="host_disk_percent",
        requires=CONF_HOST_STATS,
        translation_key="host_disk_percent",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: _host(environment, "disk_percent"),
    ),
    ArcaneEnvironmentSensorDescription(
        key="host_disk_used",
        requires=CONF_HOST_STATS,
        translation_key="host_disk_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda environment: _host(environment, "disk_used"),
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

ARCANE_VERSION_SENSOR = SensorEntityDescription(
    key="arcane_version",
    translation_key="arcane_version",
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
            *(
                ArcaneEnvironmentSensor(coordinator, environment_id, description)
                for description in ENVIRONMENT_SENSORS
                if coordinator.option(description.requires)
            ),
            ArcaneVersionSensor(coordinator, environment_id, ARCANE_VERSION_SENSOR),
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


class ArcaneVersionSensor(ArcaneEnvironmentEntity, SensorEntity):
    """Report the version of the Arcane instance."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> StateType:
        """Return the version Arcane reports."""
        return self.coordinator.data.version


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
