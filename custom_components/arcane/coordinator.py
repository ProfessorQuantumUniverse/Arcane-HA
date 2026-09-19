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
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ArcaneAuthenticationError,
    ArcaneClient,
    ArcaneError,
    ArcanePermissionError,
)
from .const import (
    CONF_ENVIRONMENTS,
    CONF_EVENTS,
    CONF_HOST_STATS,
    CONF_INCLUDE_HIDDEN,
    CONF_INCLUDE_INTERNAL,
    CONF_MONITOR_CONTAINERS,
    CONF_MONITOR_PROJECTS,
    CONF_MONITOR_RESOURCES,
    CONF_UPDATE_ENTITIES,
    DEFAULT_OPTIONS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_CONTAINER_HEALTH,
    EVENT_CONTAINER_STATE,
    EVENT_PROJECT_STATE,
    EXIT_CODE_SIGKILL,
    LOCAL_ENVIRONMENT_ID,
    STATE_RUNNING,
)
from .models import (
    ArcaneContainer,
    ArcaneData,
    ArcaneEnvironment,
    ArcaneHostStats,
    ArcaneProject,
    ArcaneVersion,
)
from .permissions import (
    POLL_PERMISSIONS,
    RequiredPermissions,
    format_permissions,
    required_permissions,
)

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
        # Permissions Arcane refused, so the missing ones can be named instead
        # of only leaving a sensor empty. The polled ones are rebuilt on every
        # refresh; a refused button press is remembered until the entry is
        # reloaded, because nothing polls it again.
        self._denied_polling: set[str] = set()
        self._denied_actions: set[str] = set()

    def option(self, key: str) -> Any:
        """Return an option of the config entry, or its default."""
        return self.config_entry.options.get(key, DEFAULT_OPTIONS[key])

    @property
    def required_permissions(self) -> RequiredPermissions:
        """Return the permissions the options in use need."""
        return required_permissions(self.config_entry.options)

    @property
    def missing_permissions(self) -> list[str]:
        """Return the permissions Arcane has refused, in the order listed."""
        denied = self._denied_polling | self._denied_actions
        listed = [
            permission
            for permission in self.required_permissions.all
            if permission in denied
        ]
        # A refused call whose permission the options do not ask for should
        # still be reported rather than swallowed.
        return listed + sorted(denied.difference(listed))

    def async_note_denied(self, permission: str) -> None:
        """Remember that Arcane refused an action for lack of a permission."""
        if permission not in self._denied_actions:
            self._denied_actions.add(permission)
            self._async_update_permission_issue()

    @property
    def _permission_issue_id(self) -> str:
        """Return the ID of the repair that lists the missing permissions."""
        return f"missing_permissions_{self.config_entry.entry_id}"

    def async_clear_permission_issue(self) -> None:
        """Drop the repair, for an entry that is being unloaded."""
        ir.async_delete_issue(self.hass, DOMAIN, self._permission_issue_id)

    def _async_update_permission_issue(self) -> None:
        """Raise or drop the repair that lists the missing permissions."""
        issue_id = self._permission_issue_id
        if not (missing := self.missing_permissions):
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="missing_permissions",
            translation_placeholders={
                "name": self.config_entry.title,
                "permissions": format_permissions(missing),
            },
        )

    async def _async_update_data(self) -> ArcaneData:
        """Fetch a snapshot of the Arcane instance."""
        self._denied_polling = set()
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
            *(self._async_update_environment(item, version_info) for item in wanted)
        )

        data = ArcaneData(
            version=version_info.get("currentVersion"),
            environments={item.id: item for item in results},
        )
        if self.option(CONF_EVENTS):
            self._fire_events(data)
        self._async_update_permission_issue()
        return data

    def _environment_calls(self, environment_id: str) -> dict[str, Any]:
        """Return the requests to make for one environment, by result name.

        Only what the options ask for is requested, so switching a part off
        stops its traffic instead of only hiding its entities.
        """
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
        if self.option(CONF_HOST_STATS):
            calls["host"] = self.client.async_get_host_stats(environment_id)
        if self.option(CONF_UPDATE_ENTITIES) and environment_id != LOCAL_ENVIRONMENT_ID:
            # The local environment is the instance that was already asked for
            # its version, so only remote ones cost a request here.
            calls["version"] = self.client.async_get_environment_version(environment_id)
        return calls

    def _note_denied_polling(self, results: dict[str, Any]) -> None:
        """Remember the permissions this refresh was refused."""
        self._denied_polling.update(
            POLL_PERMISSIONS[name]
            for name, result in results.items()
            if isinstance(result, ArcanePermissionError) and name in POLL_PERMISSIONS
        )

    @staticmethod
    def _reraise_fatal(results: dict[str, Any]) -> None:
        """Let an expired key and anything unexpected fail the whole refresh."""
        for result in results.values():
            if isinstance(result, ArcaneAuthenticationError):
                raise ConfigEntryAuthFailed(str(result))
            if isinstance(result, BaseException) and not isinstance(
                result, ArcaneError
            ):
                raise result

    async def _async_update_environment(
        self, payload: dict[str, Any], version_info: dict[str, Any]
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

        results: dict[str, Any] = {}
        if calls := self._environment_calls(environment_id):
            results = dict(
                zip(
                    calls,
                    await asyncio.gather(*calls.values(), return_exceptions=True),
                    strict=True,
                )
            )
            self._reraise_fatal(results)
            self._note_denied_polling(results)
            # Arcane answered at least once, so the environment itself is up
            # even if some of the calls were refused.
            environment.reachable = any(
                not isinstance(result, ArcaneError) for result in results.values()
            )
        else:
            environment.reachable = True

        self._apply_results(environment, results, version_info)
        return environment

    def _apply_results(
        self,
        environment: ArcaneEnvironment,
        results: dict[str, Any],
        version_info: dict[str, Any],
    ) -> None:
        """Fill an environment with whatever the requests brought back."""
        environment_id = environment.id

        def value(name: str, default: Any) -> Any:
            return self._value(results.get(name), environment_id, default)

        environment.containers = {
            container.name: container
            for container in (
                ArcaneContainer.from_api(item) for item in value("containers", [])
            )
            if container.name
        }
        environment.projects = {
            project.id: project
            for project in (
                ArcaneProject.from_api(item) for item in value("projects", [])
            )
            if project.id
        }
        environment.image_counts = value("images", {})
        environment.volume_counts = value("volumes", {})
        environment.network_counts = value("networks", {})
        environment.docker_info = value("docker", {})
        environment.docker_version = environment.docker_info.get("ServerVersion")
        if host := value("host", {}):
            environment.host_stats = ArcaneHostStats.from_api(host)
        if self.option(CONF_UPDATE_ENTITIES):
            version = (
                version_info
                if environment_id == LOCAL_ENVIRONMENT_ID
                else value("version", {})
            )
            if version:
                environment.arcane_version = ArcaneVersion.from_api(version)

    def _fire_events(self, data: ArcaneData) -> None:
        """Announce what changed since the previous refresh on the event bus.

        Nothing is fired for the first refresh or for a resource that has just
        appeared: neither is a change a user could act on.
        """
        if (previous := self.data) is None:
            return

        for environment_id, environment in data.environments.items():
            if (was := previous.environments.get(environment_id)) is None:
                continue
            shared = {
                "environment_id": environment_id,
                "environment": environment.name,
            }

            for name, container in environment.containers.items():
                if (before := was.containers.get(name)) is None:
                    continue
                if before.state != container.state:
                    crashed = (
                        before.state == STATE_RUNNING
                        and not container.is_running
                        and bool(container.exit_code)
                    )
                    self.hass.bus.async_fire(
                        EVENT_CONTAINER_STATE,
                        {
                            **shared,
                            "container": name,
                            "state": container.state,
                            "previous_state": before.state,
                            "exit_code": container.exit_code,
                            "crashed": crashed,
                            "oom_killed": crashed
                            and container.exit_code == EXIT_CODE_SIGKILL,
                        },
                    )
                if before.health != container.health and container.health is not None:
                    self.hass.bus.async_fire(
                        EVENT_CONTAINER_HEALTH,
                        {
                            **shared,
                            "container": name,
                            "health": container.health,
                            "previous_health": before.health,
                        },
                    )

            for project_id, project in environment.projects.items():
                before_project = was.projects.get(project_id)
                if before_project is None or before_project.status == project.status:
                    continue
                self.hass.bus.async_fire(
                    EVENT_PROJECT_STATE,
                    {
                        **shared,
                        "project": project.name,
                        "project_id": project_id,
                        "status": project.status,
                        "previous_status": before_project.status,
                    },
                )

    @staticmethod
    def _value(result: Any, environment_id: str, default: Any) -> Any:
        """Return a gathered result, or the default if the call failed."""
        if result is None:
            return default
        if isinstance(result, ArcaneError):
            _LOGGER.debug("Skipping part of environment %s: %s", environment_id, result)
            return default
        return result
