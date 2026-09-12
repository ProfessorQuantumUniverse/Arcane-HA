"""Data update coordinator for the Arcane integration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ArcaneAuthenticationError,
    ArcaneClient,
    ArcaneError,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .models import ArcaneContainer, ArcaneData, ArcaneEnvironment, ArcaneProject

if TYPE_CHECKING:
    from . import ArcaneConfigEntry

_LOGGER = logging.getLogger(__name__)


class ArcaneCoordinator(DataUpdateCoordinator[ArcaneData]):
    """Poll one Arcane instance and all environments it exposes."""

    config_entry: ArcaneConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: ArcaneClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> ArcaneData:
        """Fetch a full snapshot of the Arcane instance."""
        try:
            version_info = await self.client.async_get_version()
            environments = await self.client.async_get_environments()
        except ArcaneAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ArcaneError as err:
            raise UpdateFailed(str(err)) from err

        enabled = [
            environment
            for environment in environments
            if environment.get("enabled", True) and environment.get("id") is not None
        ]

        results = await asyncio.gather(
            *(self._async_update_environment(item) for item in enabled)
        )

        return ArcaneData(
            version=version_info.get("currentVersion"),
            environments={item.id: item for item in results},
        )

    async def _async_update_environment(self, payload: dict) -> ArcaneEnvironment:
        """Fetch the resources of a single environment.

        Every resource is fetched on its own: a remote environment can be
        unreachable, and an API key may be allowed to list containers but not
        volumes. Neither should fail the refresh of the whole instance, so
        failures only leave the affected part of the environment empty.
        """
        environment_id = str(payload["id"])
        environment = ArcaneEnvironment(
            id=environment_id,
            name=str(payload.get("name") or f"Environment {environment_id}"),
            status=str(payload.get("status") or "unknown"),
            enabled=bool(payload.get("enabled", True)),
        )

        results = await asyncio.gather(
            self.client.async_get_containers(environment_id),
            self.client.async_get_projects(environment_id),
            self.client.async_get_image_counts(environment_id),
            self.client.async_get_volume_counts(environment_id),
            self.client.async_get_network_counts(environment_id),
            self.client.async_get_docker_info(environment_id),
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, ArcaneAuthenticationError):
                raise ConfigEntryAuthFailed(str(result))
            if isinstance(result, BaseException) and not isinstance(
                result, ArcaneError
            ):
                raise result

        containers, projects, images, volumes, networks, docker_info = (
            self._value(result, environment_id, default)
            for result, default in zip(results, ([], [], {}, {}, {}, {}), strict=True)
        )

        # Arcane answered at least once, so the environment itself is up even
        # if some of the calls were refused.
        environment.reachable = any(
            not isinstance(result, ArcaneError) for result in results
        )
        environment.containers = {
            container.name: container
            for container in (ArcaneContainer.from_api(item) for item in containers)
            if container.name
        }
        environment.projects = {
            project.id: project
            for project in (ArcaneProject.from_api(item) for item in projects)
            if project.id
        }
        environment.image_counts = images
        environment.volume_counts = volumes
        environment.network_counts = networks
        environment.docker_info = docker_info
        environment.docker_version = docker_info.get("ServerVersion")
        return environment

    def _value(self, result: Any, environment_id: str, default: Any) -> Any:
        """Return a gathered result, or the default if the call failed."""
        if isinstance(result, ArcaneError):
            _LOGGER.debug("Skipping part of environment %s: %s", environment_id, result)
            return default
        return result
