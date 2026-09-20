"""What this build is, recorded at build time and read back at runtime.

HARDENING P0.1 asks for a manifest so Diagnostics can answer "which build is
this?" without guessing, and so the core can notice that the executable beside
it is not the one the manifest describes.

The manifest is written into the frozen bundle by ``scripts/build_info.py``
during packaging. A development run has no manifest, which is not an error —
it is simply reported as a development build.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _bundle_dir() -> Path | None:
    """The folder holding the frozen executable, or None when not frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return None


def manifest_path() -> Path | None:
    bundle = _bundle_dir()
    return bundle / "build-info.json" if bundle else None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        # A PyInstaller executable is tens of megabytes; read it in chunks
        # rather than holding the whole thing to hash it.
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class BuildInfo:
    frozen: bool
    values: dict[str, Any] = field(default_factory=dict)
    #: None when there was nothing to check against.
    hash_matches: bool | None = None
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "frozen": self.frozen,
            "hashMatches": self.hash_matches,
            "warnings": list(self.warnings),
            **self.values,
        }


def describe() -> BuildInfo:
    """Read the manifest and re-verify the executable it describes."""
    path = manifest_path()
    if path is None:
        return BuildInfo(frozen=False, values={"build": "development"})
    if not path.is_file():
        return BuildInfo(
            frozen=True,
            values={"build": "unknown"},
            warnings=("this build has no build-info.json; it was not packaged by the release script",),
        )

    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return BuildInfo(frozen=True, values={"build": "unreadable"}, warnings=(f"build-info.json could not be read: {exc}",))

    warnings: list[str] = []
    matches: bool | None = None
    recorded = values.get("coreSha256")
    if recorded:
        try:
            actual = sha256(Path(sys.executable))
        except OSError as exc:
            warnings.append(f"could not hash the core to verify it: {exc}")
        else:
            matches = actual.lower() == str(recorded).lower()
            if not matches:
                # Not fatal: an antivirus product that rewrites binaries, or a
                # partially replaced install, both land here. Say it plainly
                # and let the user decide rather than refusing to start.
                warnings.append(
                    "the core does not match the hash recorded for this build; "
                    "it may have been modified or partially replaced"
                )
    return BuildInfo(frozen=True, values=values, hash_matches=matches, warnings=tuple(warnings))
