"""Constants for the Arcane integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "arcane"

MANUFACTURER: Final = "Arcane"

DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=30)
DEFAULT_TIMEOUT: Final = 30

CONF_VERIFY_SSL: Final = "verify_ssl"

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
