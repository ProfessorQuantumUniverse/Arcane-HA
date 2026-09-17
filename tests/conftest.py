"""Fixtures for the Arcane integration tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.arcane.const import DOMAIN

VERSION_PAYLOAD = {
    "currentVersion": "1.4.0",
    "newestVersion": "1.5.0",
    "updateAvailable": True,
    "releaseUrl": "https://github.com/getarcaneapp/arcane/releases/tag/1.5.0",
    "releaseNotes": "## What's new\n\nFaster project list.",
    "releasedAt": "2026-09-01T10:00:00Z",
    "revision": "abcdef",
}

REMOTE_VERSION_PAYLOAD = {
    "currentVersion": "1.3.0",
    "updateAvailable": False,
    "revision": "123456",
}

ENVIRONMENTS_PAYLOAD = [
    {"id": "0", "name": "Local", "status": "online", "enabled": True},
]

CONTAINERS_PAYLOAD = [
    {
        "id": "c1ffee",
        "names": ["/homeassistant"],
        "image": "ghcr.io/home-assistant/home-assistant:stable",
        "imageId": "sha256:1",
        "command": "/init",
        "created": 1735689600,
        "state": "running",
        "status": "Up 2 hours",
        "labels": {
            "com.docker.compose.project": "smarthome",
            "com.docker.compose.service": "homeassistant",
        },
        "updateInfo": {
            "hasUpdate": True,
            "currentVersion": "2025.1.0",
            "latestVersion": "2025.2.0",
        },
    },
    {
        "id": "beefcafe",
        "names": ["/uptime-kuma"],
        "image": "louislam/uptime-kuma:2",
        "imageId": "sha256:3",
        "command": "/entry",
        "created": 1735689600,
        "state": "running",
        "status": "Up 26 hours (healthy)",
        "labels": {},
    },
    {
        "id": "dead10cc",
        "names": ["/whoami"],
        "image": "traefik/whoami:latest",
        "imageId": "sha256:2",
        "command": "/whoami",
        "created": 1735689600,
        "state": "exited",
        "status": "Exited (0) 3 hours ago",
        "labels": {},
    },
]

PROJECTS_PAYLOAD = [
    {
        "id": "smarthome",
        "name": "smarthome",
        "status": "running",
        "runningCount": 2,
        "serviceCount": 2,
        "updateInfo": {"hasUpdate": False},
    },
]

IMAGE_COUNTS = {
    "totalImages": 12,
    "imagesUnused": 3,
    "imagesInuse": 9,
    "totalImageSize": 5368709120,
}
VOLUME_COUNTS = {"total": 7, "unused": 1, "inuse": 6}
NETWORK_COUNTS = {"total": 4, "unused": 0, "inuse": 4}
DOCKER_INFO = {"ServerVersion": "27.3.1", "apiVersion": "1.47", "os": "linux"}
HOST_STATS = {
    "cpuUsage": 12.5,
    "memoryUsage": 4294967296,
    "memoryTotal": 17179869184,
    "diskUsage": 100000000000,
    "diskTotal": 500000000000,
    "cpuCount": 8,
    "hostname": "docker-host",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Make the custom integration loadable in tests."""
    yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a configured Arcane config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="192.168.1.10",
        data={
            "url": "http://192.168.1.10:3552",
            "api_key": "test-key",
            "verify_ssl": True,
        },
    )


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Patch the Arcane API client with canned responses."""
    with (
        patch("custom_components.arcane.ArcaneClient", autospec=True) as client_class,
        patch("custom_components.arcane.config_flow.ArcaneClient", new=client_class),
    ):
        client = client_class.return_value
        client.async_get_version.return_value = VERSION_PAYLOAD
        client.async_get_environments.return_value = ENVIRONMENTS_PAYLOAD
        client.async_get_containers.return_value = CONTAINERS_PAYLOAD
        client.async_get_projects.return_value = PROJECTS_PAYLOAD
        client.async_get_image_counts.return_value = IMAGE_COUNTS
        client.async_get_volume_counts.return_value = VOLUME_COUNTS
        client.async_get_network_counts.return_value = NETWORK_COUNTS
        client.async_get_docker_info.return_value = DOCKER_INFO
        client.async_get_host_stats.return_value = HOST_STATS
        client.async_get_environment_version.return_value = REMOTE_VERSION_PAYLOAD
        client.async_prune.return_value = {"spaceReclaimed": 1024}
        yield client
