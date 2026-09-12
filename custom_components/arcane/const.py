"""Constants for the Arcane integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "arcane"

MANUFACTURER: Final = "Arcane"

DEFAULT_TIMEOUT: Final = 30

# Options
CONF_ENVIRONMENTS: Final = "environments"
CONF_MONITOR_CONTAINERS: Final = "monitor_containers"
CONF_MONITOR_PROJECTS: Final = "monitor_projects"
CONF_MONITOR_RESOURCES: Final = "monitor_resources"
CONF_INCLUDE_INTERNAL: Final = "include_internal"
CONF_INCLUDE_HIDDEN: Final = "include_hidden"
CONF_ALLOW_CONTROL: Final = "allow_control"
CONF_UPDATE_ENTITIES: Final = "update_entities"

DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 3600

DEFAULT_OPTIONS: Final[dict[str, object]] = {
    "scan_interval": DEFAULT_SCAN_INTERVAL,
    CONF_ENVIRONMENTS: [],
    CONF_MONITOR_CONTAINERS: True,
    CONF_MONITOR_PROJECTS: True,
    CONF_MONITOR_RESOURCES: True,
    CONF_INCLUDE_INTERNAL: False,
    CONF_INCLUDE_HIDDEN: False,
    CONF_ALLOW_CONTROL: True,
    CONF_UPDATE_ENTITIES: True,
}

# Reserved ID of the environment Arcane manages directly.
LOCAL_ENVIRONMENT_ID: Final = "0"

# Container states reported by the Docker daemon.
STATE_RUNNING: Final = "running"
STATE_PAUSED: Final = "paused"

CONTAINER_STATES: Final = [
    "created",
    "dead",
    "exited",
    "paused",
    "removing",
    "restarting",
    "running",
]

# Project (compose stack) states reported by Arcane.
PROJECT_STATE_RUNNING: Final = "running"
PROJECT_STATE_PARTIALLY_RUNNING: Final = "partially running"

PROJECT_STATES: Final = [
    "deploying",
    "partially_running",
    "restarting",
    "running",
    "stopped",
    "stopping",
    "unknown",
]

ENVIRONMENT_STATUS_ONLINE: Final = "online"
