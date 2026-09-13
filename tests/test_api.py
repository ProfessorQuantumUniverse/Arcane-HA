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

    async def _ndjson(request: web.Request, lines: list[str]) -> web.StreamResponse:
        """Answer the way Arcane answers a project deploy."""
        response = web.StreamResponse()
        response.content_type = "application/x-json-stream"
        await response.prepare(request)
        for line in lines:
            await response.write(line.encode() + b"\n")
        await response.write_eof()
        return response

    async def deploy_ok(request: web.Request) -> web.StreamResponse:
        return await _ndjson(
            request,
            [
                '{"activityId":"act-1"}',
                '{"log":"Container web-1  Created"}',
                '{"log":"Container web-1  Started"}',
                '{"done":true}',
            ],
        )

    async def deploy_failed(request: web.Request) -> web.StreamResponse:
        return await _ndjson(
            request,
            [
                '{"activityId":"act-2"}',
                '{"error":"port is already allocated"}',
            ],
        )

    async def deploy_cut_off(request: web.Request) -> web.StreamResponse:
        return await _ndjson(request, ['{"activityId":"act-3"}', '{"log":"pulling"}'])

    async def deploy_no_newline(request: web.Request) -> web.StreamResponse:
        """Answer with one endless line, the way a broken host might."""
        response = web.StreamResponse()
        response.content_type = "application/x-json-stream"
        await response.prepare(request)
        for _ in range(40):
            await response.write(b"x" * 65536)
        await response.write_eof()
        return response

    async def host_stats(request: web.Request) -> web.WebSocketResponse:
        seen["ws_api_key"] = request.headers.get("X-Api-Key", "")
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        await socket.send_json(
            {
                "cpuUsage": 12.5,
                "memoryUsage": 4294967296,
                "memoryTotal": 16777216000,
                "diskUsage": 100000000000,
                "diskTotal": 500000000000,
                "cpuCount": 8,
                "hostname": "docker-host",
            }
        )
        return socket

    async def host_stats_redirect(request: web.Request) -> web.WebSocketResponse:
        raise web.HTTPFound(location="/elsewhere/stats")

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
    app.router.add_post("/api/environments/0/projects/web/up", deploy_ok)
    app.router.add_post("/api/environments/1/projects/web/up", deploy_failed)
    app.router.add_post("/api/environments/2/projects/web/up", deploy_cut_off)
    app.router.add_post("/api/environments/3/projects/web/up", deploy_no_newline)
    app.router.add_get("/api/environments/0/ws/system/stats", host_stats)
    app.router.add_get("/api/environments/6/ws/system/stats", host_stats_redirect)
    app.router.add_get("/elsewhere/stats", host_stats)
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


async def test_project_deploy_reads_the_log_stream(arcane_server) -> None:
    """Deploying a project answers with NDJSON, not a JSON envelope."""
    http, _ = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("")), "secret")

    await client.async_project_action("0", "web", "up")


async def test_project_deploy_surfaces_the_error_line(arcane_server) -> None:
    """A failure inside the stream becomes an error, not a silent success."""
    http, _ = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("")), "secret")

    with pytest.raises(ArcaneResponseError, match="port is already allocated"):
        await client.async_project_action("1", "web", "up")


async def test_project_deploy_needs_the_done_line(arcane_server) -> None:
    """A stream that stops early is reported instead of counted as success."""
    http, _ = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("")), "secret")

    with pytest.raises(ArcaneResponseError, match="finished"):
        await client.async_project_action("2", "web", "up")


async def test_unknown_actions_are_refused(arcane_server) -> None:
    """Only known actions may be turned into a request path."""
    http, _ = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("")), "secret")

    with pytest.raises(ValueError):
        await client.async_project_action("0", "web", "destroy")
    with pytest.raises(ValueError):
        await client.async_container_action("0", "abc", "exec")


async def test_host_stats_takes_one_sample(arcane_server) -> None:
    """Host statistics come from a short lived authenticated WebSocket."""
    http, seen = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("")), "secret")

    sample = await client.async_get_host_stats("0")

    assert sample["cpuUsage"] == 12.5
    assert seen["ws_api_key"] == "secret"


async def test_redirected_host_stats_socket_is_refused(arcane_server) -> None:
    """A redirected WebSocket handshake must not be accepted.

    aiohttp follows redirects on the handshake and replays the API key header
    while doing so, so the hop is caught afterwards. This also guards the
    private attribute the check reads: if aiohttp renames it, this test fails.
    """
    http, _ = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("")), "secret")

    with pytest.raises(ArcaneResponseError, match="redirected"):
        await client.async_get_host_stats("6")


async def test_stream_without_newlines_is_refused(arcane_server) -> None:
    """A reply that never ends a line cannot grow the buffer without bound."""
    http, _ = arcane_server
    client = ArcaneClient(http.session, str(http.make_url("")), "secret")

    with pytest.raises(ArcaneResponseError, match="malformed"):
        await client.async_project_action("3", "web", "up")
