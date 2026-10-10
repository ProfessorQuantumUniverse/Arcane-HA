"""Tests for the Arcane data models."""

from __future__ import annotations

import pytest

from custom_components.arcane.models import (
    NEWER_IMAGE,
    ArcaneContainer,
    image_name,
)


def _container(image: str, update_info: dict | None = None) -> ArcaneContainer:
    """Build a container running an image with the given update check."""
    return ArcaneContainer.from_api(
        {"id": "abc", "names": ["/app"], "image": image, "updateInfo": update_info}
    )


def test_tag_update_reports_both_versions() -> None:
    """A newer tag is shown as the newer version."""
    container = _container(
        "nginx:1.25",
        {"hasUpdate": True, "currentVersion": "1.25", "latestVersion": "1.27"},
    )
    assert container.installed_version == "1.25"
    assert container.latest_version == "1.27"


def test_digest_update_of_a_moving_tag_uses_the_digests() -> None:
    """A new image under the same tag must still read as an update."""
    container = _container(
        "ghcr.io/homarr-labs/homarr:latest",
        {
            "hasUpdate": True,
            "updateType": "digest",
            "currentVersion": "latest",
            "latestVersion": "latest",
            "currentDigest": "sha256:f0fb462299af9e1c0000000000000000",
            "latestDigest": "sha256:d60120a045360000000000000000000",
        },
    )
    assert container.update_available
    assert container.installed_version == "f0fb462299af"
    assert container.latest_version == "d60120a04536"


def test_digest_update_without_a_latest_version() -> None:
    """Arcane may leave the newest version out of a digest update."""
    container = _container(
        "searxng/searxng",
        {
            "hasUpdate": True,
            "currentDigest": "searxng/searxng@sha256:5286edb357820000",
            "latestDigest": "searxng/searxng@sha256:a07a5cd2da2c0000",
        },
    )
    assert container.installed_version == "5286edb35782"
    assert container.latest_version == "a07a5cd2da2c"


def test_update_without_versions_or_digests_still_differs() -> None:
    """An update Arcane cannot describe must not collapse into no update."""
    container = _container("traefik/whoami:latest", {"hasUpdate": True})
    assert container.installed_version == "latest"
    assert container.latest_version == f"latest ({NEWER_IMAGE})"


def test_newer_version_arcane_does_not_offer_is_no_update() -> None:
    """The update entity agrees with Arcane's own verdict."""
    container = _container(
        "nginx:1.25",
        {"hasUpdate": False, "currentVersion": "1.25", "latestVersion": "1.27"},
    )
    assert container.latest_version == container.installed_version == "1.25"


def test_unchecked_container_has_no_update() -> None:
    """A container Arcane has not checked yet reports its tag twice."""
    container = _container("redis:7")
    assert not container.update_available
    assert container.installed_version == container.latest_version == "7"


@pytest.mark.parametrize(
    ("image", "name", "tag"),
    [
        ("nginx", "nginx", None),
        ("nginx:1.25", "nginx", "1.25"),
        ("registry.local:5000/team/app", "registry.local:5000/team/app", None),
        ("registry.local:5000/team/app:2", "registry.local:5000/team/app", "2"),
        ("nginx@sha256:0123456789abcdef", "nginx", None),
        ("nginx:1.25@sha256:0123456789abcdef", "nginx", "1.25"),
    ],
)
def test_image_references_are_split(image: str, name: str, tag: str | None) -> None:
    """Registry ports and pinned digests are not mistaken for tags."""
    assert image_name(image) == name
    assert _container(image).installed_version == tag
