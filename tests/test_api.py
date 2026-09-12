"""Tests for the Arcane API client."""

from __future__ import annotations

import pytest
from aiohttp import web

from custom_components.arcane.api import (
    ArcaneAuthenticationError,
    ArcaneClient,
    ArcaneResponseError,
)


@pytest.fixture
async def arcane_server(aiohttp_client, socket_enabled):
    """Return a client talking to a stub Arcane API."""
    app = web.Application()
    seen: dict[str, str] = {}

    async def containers(request: web.Request) -> web.Response:
        seen["api_key"] = request.headers.get("X-Api-Key", "")
        seen["limit"] = request.query.get("limit", "")
        return web.json_response(
            {"success": True, "data": [{"id": "abc", "names": ["/nginx"]}]}
        )

    async def unauthorized(request: web.Request) -> web.Response:
        return web.json_response({"error": "nope"}, status=401)

    async def broken(request: web.Request) -> web.Response:
        return web.json_response({"success": True}, status=200)

    app.router.add_get("/api/environments/0/containers", containers)
    app.router.add_get("/api/environments/1/containers", unauthorized)
    app.router.add_get("/api/environments/2/containers", broken)

    http = await aiohttp_client(app)
    return http, seen


async def test_get_containers(arcane_server) -> None:
    """The client unwraps the API envelope and sends the API key."""
    http, seen = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("")), "secret")

    containers = await client.async_get_containers("0")

    assert containers == [{"id": "abc", "names": ["/nginx"]}]
    assert seen["api_key"] == "secret"
    assert seen["limit"] == "-1"


async def test_unauthorized(arcane_server) -> None:
    """HTTP 401 becomes an authentication error."""
    http, _ = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("")), "secret")

    with pytest.raises(ArcaneAuthenticationError):
        await client.async_get_containers("1")


async def test_missing_data_member(arcane_server) -> None:
    """A payload without ``data`` is reported as a response error."""
    http, _ = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("")), "secret")

    with pytest.raises(ArcaneResponseError):
        await client.async_get_containers("2")
