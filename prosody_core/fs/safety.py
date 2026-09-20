"""Filesystem safety: hashing, corpus immutability, and output paths.

Two rules from SPEC.md section 2 are enforced here rather than by convention:

1. Source projects are never modified. Every command hashes what it read and
   re-verifies before it returns; a changed hash fails the run.
2. Everything written goes under ``out/<slug>/``. :func:`output_dir` is the only
   sanctioned way to name a destination.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

_CHUNK = 1 << 20
_SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")


class CorpusMutated(RuntimeError):
    """A source file changed between the start and end of a run."""


def sha256_file(path: Path) -> str:
    """Stream the file so a 500 MB project does not become 500 MB of RAM."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(name: str) -> str:
    """Filesystem-safe, stable slug for an output folder name."""
    slug = _SLUG_UNSAFE.sub("-", name.strip().lower()).strip("-")
    return slug or "untitled"


def find_flps(root: Path) -> list[Path]:
    """Every .flp under ``root``, sorted for deterministic ordering."""
    root = Path(root)
    if root.is_file():
        return [root] if root.suffix.lower() == ".flp" else []
    return sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".flp"
    )


def output_dir(out_root: Path, source: Path, *, create: bool = True) -> Path:
    """``out/<slug>/`` for one source project. The only sanctioned write root."""
    target = Path(out_root) / slugify(source.stem)
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def versioned_path(directory: Path, stem: str, suffix: str) -> Path:
    """Next free ``STEM_V001.suffix``. Never returns an existing path.

    Generated projects are versioned rather than overwritten (SPEC.md section 2;
    product brief section 1, "never overwrite generated projects").
    """
    for n in range(1, 1000):
        candidate = Path(directory) / f"{stem}_V{n:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"exhausted 999 versions for {stem}{suffix} in {directory}")


@dataclass
class ReadOnlyCorpus:
    """Hashes a set of source files and proves afterwards that none changed.

    Usage::

        guard = ReadOnlyCorpus.snapshot(paths)
        ...                       # do work
        guard.verify()            # raises CorpusMutated on any change
    """

    hashes: dict[Path, str] = field(default_factory=dict)

    @classmethod
    def snapshot(cls, paths: Iterable[Path]) -> ReadOnlyCorpus:
        return cls({Path(p): sha256_file(Path(p)) for p in paths})

    def __iter__(self) -> Iterator[Path]:
        return iter(self.hashes)

    def __len__(self) -> int:
        return len(self.hashes)

    def digest(self, path: Path) -> str:
        return self.hashes[Path(path)]

    def changed(self) -> list[Path]:
        """Paths whose contents differ from the snapshot, or that vanished."""
        out: list[Path] = []
        for path, expected in self.hashes.items():
            if not path.is_file() or sha256_file(path) != expected:
                out.append(path)
        return sorted(out)

    def verify(self) -> None:
        if mutated := self.changed():
            listing = ", ".join(str(p) for p in mutated)
            raise CorpusMutated(f"source files changed during the run: {listing}")
