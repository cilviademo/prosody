"""Job manifests, and the startup sweep that finds interrupted builds.

HARDENING P0.4. A build that is interrupted — the machine sleeps, FL wedges,
the user closes Prosody mid-render — leaves an export folder with some of its
contents and no explanation. Without a manifest there is no way to tell that
folder apart from a finished build that simply produced less.

``job.json`` is written when a build starts and updated as each stage
completes, so an interrupted folder is self-describing: which source, which
hash, what was asked for, what finished and when.

On startup the workspace is swept for two things: manifests that never reached
``finished``, and stray ``.partial`` files. Both are offered to the user rather
than cleaned up silently, because a half-built folder may contain the only copy
of something they want.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST = "job.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobManifest:
    """The record of one build, written as it happens."""

    out_dir: Path
    source_path: str
    source_hash: str
    operation: str
    options: dict[str, Any] = field(default_factory=dict)
    working_copy: str | None = None
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    stages: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[dict[str, str]] = field(default_factory=list)
    validation_level: str | None = None

    @property
    def path(self) -> Path:
        return self.out_dir / MANIFEST

    def as_dict(self) -> dict[str, Any]:
        return {
            "sourcePath": self.source_path,
            "sourceHash": self.source_hash,
            "operation": self.operation,
            "options": self.options,
            "workingCopy": self.working_copy,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "stages": self.stages,
            "outputs": self.outputs,
            "validationLevel": self.validation_level,
        }

    def write(self) -> None:
        """Persist the manifest. Never raises: it is a record, not the work."""
        try:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.as_dict(), indent=2) + "\n", encoding="utf-8"
            )
        except OSError:
            pass

    def stage(self, name: str, status: str, detail: str = "") -> None:
        self.stages.append(
            {"name": name, "status": status, "detail": detail, "at": _now()}
        )
        self.write()

    def finish(self, validation_level: str | None = None) -> None:
        self.finished_at = _now()
        self.validation_level = validation_level
        self.write()


@dataclass(frozen=True)
class Interrupted:
    """An export folder whose build never reported finishing."""

    out_dir: Path
    source_path: str
    started_at: str
    last_stage: str
    stage_count: int
    partials: tuple[Path, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "outDir": str(self.out_dir),
            "name": self.out_dir.name,
            "sourcePath": self.source_path,
            "sourceExists": Path(self.source_path).is_file() if self.source_path else False,
            "startedAt": self.started_at,
            "lastStage": self.last_stage,
            "stageCount": self.stage_count,
            "partials": [str(p) for p in self.partials],
        }


def scan(export_root: Path) -> list[Interrupted]:
    """Every export folder whose build did not finish, newest first."""
    root = Path(export_root)
    if not root.is_dir():
        return []

    found: list[Interrupted] = []
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        manifest = folder / MANIFEST
        partials = tuple(sorted(p for p in folder.rglob("*.partial") if p.is_file()))

        if not manifest.is_file():
            # No manifest at all: only interesting if something is half-written.
            # A folder from a build that predates manifests is not a failure.
            if partials:
                found.append(Interrupted(
                    folder, "", "", "unknown — this build wrote no manifest", 0, partials,
                ))
            continue

        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            found.append(Interrupted(folder, "", "", "its manifest is unreadable", 0, partials))
            continue

        if data.get("finishedAt"):
            # Finished. A stray .partial here is still worth surfacing.
            if partials:
                found.append(Interrupted(
                    folder, str(data.get("sourcePath", "")), str(data.get("startedAt", "")),
                    "finished, but left a partial file", len(data.get("stages", [])), partials,
                ))
            continue

        stages = data.get("stages") or []
        last = stages[-1]["name"] if stages else "nothing started"
        found.append(Interrupted(
            folder, str(data.get("sourcePath", "")), str(data.get("startedAt", "")),
            last, len(stages), partials,
        ))

    return sorted(found, key=lambda i: i.started_at, reverse=True)


def discard(out_dir: Path, export_root: Path) -> None:
    """Delete an interrupted export folder.

    Refuses anything outside the export root. Deleting a folder is the one
    action here that cannot be undone, so it does not take the caller's word
    for where the folder is.
    """
    out_dir = Path(out_dir).resolve()
    root = Path(export_root).resolve()
    if not out_dir.is_dir():
        return
    # Equality first: the export root is technically "not inside itself", and
    # reporting that would be a confusing way to refuse the obvious mistake.
    if out_dir == root:
        raise ValueError("refusing to delete the export root itself")
    if root not in out_dir.parents:
        raise ValueError(f"{out_dir} is not inside {root}; refusing to delete it")
    shutil.rmtree(out_dir)


def clear_partials(export_root: Path) -> list[Path]:
    """Remove stray ``.partial`` files, leaving every finished file alone."""
    removed: list[Path] = []
    for path in sorted(Path(export_root).rglob("*.partial")):
        if not path.is_file():
            continue
        try:
            path.unlink()
        except OSError:
            continue
        removed.append(path)
    return removed
