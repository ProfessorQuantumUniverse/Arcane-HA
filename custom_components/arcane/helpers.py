"""Shared platform setup helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ArcaneError, ArcanePermissionError
from .const import DOMAIN
from .entity import async_register_parent_devices

if TYPE_CHECKING:
    from .coordinator import ArcaneCoordinator

type EnvironmentFactory = Callable[[str], list[Entity]]
type ContainerFactory = Callable[[str, str], list[Entity]]
type ProjectFactory = Callable[[str, str], list[Entity]]


def async_setup_entities(
    coordinator: ArcaneCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    *,
    environments: EnvironmentFactory | None = None,
    containers: ContainerFactory | None = None,
    projects: ProjectFactory | None = None,
) -> None:
    """Add entities now and whenever Arcane reports new resources.

    Containers and projects come and go while Home Assistant runs, so the
    platforms keep listening instead of only reading the first snapshot.
    """
    known: set[tuple[str, ...]] = set()

    def _async_add_new() -> None:
        new_entities: list[Entity] = []
        for environment_id, environment in coordinator.data.environments.items():
            # The devices containers and projects hang below have to exist
            # before those, also on a platform that has no entity for them.
            new_parents = [
                project_id
                for project_id in environment.projects
                if ("project", environment_id, project_id) not in known
            ]
            if new_parents or ("environment", environment_id) not in known:
                async_register_parent_devices(coordinator, environment_id, new_parents)

            key = ("environment", environment_id)
            if key not in known:
                known.add(key)
                if environments is not None:
                    new_entities.extend(environments(environment_id))
            for project_id in new_parents:
                known.add(("project", environment_id, project_id))
                if projects is not None:
                    new_entities.extend(projects(environment_id, project_id))
            if containers is not None:
                for name in environment.containers:
                    key = ("container", environment_id, name)
                    if key not in known:
                        known.add(key)
                        new_entities.extend(containers(environment_id, name))
        if new_entities:
            async_add_entities(new_entities)

    _async_add_new()
    coordinator.config_entry.async_on_unload(
        coordinator.async_add_listener(_async_add_new)
    )


def action_error(
    coordinator: ArcaneCoordinator,
    err: ArcaneError,
    *,
    permission: str,
    action_key: str,
    placeholders: dict[str, str],
) -> HomeAssistantError:
    """Return the error to raise for an action that did not go through.

    An action Arcane refused is reported with the permission the API key is
    missing, rather than with a bare 403, and is remembered so the repair issue
    lists it next to the permissions the polling is missing. Every action has a
    ``<action_key>_failed`` and a ``<action_key>_forbidden`` message.
    """
    if isinstance(err, ArcanePermissionError):
        coordinator.async_note_denied(permission)
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=f"{action_key}_forbidden",
            translation_placeholders={**placeholders, "permission": permission},
        )
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=f"{action_key}_failed",
        translation_placeholders={**placeholders, "error": str(err)},
    )
