"""Checks on the integration metadata."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parent.parent
MANIFEST = json.loads((ROOT / "custom_components/arcane/manifest.json").read_text())
CHANGELOG = (ROOT / "CHANGELOG.md").read_text()

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
HEADING = re.compile(r"^## (\d+\.\d+\.\d+)", re.MULTILINE)


def load_release_script() -> ModuleType:
    """Import scripts/release.py, which is not on the path as a package."""
    spec = importlib.util.spec_from_file_location(
        "release_script", ROOT / "scripts/release.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_version_is_semver() -> None:
    """HACS shows this version, so it has to be a version."""
    assert SEMVER.match(MANIFEST["version"])


def test_changelog_leads_with_the_manifest_version() -> None:
    """The release notes and the shipped version must not drift apart."""
    versions = HEADING.findall(CHANGELOG)

    assert versions, "the changelog has no version headings"
    assert versions[0] == MANIFEST["version"]


def test_changelog_versions_descend() -> None:
    """Newest first, so the top heading is the current version."""
    versions = [tuple(int(p) for p in v.split(".")) for v in HEADING.findall(CHANGELOG)]

    assert versions == sorted(versions, reverse=True)
    assert len(versions) == len(set(versions))


def test_brand_assets_ship_with_the_integration() -> None:
    """Without these Home Assistant falls back to a generic placeholder."""
    brand = ROOT / "custom_components/arcane/brand"

    for name in ("icon.png", "icon@2x.png", "logo.png", "logo@2x.png"):
        assert (brand / name).is_file(), f"{name} is missing from {brand}"


def test_release_script_accepts_the_current_version() -> None:
    """Tagging the version in the manifest has to pass the release check."""
    release = load_release_script()

    assert release.check(f"v{MANIFEST['version']}") == 0


def test_release_script_rejects_a_mismatched_tag() -> None:
    """A tag that does not match the manifest must stop the release."""
    release = load_release_script()

    assert release.check("v99.99.99") == 1


def test_release_notes_exist_for_the_current_version() -> None:
    """The release body comes from the changelog, so it cannot be empty."""
    release = load_release_script()

    assert release.changelog_sections()[MANIFEST["version"]]
