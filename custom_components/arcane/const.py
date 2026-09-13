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
CONF_HOST_STATS: Final = "host_stats"
CONF_HEALTH_SENSORS: Final = "health_sensors"
CONF_ENTITY_PREFIX: Final = "entity_prefix"
CONF_NEST_CONTAINERS: Final = "nest_containers"
CONF_EVENTS: Final = "events"
CONF_REDEPLOY_BUTTONS: Final = "redeploy_buttons"
CONF_PRUNE_BUTTON: Final = "prune_button"

# Values of the prune button option. Containers and volumes are deliberately
# never pruned: both destroy data that cannot be pulled back.
PRUNE_OFF: Final = "off"
PRUNE_DANGLING: Final = "dangling"
PRUNE_UNUSED: Final = "unused"
PRUNE_MODES: Final = [PRUNE_OFF, PRUNE_DANGLING, PRUNE_UNUSED]

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
    CONF_HOST_STATS: False,
    CONF_HEALTH_SENSORS: True,
    CONF_ENTITY_PREFIX: True,
    CONF_NEST_CONTAINERS: True,
    CONF_EVENTS: True,
    CONF_REDEPLOY_BUTTONS: False,
    CONF_PRUNE_BUTTON: PRUNE_OFF,
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

# Health as Docker reports it in the status line of a container.
HEALTH_HEALTHY: Final = "healthy"
HEALTH_UNHEALTHY: Final = "unhealthy"
HEALTH_STARTING: Final = "starting"

# Events fired on the Home Assistant bus.
EVENT_CONTAINER_STATE: Final = "arcane_container_state_changed"
EVENT_CONTAINER_HEALTH: Final = "arcane_container_health_changed"
EVENT_PROJECT_STATE: Final = "arcane_project_state_changed"

# Exit code Docker reports when the kernel OOM killer or a SIGKILL ended the
# main process. It is the usual fingerprint of an out of memory kill.
EXIT_CODE_SIGKILL: Final = 137
