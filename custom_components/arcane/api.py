"""Minimal async client for the Arcane REST API."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Final
from urllib.parse import quote, urlsplit

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout
from homeassistant.util.json import json_loads
from yarl import URL

from .const import DEFAULT_TIMEOUT

API_PATH: Final = "/api"
HEADER_API_KEY: Final = "X-Api-Key"

ALLOWED_SCHEMES: Final = ("http", "https")

# Only these actions may be built into a request path.
CONTAINER_ACTIONS: Final = ("start", "stop", "restart", "redeploy")
PROJECT_ACTIONS: Final = ("up", "down", "restart")

# Arcane paginates every list endpoint; ``-1`` asks for the full set.
_ALL_ITEMS: Final = "-1"

# Container actions block until Docker is done, and deploying a project can
# additionally pull images, so both get more headroom than a plain read.
ACTION_TIMEOUT: Final = 300
DEPLOY_TIMEOUT: Final = 900

# Refuse to buffer a reply larger than this. Every endpoint used here returns a
# small JSON document, so anything bigger means the URL does not point at an
# Arcane API and should not be allowed to exhaust memory.
MAX_RESPONSE_BYTES: Final = 32 * 1024 * 1024

# Only the first part of an error body is quoted back, with control characters
# removed so a hostile reply cannot forge log lines.
_ERROR_BODY_CHARS: Final = 200
_ERROR_BODY_BYTES: Final = 4096
_READ_CHUNK_BYTES: Final = 64 * 1024


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


def validate_url(url: str) -> str:
    """Return a normalized instance URL, or raise ``ValueError``.

    Only plain http and https addresses are accepted. Userinfo in the URL is
    rejected: it would end up in log messages, and Arcane authenticates with
    the API key header, never with basic auth.
    """
    parts = urlsplit(url.strip())
    if parts.scheme not in ALLOWED_SCHEMES:
        raise ValueError("Only http:// and https:// addresses are supported")
    if not parts.hostname:
        raise ValueError("The address is missing a host name")
    if parts.username or parts.password:
        raise ValueError("Credentials in the address are not supported")
    if parts.query or parts.fragment:
        raise ValueError("The address must not contain a query or fragment")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


def _sanitize(text: str) -> str:
    """Return text that is safe to put into an error message or log line."""
    return "".join(
        char if char.isprintable() else " " for char in text[:_ERROR_BODY_CHARS]
    ).strip()


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
        api_key = api_key.strip()
        if not api_key:
            raise ValueError("The API key must not be empty")
        if any(char in api_key for char in "\r\n\x00"):
            raise ValueError("The API key contains invalid characters")

        self._session = session
        base = validate_url(url)
        scheme, _, rest = base.partition("://")
        netloc, slash, path = rest.partition("/")
        self._base_url = (
            f"{scheme}://{netloc}{slash}{quote(path, safe='/%')}{API_PATH}/"
        )
        self._api_key = api_key
        self._timeout = ClientTimeout(total=timeout)

    def _url(self, *segments: str) -> URL:
        """Build an API URL from fully escaped path segments.

        Container names, project IDs and environment IDs come from the Arcane
        API, so they are escaped rather than trusted: no segment can add a path
        of its own or walk out of ``/api/``. The URL is marked as encoded so
        the escaping is not undone before the request goes out.
        """
        path = "/".join(quote(str(segment), safe="") for segment in segments)
        return URL(self._base_url + path, encoded=True)

    async def _request(
        self,
        method: str,
        url: URL,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        timeout: int | None = None,
    ) -> Any:
        """Perform a request and return the decoded JSON body."""
        try:
            response = await self._session.request(
                method,
                url,
                params=params,
                json=json,
                headers={HEADER_API_KEY: self._api_key},
                timeout=ClientTimeout(total=timeout) if timeout else self._timeout,
                # Redirects are not followed: aiohttp would replay the API key
                # header against whatever host the redirect points at.
                allow_redirects=False,
            )
        except TimeoutError as err:
            raise ArcaneConnectionError(f"Timeout while calling {url}") from err
        except ClientError as err:
            raise ArcaneConnectionError(f"Error while calling {url}: {err}") from err

        async with response:
            return await self._decode(response, url)

    @staticmethod
    async def _decode(response: ClientResponse, url: URL) -> Any:
        """Turn a response into JSON, mapping HTTP errors onto exceptions."""
        if response.status == HTTPStatus.UNAUTHORIZED:
            raise ArcaneAuthenticationError(f"Arcane rejected the API key for {url}")
        if response.status == HTTPStatus.FORBIDDEN:
            raise ArcanePermissionError(f"The API key is not allowed to call {url}")
        if HTTPStatus.MULTIPLE_CHOICES <= response.status < HTTPStatus.BAD_REQUEST:
            raise ArcaneResponseError(
                f"{url} redirected to another address. Configure the address "
                f"Arcane is actually served on."
            )
        if response.status >= HTTPStatus.BAD_REQUEST:
            # Only the first chunk is read: the body of an error reply is quoted
            # back to the user and is not trusted to be small.
            body = _sanitize(
                (await response.content.read(_ERROR_BODY_BYTES)).decode(
                    "utf-8", "replace"
                )
            )
            raise ArcaneResponseError(
                f"Arcane returned HTTP {response.status} for {url}: {body}"
            )

        if (length := response.content_length) is not None and (
            length > MAX_RESPONSE_BYTES
        ):
            raise ArcaneResponseError(f"Reply from {url} is too large ({length} bytes)")
        chunks: list[bytes] = []
        size = 0
        try:
            async for chunk in response.content.iter_chunked(_READ_CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ArcaneResponseError(f"Reply from {url} is too large")
                chunks.append(chunk)
        except ClientError as err:
            raise ArcaneConnectionError(f"Error while reading {url}: {err}") from err
        raw = b"".join(chunks)

        if not raw.strip():
            # Some action endpoints answer without a body.
            return None
        try:
            return json_loads(raw)
        except ValueError as err:
            raise ArcaneResponseError(f"Invalid JSON from {url}") from err

    async def _get_data(self, url: URL, params: dict[str, Any] | None = None) -> Any:
        """Return the ``data`` member of an Arcane API envelope."""
        payload = await self._request("GET", url, params=params)
        if not isinstance(payload, dict) or "data" not in payload:
            raise ArcaneResponseError(f"Unexpected payload from {url}")
        return payload["data"]

    async def async_get_version(self) -> dict[str, Any]:
        """Return version information about the Arcane instance."""
        payload = await self._request("GET", self._url("app-version"))
        if not isinstance(payload, dict):
            raise ArcaneResponseError("Unexpected payload for the version endpoint")
        return payload

    async def async_get_environments(self) -> list[dict[str, Any]]:
        """Return every environment the API key may see."""
        data = await self._get_data(self._url("environments"), {"limit": _ALL_ITEMS})
        return data if isinstance(data, list) else []

    async def async_get_containers(
        self,
        environment_id: str,
        *,
        include_internal: bool = False,
        include_hidden: bool = False,
    ) -> list[dict[str, Any]]:
        """Return all containers of an environment."""
        data = await self._get_data(
            self._url("environments", environment_id, "containers"),
            {
                "limit": _ALL_ITEMS,
                "includeInternal": str(include_internal).lower(),
                "includeHidden": str(include_hidden).lower(),
            },
        )
        return data if isinstance(data, list) else []

    async def async_get_projects(self, environment_id: str) -> list[dict[str, Any]]:
        """Return all compose projects of an environment."""
        data = await self._get_data(
            self._url("environments", environment_id, "projects"),
            {"limit": _ALL_ITEMS},
        )
        return data if isinstance(data, list) else []

    async def async_get_image_counts(self, environment_id: str) -> dict[str, Any]:
        """Return image usage counts of an environment."""
        data = await self._get_data(
            self._url("environments", environment_id, "images", "counts")
        )
        return data if isinstance(data, dict) else {}

    async def async_get_volume_counts(self, environment_id: str) -> dict[str, Any]:
        """Return volume usage counts of an environment."""
        data = await self._get_data(
            self._url("environments", environment_id, "volumes", "counts")
        )
        return data if isinstance(data, dict) else {}

    async def async_get_network_counts(self, environment_id: str) -> dict[str, Any]:
        """Return network usage counts of an environment."""
        data = await self._get_data(
            self._url("environments", environment_id, "networks", "counts")
        )
        return data if isinstance(data, dict) else {}

    async def async_get_docker_info(self, environment_id: str) -> dict[str, Any]:
        """Return Docker daemon information of an environment."""
        payload = await self._request(
            "GET", self._url("environments", environment_id, "system", "docker", "info")
        )
        return payload if isinstance(payload, dict) else {}

    async def async_container_action(
        self, environment_id: str, container_id: str, action: str
    ) -> None:
        """Run start, stop, restart or redeploy on a container."""
        if action not in CONTAINER_ACTIONS:
            raise ValueError(f"Unsupported container action: {action}")
        await self._request(
            "POST",
            self._url(
                "environments", environment_id, "containers", container_id, action
            ),
            timeout=DEPLOY_TIMEOUT if action == "redeploy" else ACTION_TIMEOUT,
        )

    async def async_project_action(
        self, environment_id: str, project_id: str, action: str
    ) -> None:
        """Bring a compose project up or down, or restart it."""
        if action not in PROJECT_ACTIONS:
            raise ValueError(f"Unsupported project action: {action}")
        await self._request(
            "POST",
            self._url("environments", environment_id, "projects", project_id, action),
            timeout=ACTION_TIMEOUT if action == "down" else DEPLOY_TIMEOUT,
        )
