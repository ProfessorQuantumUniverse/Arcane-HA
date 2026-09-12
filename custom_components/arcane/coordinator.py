"""Data update coordinator for the Arcane integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ArcaneAuthenticationError, ArcaneClient, ArcaneError
from .const import (
    CONF_ENVIRONMENTS,
    CONF_INCLUDE_HIDDEN,
    CONF_INCLUDE_INTERNAL,
    CONF_MONITOR_CONTAINERS,
    CONF_MONITOR_PROJECTS,
    CONF_MONITOR_RESOURCES,
    DEFAULT_OPTIONS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .models import ArcaneContainer, ArcaneData, ArcaneEnvironment, ArcaneProject

if TYPE_CHECKING:
    from . import ArcaneConfigEntry

_LOGGER = logging.getLogger(__name__)


class ArcaneCoordinator(DataUpdateCoordinator[ArcaneData]):
    """Poll one Arcane instance and the environments it exposes."""

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
            update_interval=timedelta(
                seconds=config_entry.options.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                )
            ),
        )
        self.client = client

    def option(self, key: str) -> Any:
        """Return an option of the config entry, or its default."""
        return self.config_entry.options.get(key, DEFAULT_OPTIONS[key])

    async def _async_update_data(self) -> ArcaneData:
        """Fetch a snapshot of the Arcane instance."""
        try:
            version_info = await self.client.async_get_version()
            environments = await self.client.async_get_environments()
        except ArcaneAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ArcaneError as err:
            raise UpdateFailed(str(err)) from err

        selected: list[str] = self.option(CONF_ENVIRONMENTS)
        wanted = [
            environment
            for environment in environments
            if environment.get("id") is not None
            and environment.get("enabled", True)
            and (not selected or str(environment["id"]) in selected)
        ]

        results = await asyncio.gather(
            *(self._async_update_environment(item) for item in wanted)
        )

        return ArcaneData(
            version=version_info.get("currentVersion"),
            environments={item.id: item for item in results},
        )

    async def _async_update_environment(
        self, payload: dict[str, Any]
    ) -> ArcaneEnvironment:
        """Fetch the resources of a single environment.

        Every resource is fetched on its own: a remote environment can be
        unreachable, and an API key may be allowed to list containers but not
        volumes. Neither should fail the refresh of the whole instance, so a
        failure only leaves the affected part of the environment empty.
        """
        environment_id = str(payload["id"])
        environment = ArcaneEnvironment(
            id=environment_id,
            name=str(payload.get("name") or f"Environment {environment_id}"),
            status=str(payload.get("status") or "unknown"),
            enabled=bool(payload.get("enabled", True)),
        )

        calls: dict[str, Any] = {}
        if self.option(CONF_MONITOR_CONTAINERS):
            calls["containers"] = self.client.async_get_containers(
                environment_id,
                include_internal=self.option(CONF_INCLUDE_INTERNAL),
                include_hidden=self.option(CONF_INCLUDE_HIDDEN),
            )
        if self.option(CONF_MONITOR_PROJECTS):
            calls["projects"] = self.client.async_get_projects(environment_id)
        if self.option(CONF_MONITOR_RESOURCES):
            calls["images"] = self.client.async_get_image_counts(environment_id)
            calls["volumes"] = self.client.async_get_volume_counts(environment_id)
            calls["networks"] = self.client.async_get_network_counts(environment_id)
            calls["docker"] = self.client.async_get_docker_info(environment_id)

        if not calls:
            environment.reachable = True
            return environment

        results = dict(
            zip(
                calls,
                await asyncio.gather(*calls.values(), return_exceptions=True),
                strict=True,
            )
        )

        for result in results.values():
            if isinstance(result, ArcaneAuthenticationError):
                raise ConfigEntryAuthFailed(str(result))
            if isinstance(result, BaseException) and not isinstance(
                result, ArcaneError
            ):
                raise result

        # Arcane answered at least once, so the environment itself is up even
        # if some of the calls were refused.
        environment.reachable = any(
            not isinstance(result, ArcaneError) for result in results.values()
        )

        containers = self._value(results.get("containers"), environment_id, [])
        projects = self._value(results.get("projects"), environment_id, [])
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
        environment.image_counts = self._value(
            results.get("images"), environment_id, {}
        )
        environment.volume_counts = self._value(
            results.get("volumes"), environment_id, {}
        )
        environment.network_counts = self._value(
            results.get("networks"), environment_id, {}
        )
        environment.docker_info = self._value(results.get("docker"), environment_id, {})
        environment.docker_version = environment.docker_info.get("ServerVersion")
        return environment

    @staticmethod
    def _value(result: Any, environment_id: str, default: Any) -> Any:
        """Return a gathered result, or the default if the call failed."""
        if result is None:
            return default
        if isinstance(result, ArcaneError):
            _LOGGER.debug("Skipping part of environment %s: %s", environment_id, result)
            return default
        return result
