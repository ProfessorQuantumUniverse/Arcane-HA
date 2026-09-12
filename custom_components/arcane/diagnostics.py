"""Diagnostics support for the Arcane integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from . import ArcaneConfigEntry

TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ArcaneConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "version": data.version,
        "environments": [
            {
                "id": environment.id,
                "name": environment.name,
                "status": environment.status,
                "enabled": environment.enabled,
                "reachable": environment.reachable,
                "docker_version": environment.docker_version,
                "image_counts": environment.image_counts,
                "volume_counts": environment.volume_counts,
                "network_counts": environment.network_counts,
                "containers": [
                    asdict(container) for container in environment.containers.values()
                ],
                "projects": [
                    asdict(project) for project in environment.projects.values()
                ],
            }
            for environment in data.environments.values()
        ],
    }
