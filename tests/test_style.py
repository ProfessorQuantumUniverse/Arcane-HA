"""House style checks that are easier to enforce than to remember."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Long dashes read as machine written and travel badly through terminals, YAML and
# copy-paste, so the whole repository sticks to plain hyphens, commas and full stops.
# They are spelled as code points here so that this file passes its own check.
LONG_DASHES = {
    chr(0x2012): "figure dash",
    chr(0x2013): "en dash",
    chr(0x2014): "em dash",
    chr(0x2015): "horizontal bar",
    chr(0xFF0D): "fullwidth hyphen",
}

TEXT_SUFFIXES = {
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".svg",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_NAMES = {"LICENSE", ".gitignore"}


def tracked_text_files() -> list[Path]:
    """Return every text file git knows about."""
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    paths = [ROOT / name for name in listing.stdout.split("\0") if name]
    return [
        path
        for path in paths
        if path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES
    ]


def test_there_are_files_to_check() -> None:
    """A broken listing would make the dash check pass without reading anything."""
    assert len(tracked_text_files()) > 20


def test_no_long_dashes() -> None:
    """Plain hyphens only, everywhere."""
    found = []
    for path in tracked_text_files():
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            for dash, name in LONG_DASHES.items():
                if dash in line:
                    relative = path.relative_to(ROOT).as_posix()
                    found.append(f"{relative}:{number} has a {name}: {line.strip()}")

    assert not found, "\n".join(found)
