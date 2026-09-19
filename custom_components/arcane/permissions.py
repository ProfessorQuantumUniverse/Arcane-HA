"""The Arcane permissions the enabled options need.

Arcane answers a call the API key is not allowed to make with 403. The
integration keeps going when that happens, so the failure shows up as an empty
sensor or a button press that ends in an error rather than as something a user
can act on. The options decide exactly which calls are made, so the
permissions they need can be listed before anything fails, and a call that is
refused anyway can name the permission it was missing.

The names are the ones Arcane uses under Settings > Roles, so they can be
copied straight into the role behind the API key.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from .const import (
    CONF_ALLOW_CONTROL,
    CONF_HOST_STATS,
    CONF_MONITOR_CONTAINERS,
    CONF_MONITOR_PROJECTS,
    CONF_MONITOR_RESOURCES,
    CONF_PRUNE_BUTTON,
    CONF_REDEPLOY_BUTTONS,
    CONF_UPDATE_ENTITIES,
    DEFAULT_OPTIONS,
    PRUNE_OFF,
)

# Org level permissions.
PERM_ENVIRONMENTS_LIST: Final = "environments:list"
PERM_ENVIRONMENTS_READ: Final = "environments:read"

# Permissions resolved against a single environment.
PERM_CONTAINERS_LIST: Final = "containers:list"
PERM_CONTAINERS_START: Final = "containers:start"
PERM_CONTAINERS_STOP: Final = "containers:stop"
PERM_CONTAINERS_RESTART: Final = "containers:restart"
PERM_CONTAINERS_REDEPLOY: Final = "containers:redeploy"
PERM_PROJECTS_LIST: Final = "projects:list"
PERM_PROJECTS_DEPLOY: Final = "projects:deploy"
PERM_PROJECTS_DOWN: Final = "projects:down"
PERM_PROJECTS_RESTART: Final = "projects:restart"
PERM_IMAGES_LIST: Final = "images:list"
PERM_VOLUMES_LIST: Final = "volumes:list"
PERM_NETWORKS_LIST: Final = "networks:list"
PERM_SYSTEM_READ: Final = "system:read"
PERM_SYSTEM_PRUNE: Final = "system:prune"
PERM_SYSTEM_UPGRADE: Final = "system:upgrade"

# The permission each container and project action is gated on. Both mirror
# ``CONTAINER_ACTIONS`` and ``PROJECT_ACTIONS`` of the API client: deploying a
# project and redeploying it run through the same permission.
CONTAINER_ACTION_PERMISSIONS: Final[dict[str, str]] = {
    "start": PERM_CONTAINERS_START,
    "stop": PERM_CONTAINERS_STOP,
    "restart": PERM_CONTAINERS_RESTART,
    "redeploy": PERM_CONTAINERS_REDEPLOY,
}

PROJECT_ACTION_PERMISSIONS: Final[dict[str, str]] = {
    "up": PERM_PROJECTS_DEPLOY,
    "down": PERM_PROJECTS_DOWN,
    "restart": PERM_PROJECTS_RESTART,
    "redeploy": PERM_PROJECTS_DEPLOY,
}

# The permission behind each request the coordinator makes per environment,
# keyed by the name the coordinator gathers the result under.
POLL_PERMISSIONS: Final[dict[str, str]] = {
    "containers": PERM_CONTAINERS_LIST,
    "projects": PERM_PROJECTS_LIST,
    "images": PERM_IMAGES_LIST,
    "volumes": PERM_VOLUMES_LIST,
    "networks": PERM_NETWORKS_LIST,
    "docker": PERM_SYSTEM_READ,
    "host": PERM_SYSTEM_READ,
    "version": PERM_ENVIRONMENTS_READ,
}


@dataclass(slots=True)
class RequiredPermissions:
    """The permissions the enabled options need, split by what they are for."""

    monitoring: list[str] = field(default_factory=list)
    control: list[str] = field(default_factory=list)

    @property
    def all(self) -> list[str]:
        """Return every required permission, monitoring ones first."""
        return [*self.monitoring, *self.control]


def _option(options: Mapping[str, Any], key: str) -> Any:
    """Return one option of a config entry, or its default."""
    return options.get(key, DEFAULT_OPTIONS[key])


def required_permissions(options: Mapping[str, Any]) -> RequiredPermissions:
    """Return the permissions the API key needs for these options.

    Only what the options actually ask for is listed: switching a part off
    stops its requests, so it also stops needing its permission.
    """
    return RequiredPermissions(
        monitoring=_unique(_monitoring_permissions(options)),
        control=_unique(_control_permissions(options)),
    )


def _monitoring_permissions(options: Mapping[str, Any]) -> list[str]:
    """Return the permissions the polling of one refresh needs."""
    # The environment list is the one call every setup makes. Arcane lets any
    # key call it and answers with the environments the key holds a permission
    # on, so the list permission is what makes every environment visible.
    permissions = [PERM_ENVIRONMENTS_LIST]

    if _option(options, CONF_MONITOR_CONTAINERS):
        permissions.append(PERM_CONTAINERS_LIST)
    if _option(options, CONF_MONITOR_PROJECTS):
        permissions.append(PERM_PROJECTS_LIST)
    if _option(options, CONF_MONITOR_RESOURCES):
        permissions += [PERM_IMAGES_LIST, PERM_VOLUMES_LIST, PERM_NETWORKS_LIST]
    if _option(options, CONF_MONITOR_RESOURCES) or _option(options, CONF_HOST_STATS):
        # The Docker version and the host statistics both come out of the
        # system endpoints.
        permissions.append(PERM_SYSTEM_READ)
    if _option(options, CONF_UPDATE_ENTITIES):
        # Only environments other than the local one are asked for their
        # version, and which ones exist is not known here, so the permission is
        # listed whenever the update entities are on.
        permissions.append(PERM_ENVIRONMENTS_READ)
    return permissions


def _control_permissions(options: Mapping[str, Any]) -> list[str]:
    """Return the permissions the switches, buttons and installs need."""
    if not _option(options, CONF_ALLOW_CONTROL):
        return []

    containers = _option(options, CONF_MONITOR_CONTAINERS)
    projects = _option(options, CONF_MONITOR_PROJECTS)
    # Installing a container update redeploys the container, which is what the
    # redeploy button does as well.
    redeploy = _option(options, CONF_REDEPLOY_BUTTONS)
    updates = _option(options, CONF_UPDATE_ENTITIES)

    permissions: list[str] = []
    if containers:
        permissions += [
            PERM_CONTAINERS_START,
            PERM_CONTAINERS_STOP,
            PERM_CONTAINERS_RESTART,
        ]
        if redeploy or updates:
            permissions.append(PERM_CONTAINERS_REDEPLOY)
    if projects:
        permissions += [
            PERM_PROJECTS_DEPLOY,
            PERM_PROJECTS_DOWN,
            PERM_PROJECTS_RESTART,
        ]
    if updates:
        permissions.append(PERM_SYSTEM_UPGRADE)
    if _option(options, CONF_PRUNE_BUTTON) != PRUNE_OFF:
        permissions.append(PERM_SYSTEM_PRUNE)
    return permissions


def _unique(permissions: Iterable[str]) -> list[str]:
    """Return the permissions without repeats, in the order they were added."""
    return list(dict.fromkeys(permissions))


def format_permissions(permissions: Iterable[str]) -> str:
    """Return permissions as one line of markdown, ready for a form."""
    listed = ", ".join(f"`{permission}`" for permission in permissions)
    return listed or "—"
