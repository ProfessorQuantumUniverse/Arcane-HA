"""Tests for the Arcane API client."""

from __future__ import annotations

import json

import pytest
from aiohttp import web

from custom_components.arcane.api import (
    ApiGeneration,
    ArcaneAuthenticationError,
    ArcaneClient,
    ArcaneNotFoundError,
    ArcaneResponseError,
    validate_url,
)

# The path segment every per-environment route starts with, per generation.
PREFIX = {ApiGeneration.V2: "environments", ApiGeneration.V3: "agents"}

VERSION = {"currentVersion": "v3.0.0", "updateAvailable": False}


@pytest.fixture(params=list(ApiGeneration), ids=lambda item: f"v{item.value}")
def generation(request: pytest.FixtureRequest) -> ApiGeneration:
    """Run a test against both API generations."""
    return request.param


@pytest.fixture
async def arcane_server(aiohttp_client, socket_enabled):
    """Return a client talking to a stub Arcane API.

    The stub serves the routes of both API generations. Which version endpoint
    exists is controlled through ``seen["versions"]``, so a test can make the
    instance look like Arcane 2, Arcane 3, or neither.
    """
    app = web.Application()
    seen: dict = {"versions": {ApiGeneration.V2, ApiGeneration.V3}, "calls": []}

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
        seen["calls"].append(("POST", request.path, dict(request.query)))
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

    def version(generation: ApiGeneration):
        async def handler(request: web.Request) -> web.Response:
            seen["calls"].append(("GET", request.path, {}))
            if generation not in seen["versions"]:
                return web.json_response(
                    {"success": False, "error": "API endpoint not found"},
                    status=404,
                )
            return web.json_response(VERSION)

        return handler

    async def update_container(request: web.Request) -> web.Response:
        seen["calls"].append(("POST", request.path, dict(request.query)))
        return web.json_response(
            {"success": True, "data": seen.get("update_result", {"failed": 0})}
        )

    async def release_notes(request: web.Request) -> web.Response:
        seen["calls"].append(("GET", request.path, dict(request.query)))
        return web.json_response(
            {"success": True, "data": {"status": "found", "notes": "## Fixes"}}
        )

    async def catch_all(request: web.Request) -> web.Response:
        seen["path"] = request.raw_path
        seen["calls"].append((request.method, request.path, dict(request.query)))
        return web.json_response({"success": True, "data": []})

    app.router.add_get("/api/app/version", version(ApiGeneration.V3))
    app.router.add_get("/api/app-version", version(ApiGeneration.V2))
    for generation, prefix in PREFIX.items():
        base = f"/api/{prefix}"
        app.router.add_get(f"{base}/0/containers", containers)
        app.router.add_get(f"{base}/1/containers", unauthorized)
        app.router.add_get(f"{base}/2/containers", broken)
        app.router.add_get(f"{base}/3/containers", redirect)
        app.router.add_get(f"{base}/4/containers", boom)
        app.router.add_get(f"{base}/5/containers", chunked)
        deploy = "up" if generation is ApiGeneration.V2 else "deploy"
        app.router.add_post(f"{base}/0/projects/web/{deploy}", deploy_ok)
        app.router.add_post(f"{base}/1/projects/web/{deploy}", deploy_failed)
        app.router.add_post(f"{base}/2/projects/web/{deploy}", deploy_cut_off)
        app.router.add_post(f"{base}/3/projects/web/{deploy}", deploy_no_newline)
        app.router.add_post(f"{base}/0/containers/abc/update", update_container)
        app.router.add_get(f"{base}/0/ws/system/stats", host_stats)
        app.router.add_get(f"{base}/6/ws/system/stats", host_stats_redirect)
    app.router.add_get("/api/agents/0/images/updates/releasenotes", release_notes)
    app.router.add_get("/elsewhere/stats", host_stats)
    app.router.add_route("*", "/{tail:.*}", catch_all)

    http = await aiohttp_client(app)
    return http, seen


def _client(http, generation: ApiGeneration | None, path: str = "") -> ArcaneClient:
    """Return a client for the stub server that speaks one generation."""
    return ArcaneClient(
        http.session, str(http.make_url(path)), "secret", generation=generation
    )


