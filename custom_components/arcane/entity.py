"""Base entities for the Arcane integration."""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_URL
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENTITY_PREFIX,
    CONF_NEST_CONTAINERS,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import ArcaneCoordinator
from .models import ArcaneContainer, ArcaneEnvironment, ArcaneProject

# Home Assistant 2026.8 links a device to the one above it by that device's
# registry id. Linking by identifier, as earlier releases need, is deprecated
# there and stops working in 2027.8.
_LINK_BY_DEVICE_ID = hasattr(dr, "async_get_device_id_by_identifier")


def environment_identifier(entry_id: str, environment_id: str) -> str:
    """Return the device identifier of an environment."""
    return f"{entry_id}_{environment_id}"


def project_identifier(entry_id: str, environment_id: str, project_id: str) -> str:
    """Return the device identifier of a compose project."""
    return f"{environment_identifier(entry_id, environment_id)}_project_{project_id}"


def container_identifier(entry_id: str, environment_id: str, name: str) -> str:
    """Return the device identifier of a container."""
    return f"{environment_identifier(entry_id, environment_id)}_container_{name}"


def _configuration_url(coordinator: ArcaneCoordinator) -> str:
    """Return the URL of the Arcane instance behind the coordinator."""
    return str(coordinator.config_entry.data[CONF_URL]).rstrip("/")


def _device_name(coordinator: ArcaneCoordinator, kind: str, name: str) -> str:
    """Return the device name, prefixed with its kind when asked for.

    A container and a compose project regularly carry the same name. Home
    Assistant builds entity IDs from the device name, so without the prefix
    the second device of that name only gets ``_2`` suffixed entity IDs.
    """
    if not coordinator.option(CONF_ENTITY_PREFIX):
        return name
    return f"{kind} {name}"


def _below(coordinator: ArcaneCoordinator, identifier: str) -> dict[str, Any]:
    """Return the device info fields placing a device below another one."""
    if not _LINK_BY_DEVICE_ID:
        return {"via_device": (DOMAIN, identifier)}
    try:
        device_id = dr.async_get_device_id_by_identifier(
            coordinator.hass,
            (DOMAIN, identifier),
            config_entry_id=coordinator.config_entry.entry_id,
        )
    except ValueError:
        # Not expected, as async_register_parent_devices registers every device
        # that others hang below before them. Left unlinked rather than failing.
        return {}
    return {"via_device_id": device_id}


def _environment_device(
    coordinator: ArcaneCoordinator, environment_id: str
) -> dict[str, Any]:
    """Return the device info of an environment."""
    environment = coordinator.data.environments.get(environment_id)
    entry_id = coordinator.config_entry.entry_id
    return {
        "identifiers": {(DOMAIN, environment_identifier(entry_id, environment_id))},
        "manufacturer": MANUFACTURER,
        "model": "Environment",
        "name": environment.name if environment else environment_id,
        "sw_version": coordinator.data.version,
        "configuration_url": _configuration_url(coordinator),
    }


def _project_device(
    coordinator: ArcaneCoordinator, environment_id: str, project_id: str
) -> dict[str, Any]:
    """Return the device info of a compose project."""
    environment = coordinator.data.environments.get(environment_id)
    project = environment.projects.get(project_id) if environment else None
    entry_id = coordinator.config_entry.entry_id
    return {
        "identifiers": {
            (DOMAIN, project_identifier(entry_id, environment_id, project_id))
        },
        "manufacturer": MANUFACTURER,
        "model": "Compose project",
        "name": _device_name(
            coordinator, "Project", project.name if project else project_id
        ),
        "configuration_url": f"{_configuration_url(coordinator)}/projects/{project_id}",
        **_below(coordinator, environment_identifier(entry_id, environment_id)),
    }


