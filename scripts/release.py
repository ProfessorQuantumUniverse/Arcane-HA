"""Keep the git tag, the manifest version and the changelog in step.

    python scripts/release.py check v0.5.0    # tag matches manifest and changelog
    python scripts/release.py notes 0.5.0     # print that changelog section

The release workflow runs both. Running `check` by hand before tagging saves a failed
release run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "custom_components/arcane/manifest.json"
CHANGELOG = ROOT / "CHANGELOG.md"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
SECTION = re.compile(
    r"^## (?P<version>\d+\.\d+\.\d+).*?$(?P<body>.*?)(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)


def manifest_version() -> str:
    """Return the version HACS and Home Assistant show for the integration."""
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]


def changelog_sections() -> dict[str, str]:
    """Return the changelog body per version, newest first."""
    text = CHANGELOG.read_text(encoding="utf-8")
    return {m["version"]: m["body"].strip() for m in SECTION.finditer(text)}


def strip_tag(tag: str) -> str:
    """Return the version a tag names, with the leading v removed."""
    return tag[1:] if tag.startswith("v") else tag


def check(tag: str) -> int:
    """Fail unless the tag, the manifest and the top changelog entry agree."""
    version = strip_tag(tag)
    problems = []

    if not SEMVER.match(version):
        problems.append(f"tag {tag} is not vMAJOR.MINOR.PATCH")
    if version != manifest_version():
        problems.append(
            f"tag says {version}, manifest.json says {manifest_version()}"
        )

    sections = changelog_sections()
    if not sections:
        problems.append("CHANGELOG.md has no version headings")
    elif next(iter(sections)) != version:
        problems.append(
            f"CHANGELOG.md leads with {next(iter(sections))}, expected {version}"
        )

    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1

    print(f"{tag} is consistent")
    return 0


def notes(version: str) -> int:
    """Print the changelog section for a version, for use as release notes."""
    version = strip_tag(version)
    section = changelog_sections().get(version)
    if section is None:
        print(f"error: CHANGELOG.md has no {version} section", file=sys.stderr)
        return 1

    print(section)
    return 0


def main() -> int:
    """Run the subcommand named on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "notes"):
        step = sub.add_parser(name)
        step.add_argument("version", help="a tag like v0.5.0, or a bare 0.5.0")

    args = parser.parse_args()
    return check(args.version) if args.command == "check" else notes(args.version)


if __name__ == "__main__":
    raise SystemExit(main())