async def test_get_containers(arcane_server, generation) -> None:
    """The client unwraps the API envelope and sends the API key."""
    http, seen = arcane_server
    client = _client(http, generation)

    containers = await client.async_get_containers("0")

    assert containers == [{"id": "abc", "names": ["/nginx"]}]
    assert seen["api_key"] == "secret"
    assert seen["limit"] == "-1"


async def test_unauthorized(arcane_server, generation) -> None:
    """HTTP 401 becomes an authentication error."""
    http, _ = arcane_server
    client = _client(http, generation)

    with pytest.raises(ArcaneAuthenticationError):
        await client.async_get_containers("1")


async def test_missing_data_member(arcane_server, generation) -> None:
    """A payload without ``data`` is reported as a response error."""
    http, _ = arcane_server
    client = _client(http, generation)

    with pytest.raises(ArcaneResponseError):
        await client.async_get_containers("2")


async def test_redirects_are_not_followed(arcane_server, generation) -> None:
    """A redirect must never replay the API key against another host."""
    http, _ = arcane_server
    client = _client(http, generation)

    with pytest.raises(ArcaneResponseError, match="redirected"):
        await client.async_get_containers("3")


async def test_path_segments_are_escaped(arcane_server, generation) -> None:
    """An ID cannot break out of the API path."""
    http, seen = arcane_server
    client = _client(http, generation)

    await client.async_get_containers("../../etc")

    assert seen["path"].startswith(
        f"/api/{PREFIX[generation]}/..%2F..%2Fetc/containers?"
    )


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


async def test_subpath_installation(arcane_server, generation) -> None:
    """An Arcane served under a subpath keeps that prefix."""
    http, seen = arcane_server
    client = _client(http, generation, "/arcane")

    await client.async_get_projects("0")

    assert seen["path"].startswith(f"/arcane/api/{PREFIX[generation]}/0/projects")


async def test_error_body_is_quoted_back_sanitized(arcane_server, generation) -> None:
    """A failing call reports the status and a short, printable body."""
    http, _ = arcane_server
    client = _client(http, generation)

    with pytest.raises(ArcaneResponseError, match="HTTP 500"):
        await client.async_get_containers("4")


async def test_large_chunked_reply_is_read_in_full(arcane_server, generation) -> None:
    """A reply that arrives in many chunks is not truncated."""
    http, _ = arcane_server
    client = _client(http, generation)

    containers = await client.async_get_containers("5")

    assert len(containers) == 5000


async def test_project_deploy_reads_the_log_stream(arcane_server, generation) -> None:
    """Deploying a project answers with NDJSON, not a JSON envelope."""
    http, _ = arcane_server
    client = _client(http, generation)

    await client.async_project_action("0", "web", "up")


async def test_project_deploy_surfaces_the_error_line(
    arcane_server, generation
) -> None:
    """A failure inside the stream becomes an error, not a silent success."""
    http, _ = arcane_server
    client = _client(http, generation)

    with pytest.raises(ArcaneResponseError, match="port is already allocated"):
        await client.async_project_action("1", "web", "up")


async def test_project_deploy_needs_the_done_line(arcane_server, generation) -> None:
    """A stream that stops early is reported instead of counted as success."""
    http, _ = arcane_server
    client = _client(http, generation)

    with pytest.raises(ArcaneResponseError, match="finished"):
        await client.async_project_action("2", "web", "up")


async def test_unknown_actions_are_refused(arcane_server, generation) -> None:
    """Only known actions may be turned into a request."""
    http, _ = arcane_server
    client = _client(http, generation)

    with pytest.raises(ValueError):
        await client.async_project_action("0", "web", "destroy")
    with pytest.raises(ValueError):
        await client.async_container_action("0", "abc", "exec")


async def test_host_stats_takes_one_sample(arcane_server, generation) -> None:
    """Host statistics come from a short lived authenticated WebSocket."""
    http, seen = arcane_server
    client = _client(http, generation)

    sample = await client.async_get_host_stats("0")

    assert sample["cpuUsage"] == 12.5
    assert seen["ws_api_key"] == "secret"


