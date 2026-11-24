"""Release notes of container images, looked up on GitHub.

Arcane 3 looks up the release notes of an image update itself, but only finds
them when it knows the version the update installs. A new image of a moving
tag such as ``latest`` often names no version, and Arcane 2 has no release
notes at all. For an image whose labels name its GitHub repository, the
integration then reads the releases of that repository on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Final

from aiohttp import ClientError, ClientSession, ClientTimeout
from yarl import URL

GITHUB_API: Final = URL("https://api.github.com")
_HEADERS: Final = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
_TIMEOUT: Final = ClientTimeout(total=15)

# One page of releases covers every update short of a very old installation.
RELEASES_PER_PAGE: Final = 30
# At most this many releases are combined into the notes of one update.
MAX_RELEASES: Final = 5

# What Docker accepts as a tag. Nothing else is put into a request path.
_DOCKER_TAG: Final = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
# A tag that follows a major or a minor version line, such as 2 or 1.4.
_VERSION_LINE: Final = re.compile(r"^v?\d+(?:\.\d+)?$")
# The suffix of a pre-release, rather than of an image variant like -alpine.
_PRERELEASE: Final = re.compile(r"^(?:alpha|beta|rc|pre|preview|dev|nightly)", re.I)


class GitHubError(Exception):
    """GitHub could not be asked, or did not answer usefully."""


@dataclass(frozen=True, slots=True)
class GitHubRelease:
    """A published release of a GitHub repository."""

    tag: str
    name: str
    body: str
    url: str
    prerelease: bool

    @classmethod
    def from_api(cls, payload: Any) -> GitHubRelease | None:
        """Build a release from the GitHub API, skipping drafts and junk."""
        if not isinstance(payload, dict) or payload.get("draft"):
            return None
        tag = payload.get("tag_name")
        url = payload.get("html_url")
        if not isinstance(tag, str) or not tag or not isinstance(url, str):
            return None
        name = payload.get("name")
        body = payload.get("body")
        return cls(
            tag=tag,
            name=name.strip() if isinstance(name, str) and name.strip() else tag,
            body=body.strip() if isinstance(body, str) else "",
            url=url,
            prerelease=bool(payload.get("prerelease")),
        )


@dataclass(frozen=True, slots=True)
class ReleaseNotes:
    """Release notes of an update and the release page they come from."""

    notes: str
    url: str


async def _get(session: ClientSession, url: URL) -> Any:
    """Return the decoded reply of a GitHub API call, None for a 404."""
    try:
        async with session.get(url, headers=_HEADERS, timeout=_TIMEOUT) as response:
            if response.status == HTTPStatus.NOT_FOUND:
                return None
            if response.status != HTTPStatus.OK:
                # 403 and 429 are GitHub's limit for anonymous requests.
                raise GitHubError(f"GitHub answered {response.status} for {url}")
            return await response.json()
    except (ClientError, TimeoutError, ValueError) as err:
        raise GitHubError(f"Could not read {url}: {err}") from err


def _repository_url(repository: str, *segments: str) -> URL:
    """Return the API URL of a repository, given as ``owner/repo``."""
    owner, _, repo = repository.partition("/")
    return GITHUB_API.joinpath("repos", owner, repo, *segments)


async def async_get_releases(
    session: ClientSession, repository: str
) -> list[GitHubRelease]:
    """Return the newest published releases of a repository, newest first."""
    payload = await _get(
        session,
        _repository_url(repository, "releases").with_query(per_page=RELEASES_PER_PAGE),
    )
    if not isinstance(payload, list):
        return []
    return [
        release
        for item in payload
        if (release := GitHubRelease.from_api(item)) is not None
    ]


async def async_get_release(
    session: ClientSession, repository: str, tag: str
) -> GitHubRelease | None:
    """Return the release of a tag, or None if the tag has none."""
    if not _DOCKER_TAG.match(tag):
        return None
    return GitHubRelease.from_api(
        await _get(session, _repository_url(repository, "releases", "tags", tag))
    )


def _split_prefix(tag: str) -> tuple[str, str]:
    """Split a release tag into what comes before the version and the version."""
    index = next((i for i, char in enumerate(tag) if char.isdigit()), len(tag))
    return tag[:index], tag[index:]


def _tag_candidates(version: str) -> list[str]:
    """Return the release tags a version may be published under."""
    base, _, suffix = version.partition("-")
    # An image variant such as 1.2.3-alpine is released as 1.2.3.
    values = [version] if not suffix or _PRERELEASE.match(suffix) else [version, base]
    candidates: list[str] = []
    for value in values:
        bare = value.removeprefix("v")
        for candidate in (value, f"v{bare}", bare):
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def find_release(releases: list[GitHubRelease], version: str, image: str) -> int | None:
    """Return the position of the release of a version, if it is listed.

    A monorepo prefixes its tags with the component, like ``app-v1.2.3``; of
    several releases carrying the version, the one naming the image wins.
    """
    candidates = _tag_candidates(version)
    lowered = [release.tag.lower() for release in releases]
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered.index(candidate.lower())

    image = image.lower()
    for candidate in candidates:
        if not (core := _split_prefix(candidate)[1]):
            continue
        matches = [
            index
            for index, release in enumerate(releases)
            if _split_prefix(release.tag)[1].lower() == core.lower()
        ]
        if matches:
            return next(
                (
                    index
                    for index in matches
                    if image and image in _split_prefix(releases[index].tag)[0].lower()
                ),
                matches[0],
            )
    return None


def newest_release(releases: list[GitHubRelease], tag: str | None) -> int | None:
    """Return the position of the newest release a moving tag points at.

    A tag without a version, such as ``latest`` or ``stable``, follows the
    newest stable release; ``2`` or ``1.4`` follow the newest release of that
    version line. Any other tag names a fixed version, so a new image of it is
    a rebuild that no release describes.
    """
    if tag is None or not any(char.isdigit() for char in tag):
        line = None
    elif _VERSION_LINE.match(tag):
        line = tag.removeprefix("v")
    else:
        return None
    for index, release in enumerate(releases):
        if release.prerelease:
            continue
        version = _split_prefix(release.tag)[1]
        if line is None or version == line or version.startswith(f"{line}."):
            return index
    return None


def _format(releases: list[GitHubRelease], intro: str | None) -> str:
    """Return the notes of one or more releases as Markdown."""
    parts = [intro] if intro else []
    for release in releases:
        body = release.body or f"[{release.name}]({release.url})"
        parts.append(f"## {release.name}\n\n{body}")
    return "\n\n".join(parts)


@dataclass(frozen=True, slots=True)
class ImageUpdate:
    """The image update release notes are looked up for.

    ``image`` is the bare image name, such as ``home-assistant``. ``version``
    is what the update installs, if that is known, and ``installed`` the
    version the container runs now.
    """

    image: str
    tag: str | None
    version: str | None
    installed: str | None


async def async_release_notes(
    session: ClientSession, repository: str, update: ImageUpdate
) -> ReleaseNotes | None:
    """Return the notes of the releases an image update brings.

    Without a version the update is a new image of the moving tag, which is
    assumed to carry the newest release that tag follows. When the release of
    the installed version is listed as well, every release in between is
    included, so an update skipping a few versions shows all of them.
    """
    image, tag, version, installed = (
        update.image,
        update.tag,
        update.version,
        update.installed,
    )
    releases = await async_get_releases(session, repository)
    intro: str | None = None
    if version:
        target = find_release(releases, version, image)
        if target is None:
            if len(releases) < RELEASES_PER_PAGE:
                # Every release is listed already, so the version has none.
                return None
            # An old version beyond the first page is asked for directly.
            for candidate in _tag_candidates(version):
                if release := await async_get_release(session, repository, candidate):
                    return ReleaseNotes(_format([release], None), release.url)
            return None
    else:
        target = newest_release(releases, tag)
        if target is None:
            return None
        intro = (
            f"*Arcane found a new image of the `{tag or 'latest'}` tag, which "
            f"names no version. These are the notes of the newest release on "
            f"GitHub it follows.*"
        )

    picked = [releases[target]]
    start = find_release(releases, installed, image) if installed else None
    if start is not None and start <= target and not version:
        # The newest release is installed already, so the new image is a
        # rebuild of it and no release describes what changed.
        return None
    if start is not None and start > target:
        picked.extend(
            release
            for release in releases[target + 1 : start]
            if not release.prerelease
        )
        picked = picked[:MAX_RELEASES]
        if intro:
            intro = (
                f"*Arcane found a new image of the `{tag or 'latest'}` tag. "
                f"These are the releases on GitHub since the installed "
                f"{releases[start].name}.*"
            )
    return ReleaseNotes(_format(picked, intro), releases[target].url)
