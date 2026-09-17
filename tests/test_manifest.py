"""Checks on the integration metadata."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
MANIFEST = json.loads((ROOT / "custom_components/arcane/manifest.json").read_text())
CHANGELOG = (ROOT / "CHANGELOG.md").read_text()

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
HEADING = re.compile(r"^## (\d+\.\d+\.\d+)", re.MULTILINE)


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