async def test_redirected_host_stats_socket_is_refused(
    arcane_server, generation
) -> None:
    """A redirected WebSocket handshake must not be accepted.

    aiohttp follows redirects on the handshake and replays the API key header
    while doing so, so the hop is caught afterwards. This also guards the
    private attribute the check reads: if aiohttp renames it, this test fails.
    """
    http, _ = arcane_server
    client = _client(http, generation)

    with pytest.raises(ArcaneResponseError, match="redirected"):
        await client.async_get_host_stats("6")


async def test_stream_without_newlines_is_refused(arcane_server, generation) -> None:
    """A reply that never ends a line cannot grow the buffer without bound."""
    http, _ = arcane_server
    client = _client(http, generation)

    with pytest.raises(ArcaneResponseError, match="malformed"):
        await client.async_project_action("3", "web", "up")


@pytest.mark.parametrize("instance", list(ApiGeneration), ids=["v2", "v3"])
async def test_version_detects_the_generation(arcane_server, instance) -> None:
    """The version endpoint that answers tells which API layout is in use."""
    http, seen = arcane_server
    seen["versions"] = {instance}
    client = _client(http, None)

    assert await client.async_get_version() == VERSION
    assert client.generation is instance


async def test_version_without_any_endpoint(arcane_server) -> None:
    """An address that is no Arcane API at all is reported as not found."""
    http, seen = arcane_server
    seen["versions"] = set()
    client = _client(http, None)

    with pytest.raises(ArcaneNotFoundError):
        await client.async_get_version()
    assert client.generation is None


async def test_known_generation_is_asked_first(arcane_server) -> None:
    """A steady instance costs one version request, not one per generation."""
    http, seen = arcane_server
    seen["versions"] = {ApiGeneration.V2}
    client = _client(http, ApiGeneration.V2)

    await client.async_get_version()

    assert seen["calls"] == [("GET", "/api/app-version", {})]


async def test_upgrade_to_arcane_3_is_noticed(arcane_server) -> None:
    """An instance upgraded while Home Assistant runs switches layout."""
    http, seen = arcane_server
    client = _client(http, None)
    seen["versions"] = {ApiGeneration.V2}
    await client.async_get_version()
    assert client.generation is ApiGeneration.V2

    seen["versions"] = {ApiGeneration.V3}
    await client.async_get_version()
    await client.async_get_projects("0")

    assert client.generation is ApiGeneration.V3
    assert seen["calls"][-1] == ("GET", "/api/agents/0/projects", {"limit": "-1"})


async def test_generation_is_found_out_lazily(arcane_server) -> None:
    """A client that has not asked for the version yet does so first."""
    http, seen = arcane_server
    seen["versions"] = {ApiGeneration.V2}
    client = _client(http, None)

    await client.async_get_projects("0")

    assert [call[1] for call in seen["calls"]] == [
        "/api/app/version",
        "/api/app-version",
        "/api/environments/0/projects",
    ]


async def test_environment_list_path(arcane_server, generation) -> None:
    """The environment list moved from /environments to /agents."""
    http, seen = arcane_server
    client = _client(http, generation)

    await client.async_get_environments()

    assert seen["calls"][-1] == ("GET", f"/api/{PREFIX[generation]}", {"limit": "-1"})


@pytest.mark.parametrize(
    ("generation", "action", "path", "query"),
    [
        (ApiGeneration.V2, "start", "/api/environments/0/containers/abc/start", {}),
        (
            ApiGeneration.V2,
            "redeploy",
            "/api/environments/0/containers/abc/redeploy",
            {},
        ),
        (
            ApiGeneration.V3,
            "start",
            "/api/agents/0/containers/abc",
            {"action": "start"},
        ),
        (ApiGeneration.V3, "stop", "/api/agents/0/containers/abc", {"action": "stop"}),
        (ApiGeneration.V3, "redeploy", "/api/agents/0/containers/abc/redeploy", {}),
    ],
)
async def test_container_action_requests(
    arcane_server, generation, action, path, query
) -> None:
    """Arcane 3 takes most container actions as a query parameter."""
    http, seen = arcane_server
    client = _client(http, generation)

    await client.async_container_action("0", "abc", action)

    assert seen["calls"][-1] == ("POST", path, query)


