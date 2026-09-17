"""Data models describing an Arcane instance snapshot."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .const import (
    ENVIRONMENT_STATUS_ONLINE,
    HEALTH_HEALTHY,
    HEALTH_STARTING,
    HEALTH_UNHEALTHY,
    PROJECT_STATE_PARTIALLY_RUNNING,
    PROJECT_STATE_RUNNING,
    STATE_RUNNING,
)

# Docker puts the health of a container and the exit code of a stopped one into
# the status line, and the container list carries nothing else about either.
_HEALTH_PATTERN = re.compile(r"\((healthy|unhealthy|health: starting)\)")
_EXIT_CODE_PATTERN = re.compile(r"^Exited \((\d+)\)")


def _container_name(payload: dict[str, Any]) -> str:
    """Return the primary container name without the Docker slash prefix."""
    names = payload.get("names") or []
    for name in names:
        if isinstance(name, str) and name.strip("/"):
            return name.strip("/")
    return str(payload.get("id", ""))[:12]


def _short_digest(value: Any) -> str | None:
    """Return a readable short form of an image digest."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().removeprefix("sha256:")[:12] or None


def _health(status: str) -> str | None:
    """Return the health Docker reports in a status line, if it reports one."""
    if (match := _HEALTH_PATTERN.search(status)) is None:
        return None
    found = match.group(1)
    if found == "health: starting":
        return HEALTH_STARTING
    return HEALTH_UNHEALTHY if found == HEALTH_UNHEALTHY else HEALTH_HEALTHY


def _exit_code(status: str) -> int | None:
    """Return the exit code of a stopped container, if the status carries one."""
    if (match := _EXIT_CODE_PATTERN.match(status.strip())) is None:
        return None
    return int(match.group(1))


def _version(value: Any) -> str | None:
    """Return a non-empty version string, or None."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _image_tag(image: str) -> str | None:
    """Return the tag of an image reference, ignoring a port in the registry."""
    _, separator, tag = image.rpartition(":")
    if not separator or "/" in tag:
        return None
    return tag or None


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
    installed_version: str | None
    latest_version: str | None
    health: str | None
    exit_code: int | None
    project: str | None
    service: str | None

    @property
    def is_running(self) -> bool:
        """Return whether the container is currently running."""
        return self.state == STATE_RUNNING

    @property
    def is_healthy(self) -> bool | None:
        """Return the health of the container, or None if it reports none."""
        if self.health is None:
            return None
        return self.health == HEALTH_HEALTHY

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ArcaneContainer:
        """Build a container from an Arcane container summary."""
        labels = payload.get("labels") or {}
        update_info = payload.get("updateInfo") or {}
        image = str(payload.get("image") or "")
        status = str(payload.get("status") or "")
        installed = _version(update_info.get("currentVersion")) or _image_tag(image)
        latest = _version(update_info.get("latestVersion"))
        return cls(
            id=str(payload.get("id", "")),
            name=_container_name(payload),
            state=str(payload.get("state") or "unknown"),
            status=status,
            image=image,
            created=_created_at(payload.get("created")),
            update_available=bool(update_info.get("hasUpdate")),
            installed_version=installed,
            latest_version=latest or installed,
            health=_health(status),
            exit_code=_exit_code(status),
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
class ArcaneVersion:
    """Version and update state of an Arcane instance."""

    installed: str | None
    latest: str | None
    update_available: bool
    release_url: str | None
    release_notes: str | None
    released_at: str | None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ArcaneVersion:
        """Build the version state from an Arcane version payload."""
        installed = _version(payload.get("currentVersion"))
        latest = _version(payload.get("newestVersion"))
        update_available = bool(payload.get("updateAvailable"))
        if latest is None and update_available:
            # An instance that tracks a digest rather than a release reports an
            # update without naming a version. The digest is what changed, so
            # it stands in as the newer version; Home Assistant needs the two
            # to differ for the entity to read as "update available".
            latest = _short_digest(payload.get("newestDigest"))
        return cls(
            installed=installed,
            # Home Assistant compares the two, so an unknown newest version has
            # to read as "same as installed" rather than as an update.
            latest=latest or installed,
            update_available=update_available,
            release_url=_version(payload.get("releaseUrl")),
            release_notes=_version(payload.get("releaseNotes")),
            released_at=_version(payload.get("releasedAt")),
        )


@dataclass(slots=True)
class ArcaneHostStats:
    """Host resource usage of the machine an environment runs on."""

    cpu_percent: float | None
    cpu_count: int | None
    memory_used: int | None
    memory_total: int | None
    disk_used: int | None
    disk_total: int | None
    hostname: str | None

    @staticmethod
    def _percent(used: int | None, total: int | None) -> float | None:
        """Return used as a percentage of total."""
        if not used or not total:
            return None
        return round(used / total * 100, 1)

    @property
    def memory_percent(self) -> float | None:
        """Return the share of host memory in use."""
        return self._percent(self.memory_used, self.memory_total)

    @property
    def disk_percent(self) -> float | None:
        """Return the share of host disk space in use."""
        return self._percent(self.disk_used, self.disk_total)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ArcaneHostStats:
        """Build host statistics from one WebSocket sample."""

        def number(key: str) -> Any:
            value = payload.get(key)
            return value if isinstance(value, (int, float)) else None

        cpu = number("cpuUsage")
        return cls(
            cpu_percent=round(float(cpu), 1) if cpu is not None else None,
            cpu_count=payload.get("cpuCount") or None,
            memory_used=number("memoryUsage"),
            memory_total=number("memoryTotal"),
            disk_used=number("diskUsage"),
            disk_total=number("diskTotal"),
            hostname=payload.get("hostname") or None,
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
    host_stats: ArcaneHostStats | None = None
    arcane_version: ArcaneVersion | None = None

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

    @property
    def containers_unhealthy(self) -> int:
        """Return the number of containers reporting an unhealthy check."""
        return sum(1 for item in self.containers.values() if item.is_healthy is False)

    def project_id_for(self, name: str | None) -> str | None:
        """Return the ID of the project with this compose name, if tracked."""
        if not name:
            return None
        for project in self.projects.values():
            if project.name == name:
                return project.id
        return None


@dataclass(slots=True)
class ArcaneData:
    """The full snapshot handed to the entities on every refresh."""

    version: str | None
    environments: dict[str, ArcaneEnvironment] = field(default_factory=dict)