@callback
def async_register_parent_devices(
    coordinator: ArcaneCoordinator,
    environment_id: str,
    project_ids: list[str],
) -> None:
    """Register an environment and its projects before anything below them.

    Home Assistant links a device to the one above it by registry id, so that
    device has to exist already. The platforms are set up side by side, and
    one of them may reach a container before another added its environment.
    """
    registry = dr.async_get(coordinator.hass)
    entry_id = coordinator.config_entry.entry_id
    registry.async_get_or_create(
        config_entry_id=entry_id,
        **_environment_device(coordinator, environment_id),
    )
    for project_id in project_ids:
        registry.async_get_or_create(
            config_entry_id=entry_id,
            **_project_device(coordinator, environment_id, project_id),
        )


class ArcaneEntity(CoordinatorEntity[ArcaneCoordinator]):
    """Common behaviour of every Arcane entity."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ArcaneCoordinator, description: EntityDescription
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description


class ArcaneEnvironmentEntity(ArcaneEntity):
    """An entity describing an Arcane environment as a whole."""

    def __init__(
        self,
        coordinator: ArcaneCoordinator,
        environment_id: str,
        description: EntityDescription,
    ) -> None:
        """Initialize the environment entity."""
        super().__init__(coordinator, description)
        self.environment_id = environment_id
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{environment_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            **_environment_device(coordinator, environment_id)
        )

    @property
    def environment(self) -> ArcaneEnvironment | None:
        """Return the environment this entity belongs to."""
        return self.coordinator.data.environments.get(self.environment_id)

    @property
    def available(self) -> bool:
        """Return whether the environment is still known to Arcane."""
        return super().available and self.environment is not None


class ArcaneContainerEntity(ArcaneEntity):
    """An entity describing a single container."""

    def __init__(
        self,
        coordinator: ArcaneCoordinator,
        environment_id: str,
        container_name: str,
        description: EntityDescription,
    ) -> None:
        """Initialize the container entity."""
        super().__init__(coordinator, description)
        self.environment_id = environment_id
        self.container_name = container_name
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = (
            f"{entry_id}_{environment_id}_container_{container_name}_{description.key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    container_identifier(entry_id, environment_id, container_name),
                )
            },
            manufacturer=MANUFACTURER,
            model="Container",
            name=_device_name(coordinator, "Container", container_name),
            configuration_url=f"{_configuration_url(coordinator)}/containers",
            **_below(coordinator, self._parent_identifier()),
        )

    def _parent_identifier(self) -> str:
        """Return the identifier of the device this container hangs below.

        Containers of a compose project are nested under the project device so
        the device page shows the stack it belongs to; everything else hangs
        directly below its environment.
        """
        entry_id = self.coordinator.config_entry.entry_id
        environment_device = environment_identifier(entry_id, self.environment_id)
        if not self.coordinator.option(CONF_NEST_CONTAINERS):
            return environment_device

        container = self.container
        environment = self.coordinator.data.environments.get(self.environment_id)
        if container is None or environment is None:
            return environment_device
        project_id = environment.project_id_for(container.project)
        if project_id is None:
            return environment_device
        return project_identifier(entry_id, self.environment_id, project_id)

    @property
    def container(self) -> ArcaneContainer | None:
        """Return the container this entity belongs to."""
        environment = self.coordinator.data.environments.get(self.environment_id)
        if environment is None:
            return None
        return environment.containers.get(self.container_name)

    @property
    def available(self) -> bool:
        """Return whether the container still exists."""
        return super().available and self.container is not None


class ArcaneProjectEntity(ArcaneEntity):
    """An entity describing a compose project."""

    def __init__(
        self,
        coordinator: ArcaneCoordinator,
        environment_id: str,
        project_id: str,
        description: EntityDescription,
    ) -> None:
        """Initialize the project entity."""
        super().__init__(coordinator, description)
        self.environment_id = environment_id
        self.project_id = project_id
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = (
            f"{entry_id}_{environment_id}_project_{project_id}_{description.key}"
        )
        self._attr_device_info = DeviceInfo(
            **_project_device(coordinator, environment_id, project_id)
        )

    @property
    def project(self) -> ArcaneProject | None:
        """Return the project this entity belongs to."""
        environment = self.coordinator.data.environments.get(self.environment_id)
        if environment is None:
            return None
        return environment.projects.get(self.project_id)

    @property
    def available(self) -> bool:
        """Return whether the project still exists."""
        return super().available and self.project is not None
