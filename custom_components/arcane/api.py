"""Minimal async client for the Arcane REST API."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any, Final
from urllib.parse import urljoin

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout

from .const import DEFAULT_TIMEOUT

_LOGGER = logging.getLogger(__name__)

API_PATH: Final = "/api"
HEADER_API_KEY: Final = "X-Api-Key"

# Arcane paginates every list endpoint; ``-1`` asks for the full set.
_ALL_ITEMS: Final = "-1"

# Container actions block until Docker is done, and deploying a project can
# additionally pull images, so both get more headroom than a plain read.
ACTION_TIMEOUT: Final = 300
DEPLOY_TIMEOUT: Final = 900


class ArcaneError(Exception):
    """Base error for all Arcane API failures."""


class ArcaneConnectionError(ArcaneError):
    """Raised when the Arcane instance cannot be reached."""


class ArcaneAuthenticationError(ArcaneError):
    """Raised when Arcane does not accept the API key at all."""


class ArcanePermissionError(ArcaneError):
    """Raised when the API key is valid but lacks a permission.

    This is kept apart from an authentication failure: asking the user for a
    new key does not help, they have to widen the permissions of the one they
    have.
    """


class ArcaneResponseError(ArcaneError):
    """Raised when Arcane answers with an unexpected payload or status."""


class ArcaneClient:
    """Thin wrapper around the endpoints the integration needs."""

    def __init__(
        self,
        session: ClientSession,
        url: str,
        api_key: str,
        *,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the client for a single Arcane instance."""
        self._session = session
        self._base_url = f"{url.rstrip('/')}{API_PATH}/"
        self._api_key = api_key
        self._timeout = ClientTimeout(total=timeout)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        timeout: int | None = None,
    ) -> Any:
        """Perform a request and return the decoded JSON body."""
        url = urljoin(self._base_url, path.lstrip("/"))
        try:
            response = await self._session.request(
                method,
                url,
                params=params,
                json=json,
                headers={HEADER_API_KEY: self._api_key},
                timeout=ClientTimeout(total=timeout) if timeout else self._timeout,
            )
        except TimeoutError as err:
            raise ArcaneConnectionError(f"Timeout while calling {url}") from err
        except ClientError as err:
            raise ArcaneConnectionError(f"Error while calling {url}: {err}") from err

        return await self._decode(response, url)

    @staticmethod
    async def _decode(response: ClientResponse, url: str) -> Any:
        """Turn a response into JSON, mapping HTTP errors onto exceptions."""
        if response.status == HTTPStatus.UNAUTHORIZED:
            raise ArcaneAuthenticationError(f"Arcane rejected the API key for {url}")
        if response.status == HTTPStatus.FORBIDDEN:
            raise ArcanePermissionError(f"The API key is not allowed to call {url}")
        if response.status >= HTTPStatus.BAD_REQUEST:
            body = (await response.text())[:200]
            raise ArcaneResponseError(
                f"Arcane returned HTTP {response.status} for {url}: {body}"
            )
        if response.status == HTTPStatus.NO_CONTENT or not response.content_length:
            # Some action endpoints answer without a body.
            text = await response.text()
            if not text.strip():
                return None
        try:
            return await response.json(content_type=None)
        except ValueError as err:
            raise ArcaneResponseError(f"Invalid JSON from {url}") from err

    async def _get_data(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Return the ``data`` member of an Arcane API envelope."""
        payload = await self._request("GET", path, params=params)
        if not isinstance(payload, dict) or "data" not in payload:
            raise ArcaneResponseError(f"Unexpected payload for {path}")
        return payload["data"]

    async def async_get_version(self) -> dict[str, Any]:
        """Return version information about the Arcane instance."""
        payload = await self._request("GET", "app-version")
        if not isinstance(payload, dict):
            raise ArcaneResponseError("Unexpected payload for app-version")
        return payload

    async def async_get_environments(self) -> list[dict[str, Any]]:
        """Return every environment the API key may see."""
        data = await self._get_data("environments", {"limit": _ALL_ITEMS})
        return data if isinstance(data, list) else []

    async def async_get_containers(self, environment_id: str) -> list[dict[str, Any]]:
        """Return all containers of an environment."""
        data = await self._get_data(
            f"environments/{environment_id}/containers", {"limit": _ALL_ITEMS}
        )
        return data if isinstance(data, list) else []

    async def async_get_projects(self, environment_id: str) -> list[dict[str, Any]]:
        """Return all compose projects of an environment."""
        data = await self._get_data(
            f"environments/{environment_id}/projects", {"limit": _ALL_ITEMS}
        )
        return data if isinstance(data, list) else []

    async def async_get_image_counts(self, environment_id: str) -> dict[str, Any]:
        """Return image usage counts of an environment."""
        data = await self._get_data(f"environments/{environment_id}/images/counts")
        return data if isinstance(data, dict) else {}

    async def async_get_volume_counts(self, environment_id: str) -> dict[str, Any]:
        """Return volume usage counts of an environment."""
        data = await self._get_data(f"environments/{environment_id}/volumes/counts")
        return data if isinstance(data, dict) else {}

    async def async_get_network_counts(self, environment_id: str) -> dict[str, Any]:
        """Return network usage counts of an environment."""
        data = await self._get_data(f"environments/{environment_id}/networks/counts")
        return data if isinstance(data, dict) else {}

    async def async_get_docker_info(self, environment_id: str) -> dict[str, Any]:
        """Return Docker daemon information of an environment."""
        payload = await self._request(
            "GET", f"environments/{environment_id}/system/docker/info"
        )
        return payload if isinstance(payload, dict) else {}

    async def async_container_action(
        self, environment_id: str, container_id: str, action: str
    ) -> None:
        """Run start, stop, restart, pause or unpause on a container."""
        await self._request(
            "POST",
            f"environments/{environment_id}/containers/{container_id}/{action}",
            timeout=ACTION_TIMEOUT,
        )

    async def async_project_up(self, environment_id: str, project_id: str) -> None:
        """Deploy a compose project."""
        await self._request(
            "POST",
            f"environments/{environment_id}/projects/{project_id}/up",
            timeout=DEPLOY_TIMEOUT,
        )

    async def async_project_down(self, environment_id: str, project_id: str) -> None:
        """Stop a compose project."""
        await self._request(
            "POST",
            f"environments/{environment_id}/projects/{project_id}/down",
            timeout=ACTION_TIMEOUT,
        )

    async def async_project_restart(self, environment_id: str, project_id: str) -> None:
        """Restart every service of a compose project."""
        await self._request(
            "POST",
            f"environments/{environment_id}/projects/{project_id}/restart",
            timeout=DEPLOY_TIMEOUT,
        )
