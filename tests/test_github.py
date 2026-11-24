"""Tests for the release notes read from GitHub."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.arcane.github import (
    GitHubError,
    GitHubRelease,
    ImageUpdate,
    async_release_notes,
    find_release,
    newest_release,
)

RELEASES = "https://api.github.com/repos/acme/app/releases"


def _release(tag: str, *, prerelease: bool = False, body: str = "") -> GitHubRelease:
    return GitHubRelease(
        tag=tag,
        name=tag,
        body=body or f"Notes of {tag}.",
        url=f"https://github.com/acme/app/releases/tag/{tag}",
        prerelease=prerelease,
    )


def _payload(tag: str, *, prerelease: bool = False, draft: bool = False) -> dict:
    return {
        "tag_name": tag,
        "name": tag,
        "body": f"Notes of {tag}.",
        "html_url": f"https://github.com/acme/app/releases/tag/{tag}",
        "prerelease": prerelease,
        "draft": draft,
    }


@pytest.mark.parametrize(
    ("tags", "version", "found"),
    [
        (["v1.3.0", "v1.2.0"], "1.2.0", 1),
        (["1.3.0", "1.2.0"], "v1.3.0", 0),
        (["v1.3.0", "v1.2.0"], "1.2.0-alpine", 1),
        (["v1.3.0-rc1", "v1.2.0"], "1.3.0-rc1", 0),
        (["v1.3.0", "v1.2.0"], "1.3.0-rc1", None),
        (["worker-v1.3.0", "app-v1.3.0"], "1.3.0", 1),
        (["v1.3.0"], "2.0.0", None),
    ],
)
def test_find_release(tags: list[str], version: str, found: int | None) -> None:
    """Tags with or without a v, image variants and monorepo prefixes match."""
    assert find_release([_release(tag) for tag in tags], version, "app") == found


@pytest.mark.parametrize(
    ("tag", "found"),
    [
        ("latest", 1),
        ("stable", 1),
        (None, 1),
        ("2", 1),
        ("1", 2),
        ("1.4", 3),
        ("1.4.2", None),
        ("16-alpine", None),
    ],
)
def test_newest_release(tag: str | None, found: int | None) -> None:
    """A moving tag follows the newest stable release of its line."""
    releases = [
        _release("v2.1.0-beta.1", prerelease=True),
        _release("v2.0.0"),
        _release("v1.5.0"),
        _release("v1.4.2"),
    ]
    assert newest_release(releases, tag) == found


async def test_tag_update_brings_the_releases_since_installed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An update skipping versions shows every stable release in between."""
    aioclient_mock.get(
        RELEASES,
        json=[
            _payload("v1.4.0"),
            _payload("v1.3.0"),
            _payload("v1.2.1-rc1", prerelease=True),
            _payload("v1.2.1", draft=True),
            _payload("v1.2.0"),
            _payload("v1.1.0"),
        ],
    )
    notes = await async_release_notes(
        async_get_clientsession(hass),
        "acme/app",
        ImageUpdate(image="app", tag="1.1.0", version="1.3.0", installed="1.1.0"),
    )
    assert notes is not None
    assert notes.url == "https://github.com/acme/app/releases/tag/v1.3.0"
    assert notes.notes == (
        "## v1.3.0\n\nNotes of v1.3.0.\n\n## v1.2.0\n\nNotes of v1.2.0."
    )


async def test_new_image_of_latest(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A new image naming no version gets the newest release, said as much."""
    aioclient_mock.get(
        RELEASES,
        json=[_payload("v2.0.0-rc1", prerelease=True), _payload("v1.4.0")],
    )
    notes = await async_release_notes(
        async_get_clientsession(hass),
        "acme/app",
        ImageUpdate(image="app", tag="latest", version=None, installed=None),
    )
    assert notes is not None
    assert notes.url == "https://github.com/acme/app/releases/tag/v1.4.0"
    assert notes.notes.startswith("*Arcane found a new image of the `latest` tag")
    assert notes.notes.endswith("## v1.4.0\n\nNotes of v1.4.0.")


async def test_new_image_of_latest_since_installed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The version label of the running image bounds the releases shown."""
    aioclient_mock.get(
        RELEASES, json=[_payload("v1.4.0"), _payload("v1.3.0"), _payload("v1.2.0")]
    )
    notes = await async_release_notes(
        async_get_clientsession(hass),
        "acme/app",
        ImageUpdate(image="app", tag="latest", version=None, installed="1.2.0"),
    )
    assert notes is not None
    assert "since the installed v1.2.0" in notes.notes
    assert "## v1.4.0" in notes.notes
    assert "## v1.3.0" in notes.notes
    assert "## v1.2.0" not in notes.notes


async def test_rebuild_of_the_installed_release(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A new image of the release already installed has nothing to show."""
    aioclient_mock.get(RELEASES, json=[_payload("v1.4.0"), _payload("v1.3.0")])
    assert (
        await async_release_notes(
            async_get_clientsession(hass),
            "acme/app",
            ImageUpdate(image="app", tag="latest", version=None, installed="1.4.0"),
        )
        is None
    )


async def test_old_version_is_asked_for_by_tag(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A release beyond the first page is fetched by its tag."""
    aioclient_mock.get(
        RELEASES, json=[_payload(f"v9.{minor}.0") for minor in range(30, 0, -1)]
    )
    aioclient_mock.get(f"{RELEASES}/tags/1.0.0", status=404)
    aioclient_mock.get(f"{RELEASES}/tags/v1.0.0", json=_payload("v1.0.0"))
    notes = await async_release_notes(
        async_get_clientsession(hass),
        "acme/app",
        ImageUpdate(image="app", tag="0.9.0", version="1.0.0", installed="0.9.0"),
    )
    assert notes is not None
    assert notes.notes == "## v1.0.0\n\nNotes of v1.0.0."


async def test_rate_limit_is_an_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """GitHub refusing is told apart from a repository without releases."""
    aioclient_mock.get(RELEASES, status=403)
    with pytest.raises(GitHubError):
        await async_release_notes(
            async_get_clientsession(hass),
            "acme/app",
            ImageUpdate(image="app", tag="latest", version=None, installed=None),
        )