@pytest.mark.parametrize(
    ("generation", "action", "path", "query"),
    [
        (ApiGeneration.V2, "down", "/api/environments/9/projects/web/down", {}),
        (ApiGeneration.V2, "restart", "/api/environments/9/projects/web/restart", {}),
        (ApiGeneration.V3, "down", "/api/agents/9/projects/web", {"action": "down"}),
        (
            ApiGeneration.V3,
            "restart",
            "/api/agents/9/projects/web",
            {"action": "restart"},
        ),
    ],
)
async def test_project_action_requests(
    arcane_server, generation, action, path, query
) -> None:
    """Arcane 3 runs project actions through an action parameter."""
    http, seen = arcane_server
    client = _client(http, generation)

    await client.async_project_action("9", "web", action)

    assert seen["calls"][-1] == ("POST", path, query)


@pytest.mark.parametrize("action", ["up", "redeploy"])
async def test_arcane_3_deploys_through_the_deploy_route(arcane_server, action) -> None:
    """Deploying and redeploying share one streaming route in Arcane 3."""
    http, seen = arcane_server
    client = _client(http, ApiGeneration.V3)

    await client.async_project_action("0", "web", action)

    assert seen["calls"][-1] == (
        "POST",
        "/api/agents/0/projects/web/deploy",
        {"action": action},
    )


async def test_update_container(arcane_server, generation) -> None:
    """Installing an update runs Arcane's updater for that container."""
    http, seen = arcane_server
    seen["update_result"] = {"updated": 1, "failed": 0, "items": []}
    client = _client(http, generation)

    result = await client.async_update_container("0", "abc")

    assert result["updated"] == 1
    assert seen["calls"][-1] == (
        "POST",
        f"/api/{PREFIX[generation]}/0/containers/abc/update",
        {},
    )


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (
            {"failed": 1, "items": [{"status": "failed", "error": "pull\x00 denied"}]},
            "pull  denied",
        ),
        ({"failed": 1, "items": []}, "could not apply"),
    ],
)
async def test_failed_update_is_an_error(arcane_server, result, message) -> None:
    """Arcane reports a failed update inside a 200 reply; that must not pass."""
    http, seen = arcane_server
    seen["update_result"] = result
    client = _client(http, ApiGeneration.V3)

    with pytest.raises(ArcaneResponseError, match=message):
        await client.async_update_container("0", "abc")


async def test_skipped_update_is_not_an_error(arcane_server) -> None:
    """A container that is already up to date is not a failure."""
    http, seen = arcane_server
    seen["update_result"] = {
        "skipped": 1,
        "failed": 0,
        "items": [{"status": "up_to_date"}],
    }
    client = _client(http, ApiGeneration.V3)

    assert (await client.async_update_container("0", "abc"))["skipped"] == 1


async def test_release_notes_on_arcane_3(arcane_server) -> None:
    """Arcane 3 looks up the release of the target version for an image."""
    http, seen = arcane_server
    client = _client(http, ApiGeneration.V3)

    notes = await client.async_get_release_notes(
        "0", "traefik/whoami:v1.11.0", version="v1.12.0", digest="sha256:new"
    )

    assert notes == {"status": "found", "notes": "## Fixes"}
    assert seen["calls"][-1] == (
        "GET",
        "/api/agents/0/images/updates/releasenotes",
        {
            "imageRef": "traefik/whoami:v1.11.0",
            "version": "v1.12.0",
            "digest": "sha256:new",
        },
    )


async def test_release_notes_skip_what_is_unknown(arcane_server) -> None:
    """A digest update has no version to ask for."""
    http, seen = arcane_server
    client = _client(http, ApiGeneration.V3)

    await client.async_get_release_notes("0", "app:latest", digest="sha256:new")

    assert seen["calls"][-1][2] == {"imageRef": "app:latest", "digest": "sha256:new"}


async def test_arcane_2_has_no_release_notes(arcane_server) -> None:
    """Arcane 2 has no release notes endpoint, so nothing is requested."""
    http, seen = arcane_server
    client = _client(http, ApiGeneration.V2)

    assert await client.async_get_release_notes("0", "app:1", version="2") == {}
    assert seen["calls"] == []
