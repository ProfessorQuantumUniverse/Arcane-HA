"""Shared platform setup helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

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
            if environments is not None:
                key = ("environment", environment_id)
                if key not in known:
                    known.add(key)
                    new_entities.extend(environments(environment_id))
            if containers is not None:
                for name in environment.containers:
                    key = ("container", environment_id, name)
                    if key not in known:
                        known.add(key)
                        new_entities.extend(containers(environment_id, name))
            if projects is not None:
                for project_id in environment.projects:
                    key = ("project", environment_id, project_id)
                    if key not in known:
                        known.add(key)
                        new_entities.extend(projects(environment_id, project_id))
        if new_entities:
            async_add_entities(new_entities)

    _async_add_new()
    coordinator.config_entry.async_on_unload(
        coordinator.async_add_listener(_async_add_new)
    )
