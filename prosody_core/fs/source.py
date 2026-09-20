"""The only code allowed to open a source project, and the only code allowed
to replace a file on disk.

HARDENING P0.3 and P0.4. Both rules exist because "never modify the user's
original" and "never leave half a file behind" cannot be kept by everyone
remembering to keep them. They are kept here, once, and every writer goes
through :func:`atomic_write`.

Three distinct protections, because they fail differently:

* **Read-only opening.** A source is opened ``"rb"`` and copied. Nothing
  downstream ever holds a writable handle to it.
* **Destination identity.** A destination is rejected when it *is* the source.
  Comparing paths is not enough on Windows, where a hard link, a junction, a
  substituted drive or simply a different spelling of the same path all reach
  the same bytes under a different name. ``st_dev``/``st_ino`` compare the file
  itself, and Python populates both on Windows.
* **Atomic replacement.** Write a sibling temporary file, flush it, fsync it,
  then ``os.replace``. A reader sees the old file or the new one, never a
  partial one, and a crash mid-write cannot destroy a good previous version.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from prosody_core.fs.safety import sha256_file


class SourceWouldBeModified(RuntimeError):
    """A write was aimed at, or into, the user's original project."""


class SourceChanged(RuntimeError):
    """A source file changed underneath a run."""


def file_identity(path: Path) -> tuple[int, int] | None:
    """``(device, inode)`` — what actually identifies a file to the OS.

    On Windows these are the volume serial number and the file index, so two
    different spellings of one file, or a hard link to it, compare equal.
    Returns None when the file does not exist, which is the normal case for a
    destination and is never treated as a match.
    """
    try:
        info = Path(path).stat()
    except OSError:
        return None
    if info.st_ino == 0:
        # Some filesystems do not report a usable index; fall back to the
        # resolved path rather than silently treating everything as distinct.
        return None
    return (info.st_dev, info.st_ino)


def is_same_file(left: Path, right: Path) -> bool:
    left_id, right_id = file_identity(left), file_identity(right)
    if left_id is not None and right_id is not None:
        return left_id == right_id
    # No usable identity: compare fully resolved paths, case-insensitively on
    # Windows, where two spellings of one path are the same file.
    try:
        a, b = Path(left).resolve(), Path(right).resolve()
    except OSError:
        return False
    if os.name == "nt":
        return str(a).lower() == str(b).lower()
    return a == b


def assert_not_the_source(destination: Path, source: Path) -> None:
    """Refuse a destination that is, or lives inside, the source project."""
    destination, source = Path(destination), Path(source)
    if is_same_file(destination, source):
        raise SourceWouldBeModified(
            f"refusing to write over the source project at {source}"
        )
    # Writing *into* the folder a source sits in is allowed — the user may
    # legitimately choose it as an export location — but never over the file.
    if destination.name == source.name and is_same_file(
        destination.parent, source.parent
    ):
        raise SourceWouldBeModified(
            f"refusing to write {destination.name} beside the source of the same name"
        )


@contextmanager
def open_source(path: Path) -> Iterator[Path]:
    """Yield a path safe to parse, with the original verified either side.

    The hash is taken before anything reads the file and checked again on the
    way out, so a source edited in FL Studio mid-run is caught rather than
    half-used.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist")
    before = sha256_file(path)
    try:
        yield path
    finally:
        after = sha256_file(path) if path.is_file() else None
        if after != before:
            raise SourceChanged(
                f"{path} changed while Prosody was reading it "
                f"({before[:12]} -> {after[:12] if after else 'missing'}). "
                "Nothing was written."
            )


@dataclass(frozen=True)
class WorkingCopy:
    """A private copy of a source, with the hash it was taken from."""

    path: Path
    source: Path
    source_hash: str


def working_copy(source: Path, cache_root: Path, job_id: str | None = None) -> WorkingCopy:
    """Copy a source into the cache and work from that (HARDENING P0.3).

    Every later stage reads the copy, so no amount of downstream carelessness
    can reach the original — and if FL Studio has the original open, the copy
    is still a stable set of bytes to parse.
    """
    source = Path(source)
    digest = sha256_file(source)
    job = job_id or uuid.uuid4().hex[:12]
    folder = Path(cache_root) / "jobs" / job
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "source.flp"
    shutil.copy2(source, target)
    if sha256_file(target) != digest:
        raise SourceChanged(f"{source} changed while it was being copied")
    return WorkingCopy(path=target, source=source, source_hash=digest)


@contextmanager
def temporary_copy(source: Path, cache_root: Path) -> Iterator[WorkingCopy]:
    """A working copy that is removed when the caller is done with it.

    Inspecting a project and previewing an arrangement both need a copy to
    read, but neither produces output, so neither should leave anything in the
    cache. A build keeps its copy, because a build has a job folder that
    outlives the call.
    """
    copy = working_copy(source, cache_root)
    try:
        yield copy
    finally:
        jobs = copy.path.parent.parent
        shutil.rmtree(copy.path.parent, ignore_errors=True)
        # Leave no trace at all, so "a preview writes nothing" stays literally
        # true and a machine that only ever previews grows no empty folders.
        # It is expected to fail whenever a build's job folder is still there.
        with suppress(OSError):
            jobs.rmdir()


def atomic_write(destination: Path, data: bytes, *, source: Path | None = None) -> Path:
    """Write ``data`` to ``destination`` without ever leaving a partial file.

    The temporary file is created beside the destination, because ``os.replace``
    is only atomic within one volume — writing it in the cache and moving it to
    another drive would be a copy, and a copy can be interrupted.

    A destination locked by another program (FL Studio has it open, Explorer is
    previewing it) raises ``PermissionError`` from ``os.replace``. That is left
    to the caller, which knows whether the right answer is the next version
    number; the locked file is never deleted to make room.
    """
    destination = Path(destination)
    if source is not None:
        assert_not_the_source(destination, source)
    destination.parent.mkdir(parents=True, exist_ok=True)

    partial = destination.with_name(f"{destination.name}.{uuid.uuid4().hex[:8]}.partial")
    try:
        with open(partial, "wb") as handle:
            handle.write(data)
            handle.flush()
            # Without fsync the bytes may still be in the OS cache when the
            # rename lands, so a power loss can leave a named, empty file.
            os.fsync(handle.fileno())
        os.replace(partial, destination)
    except BaseException:
        # Never leave a .partial behind for the stale-file scan to puzzle over.
        with suppress(OSError):
            partial.unlink(missing_ok=True)
        raise
    return destination


def atomic_write_versioned(
    directory: Path,
    stem: str,
    suffix: str,
    data: bytes,
    *,
    source: Path | None = None,
    limit: int = 99,
) -> Path:
    """Write ``<stem>.<suffix>``, stepping to the next version if it is locked.

    FL Studio holding a previous export open is the ordinary case, not an
    error. Stepping past it keeps the build moving and, crucially, never
    deletes the file the user still has open.
    """
    attempt = 0
    name = f"{stem}{suffix}"
    while True:
        try:
            return atomic_write(directory / name, data, source=source)
        except PermissionError:
            attempt += 1
            if attempt > limit:
                raise
            name = f"{stem}_V{attempt + 1:03d}{suffix}"


def stale_partials(root: Path) -> list[Path]:
    """Every leftover ``.partial`` under ``root``, for the startup sweep."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.partial") if p.is_file())
