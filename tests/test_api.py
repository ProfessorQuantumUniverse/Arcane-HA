"""Tests for the Arcane API client."""

from __future__ import annotations

import json

import pytest
from aiohttp import web

from custom_components.arcane.api import (
    ArcaneAuthenticationError,
    ArcaneClient,
    ArcaneResponseError,
    validate_url,
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

    async def chunked(request: web.Request) -> web.StreamResponse:
        """Send a large list in many chunks, the way a real host would."""
        payload = json.dumps(
            {"success": True, "data": [{"id": f"c{i}"} for i in range(5000)]}
        ).encode()
        response = web.StreamResponse()
        response.content_type = "application/json"
        await response.prepare(request)
        for start in range(0, len(payload), 1024):
            await response.write(payload[start : start + 1024])
        await response.write_eof()
        return response

    async def boom(request: web.Request) -> web.Response:
        return web.Response(status=500, text="kaboom\x00\x07" + "x" * 10000)

    async def redirect(request: web.Request) -> web.Response:
        raise web.HTTPFound(location="http://attacker.example/api")

    async def catch_all(request: web.Request) -> web.Response:
        seen["path"] = request.raw_path
        return web.json_response({"success": True, "data": []})

    app.router.add_get("/api/environments/0/containers", containers)
    app.router.add_get("/api/environments/1/containers", unauthorized)
    app.router.add_get("/api/environments/2/containers", broken)
    app.router.add_get("/api/environments/3/containers", redirect)
    app.router.add_get("/api/environments/4/containers", boom)
    app.router.add_get("/api/environments/5/containers", chunked)
    app.router.add_route("*", "/{tail:.*}", catch_all)

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


async def test_redirects_are_not_followed(arcane_server) -> None:
    """A redirect must never replay the API key against another host."""
    http, _ = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("")), "secret")

    with pytest.raises(ArcaneResponseError, match="redirected"):
        await client.async_get_containers("3")


async def test_path_segments_are_escaped(arcane_server) -> None:
    """An ID cannot break out of the API path."""
    http, seen = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("")), "secret")

    await client.async_get_containers("../../etc")

    assert seen["path"].startswith("/api/environments/..%2F..%2Fetc/containers?")


@pytest.mark.parametrize(
    "url",
    [
        "ftp://host",
        "file:///etc/passwd",
        "http://user:pass@host",
        "http://host/?a=b",
        "https://",
    ],
)
def test_validate_url_rejects(url: str) -> None:
    """Only plain http and https addresses without userinfo are accepted."""
    with pytest.raises(ValueError):
        validate_url(url)


def test_validate_url_normalizes() -> None:
    """A trailing slash is dropped and a subpath is kept."""
    assert validate_url("http://host:3552/") == "http://host:3552"
    assert validate_url(" https://host/arcane/ ") == "https://host/arcane"


@pytest.mark.parametrize("api_key", ["", "   ", "key\nX-Evil: 1"])
def test_bad_api_keys_are_rejected(api_key: str) -> None:
    """An empty key or one that could inject a header is refused."""
    with pytest.raises(ValueError):
        ArcaneClient(None, "http://host", api_key)


async def test_subpath_installation(arcane_server) -> None:
    """An Arcane served under a subpath keeps that prefix."""
    http, seen = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("/arcane")), "secret")

    await client.async_get_projects("0")

    assert seen["path"].startswith("/arcane/api/environments/0/projects")


async def test_error_body_is_quoted_back_sanitized(arcane_server) -> None:
    """A failing call reports the status and a short, printable body."""
    http, _ = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("")), "secret")

    with pytest.raises(ArcaneResponseError, match="HTTP 500"):
        await client.async_get_containers("4")


async def test_large_chunked_reply_is_read_in_full(arcane_server) -> None:
    """A reply that arrives in many chunks is not truncated."""
    http, _ = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("")), "secret")

    containers = await client.async_get_containers("5")

    assert len(containers) == 5000
