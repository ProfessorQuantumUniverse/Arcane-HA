"""Data models describing an Arcane instance snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .const import (
    ENVIRONMENT_STATUS_ONLINE,
    PROJECT_STATE_PARTIALLY_RUNNING,
    PROJECT_STATE_RUNNING,
    STATE_RUNNING,
)


def _container_name(payload: dict[str, Any]) -> str:
    """Return the primary container name without the Docker slash prefix."""
    names = payload.get("names") or []
    for name in names:
        if isinstance(name, str) and name.strip("/"):
            return name.strip("/")
    return str(payload.get("id", ""))[:12]


def _created_at(value: Any) -> datetime | None:
    """Return the creation timestamp of a container as an aware datetime."""
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, tz=UTC)
    return None


@dataclass(slots=True)
class ArcaneContainer:
    """A single Docker container as reported by Arcane."""

    id: str
    name: str
    state: str
    status: str
    image: str
    created: datetime | None
    update_available: bool
    project: str | None
    service: str | None

    @property
    def is_running(self) -> bool:
        """Return whether the container is currently running."""
        return self.state == STATE_RUNNING

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ArcaneContainer:
        """Build a container from an Arcane container summary."""
        labels = payload.get("labels") or {}
        update_info = payload.get("updateInfo") or {}
        return cls(
            id=str(payload.get("id", "")),
            name=_container_name(payload),
            state=str(payload.get("state") or "unknown"),
            status=str(payload.get("status") or ""),
            image=str(payload.get("image") or ""),
            created=_created_at(payload.get("created")),
            update_available=bool(update_info.get("hasUpdate")),
            project=labels.get("com.docker.compose.project"),
            service=labels.get("com.docker.compose.service"),
        )


@dataclass(slots=True)
class ArcaneProject:
    """A compose project (stack) as reported by Arcane."""

    id: str
    name: str
    status: str
    running_count: int
    service_count: int
    update_available: bool

    @property
    def is_running(self) -> bool:
        """Return whether at least one service of the project runs."""
        return self.status in (PROJECT_STATE_RUNNING, PROJECT_STATE_PARTIALLY_RUNNING)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ArcaneProject:
        """Build a project from an Arcane project details payload."""
        update_info = payload.get("updateInfo") or {}
        return cls(
            id=str(payload.get("id", "")),
            name=str(payload.get("name") or payload.get("id") or ""),
            status=str(payload.get("status") or "unknown"),
            running_count=int(payload.get("runningCount") or 0),
            service_count=int(payload.get("serviceCount") or 0),
            update_available=bool(update_info.get("hasUpdate")),
        )


@dataclass(slots=True)
class ArcaneEnvironment:
    """Everything the integration knows about one Arcane environment."""

    id: str
    name: str
    status: str
    enabled: bool
    reachable: bool = False
    docker_version: str | None = None
    docker_info: dict[str, Any] = field(default_factory=dict)
    containers: dict[str, ArcaneContainer] = field(default_factory=dict)
    projects: dict[str, ArcaneProject] = field(default_factory=dict)
    image_counts: dict[str, Any] = field(default_factory=dict)
    volume_counts: dict[str, Any] = field(default_factory=dict)
    network_counts: dict[str, Any] = field(default_factory=dict)

    @property
    def is_online(self) -> bool:
        """Return whether Arcane considers the environment online."""
        return self.reachable and self.status == ENVIRONMENT_STATUS_ONLINE

    @property
    def containers_running(self) -> int:
        """Return the number of running containers."""
        return sum(1 for item in self.containers.values() if item.is_running)

    @property
    def containers_stopped(self) -> int:
        """Return the number of containers that are not running."""
        return len(self.containers) - self.containers_running

    @property
    def containers_total(self) -> int:
        """Return the total number of containers."""
        return len(self.containers)

    @property
    def containers_with_update(self) -> int:
        """Return the number of containers running an outdated image."""
        return sum(1 for item in self.containers.values() if item.update_available)

    @property
    def projects_running(self) -> int:
        """Return the number of projects with at least one running service."""
        return sum(1 for item in self.projects.values() if item.is_running)

    @property
    def projects_total(self) -> int:
        """Return the total number of projects."""
        return len(self.projects)


@dataclass(slots=True)
class ArcaneData:
    """The full snapshot handed to the entities on every refresh."""

    version: str | None
    environments: dict[str, ArcaneEnvironment] = field(default_factory=dict)
