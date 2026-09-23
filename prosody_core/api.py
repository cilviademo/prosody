"""Line-delimited JSON API for the Prosody desktop shell.

One process per call. Progress is streamed as NDJSON so the UI can show live
stage status, and the last line is always the final envelope:

    {"event": "progress", "stage": "...", "status": "...", "detail": "..."}
    {"event": "result",   "ok": true,  "data": {...}}
    {"event": "result",   "ok": false, "error": "...", "detail": "..."}

Errors are returned as data, never as a stack trace on stderr, so the UI can
always show the user something meaningful.
"""

from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prosody_core import build as build_module
from prosody_core import buildinfo, jobs
from prosody_core.ai.planner import PROVIDERS, PlanRequest, get_planner
from prosody_core.arrange import profiles
from prosody_core.arrange.planner import PlanningError, pattern_roles
from prosody_core.classify.signals import analyse_project
from prosody_core.env import describe
from prosody_core.extract import render_fl
from prosody_core.extract import stems as stems_module
from prosody_core.fs.safety import sha256_file
from prosody_core.fs.source import WorkingCopy, cloud_sync_provider, temporary_copy, working_copy
from prosody_core.health import systemcheck
from prosody_core.health.check import check_project, classify_state, human_status
from prosody_core.index import db
from prosody_core.model.roles import Role
from prosody_core.model.schemas import (
    Analysis,
    BeatProject,
    HealthStatus,
    LibraryEntry,
    PermissionLevel,
)
from prosody_core.parse.adapter import ParseError
from prosody_core.parse.pyflp_backend import PyFLPBackend
from prosody_core.workspace import Workspace

Handler = Callable[[dict[str, Any], Workspace], dict[str, Any]]

#: Roles shown as a checklist on the project screen, in this order.
DISPLAY_ROLES: tuple[Role, ...] = (
    Role.MELODY, Role.CHORDS, Role.BASS, Role.KICK, Role.SNARE,
    Role.HATS, Role.PERC, Role.COUNTER, Role.VOCAL, Role.FX,
)

_PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
#: Krumhansl-style major/minor profiles, normalised. Enough for a labelled guess
#: that the UI marks as approximate; not a claim of musicological rigour.
_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)


def _stdout_sink(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


#: Where emitted envelopes go. The stdio server swaps this so it can stamp a
#: request id onto every line; tests swap it to capture. Handlers always call
#: :func:`emit` and never write to stdout themselves.
_sink: Callable[[dict[str, Any]], None] = _stdout_sink


@contextmanager
def sink(target: Callable[[dict[str, Any]], None]) -> Iterator[None]:
    """Route emitted envelopes to ``target`` for the duration of the block."""
    global _sink
    previous = _sink
    _sink = target
    try:
        yield
    finally:
        _sink = previous


def emit(payload: dict[str, Any]) -> None:
    _sink(payload)


def guess_key(project: BeatProject) -> tuple[str | None, float]:
    """Pitch-class-histogram key guess over pitched material only."""
    histogram = [0.0] * 12
    total = 0
    for pattern in project.patterns:
        for note in pattern.notes:
            histogram[note.key % 12] += max(note.length, 1)
            total += 1
    if total < 8 or not any(histogram):
        return None, 0.0

    mean = sum(histogram) / 12
    centred = [v - mean for v in histogram]

    def correlate(profile: tuple[float, ...], shift: int) -> float:
        pmean = sum(profile) / 12
        pc = [profile[(i - shift) % 12] - pmean for i in range(12)]
        num = sum(a * b for a, b in zip(centred, pc, strict=True))
        den = (sum(a * a for a in centred) ** 0.5) * (sum(b * b for b in pc) ** 0.5)
        return num / den if den else 0.0

    best: tuple[float, str] = (-2.0, "")
    for shift in range(12):
        for profile, mode in ((_MAJOR, "Major"), (_MINOR, "Minor")):
            score = correlate(profile, shift)
            if score > best[0]:
                best = (score, f"{_PITCH_CLASSES[shift]} {mode}")
    confidence = max(0.0, min(1.0, (best[0] + 1) / 2))
    return (best[1] or None), round(confidence, 2)


def _project_payload(path: Path, workspace: Workspace) -> dict[str, Any]:
    backend = PyFLPBackend()
    # Read a copy, never the user's file, and do not leave it behind: an
    # inspection produces no output (HARDENING P0.3).
    with temporary_copy(path, workspace.cache) as copy:
        project = _parse_original(backend, copy.path, path)
        # Needs the file: write_compatibility rewrites it in memory.
        health = check_project(project, source=copy.path)
    analysis = analyse_project(project, classify_state(project))
    key, key_confidence = guess_key(project)

    present = {a.role for a in analysis.roles if a.is_confident}
    # Roles detected below the confidence threshold. The arrangement engine does
    # use them (weighted by confidence), so the UI must not show them as absent -
    # that would under-report what the product will actually do.
    likely = {
        a.role for a in analysis.roles
        if not a.is_confident and a.role is not Role.UNKNOWN and a.confidence > 0
    } - present
    uncertain = [
        {
            "channel": a.channel,
            "name": next(
                (c.name for c in project.channels if c.index == a.channel), None
            ),
            "role": a.role.value,
            "confidence": a.confidence,
            "sources": list(a.sources),
        }
        for a in analysis.roles if not a.is_confident
    ]

    patterns = [
        {
            "pattern": p.pattern, "name": p.name, "role": p.role.value,
            "notes": p.note_count,
        }
        for p in pattern_roles(project, analysis)
    ]

    _remember(workspace, path, project, health.status, key, status="Analyzed")

    return {
        "id": project.id,
        "name": path.name,
        "path": str(path),
        "hash": project.id,
        "tempo": project.tempo,
        "key": key,
        "keyConfidence": key_confidence,
        "lengthBars": round(project.length_bars, 2),
        "durationSeconds": project.duration_seconds,
        "timeSignature": list(project.time_signature),
        "flVersion": project.fl_version,
        "backend": project.backend,
        "state": analysis.state.value,
        "counts": {
            "patterns": len(project.patterns),
            "channels": len(project.channels),
            "plugins": len(project.plugins),
            "mixerTracks": len(project.mixer),
            "notes": project.note_count,
            "playlistClips": sum(len(a.clips) for a in project.arrangements),
            "samplesMissing": health.samples_missing,
        },
        "roles": [
            {
                "role": r.value,
                "present": r in present,
                "likely": r in likely,
                "label": r.value.replace("_", " ").title(),
            }
            for r in DISPLAY_ROLES
        ],
        "uncertain": uncertain,
        "patternRoles": patterns,
        "health": {
            "status": health.status.value,
            "label": human_status(health.status),
            "checks": [
                {"name": c.name, "ok": c.ok, "detail": c.detail}
                for c in health.checks
            ],
            "missing": [a.identifier for a in health.missing_assets],
        },
        "canArrange": bool(patterns),
        # An audio-clip session has playlist clips but no patterns; the UI
        # says so instead of implying the file is at fault (P1.6).
        "audioClipCount": sum(
            1 for a in project.arrangements for c in a.clips if c.kind == "channel"
        ),
        "missingSamples": [a.identifier for a in health.missing_assets],
        "warnings": [
            {"code": w.code, "message": w.message, "severity": w.severity.value}
            for w in project.parse_warnings
        ],
    }


def _remember(
    workspace: Workspace,
    path: Path,
    project: BeatProject,
    health: HealthStatus,
    key: str | None,
    *,
    status: str,
    genre: str | None = None,
    out_dir: str | None = None,
) -> LibraryEntry:
    """Record a project in the library. Every write path goes through here, so
    a build can never reference a project row that was never created."""
    entry = LibraryEntry(
        project_id=project.id,
        name=path.stem,
        source_path=str(path),
        tempo=project.tempo,
        key=key,
        length_bars=round(project.length_bars, 2),
        genre=genre,
        status=status,
        health=health,
        out_dir=out_dir,
    )
    db.migrate(workspace.db_path)
    db.upsert_project(workspace.db_path, entry)
    return entry


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #


def _exe_fingerprint(path: Path) -> str | None:
    """Size and mtime: cheap, and an updated or reinstalled FL changes both."""
    try:
        st = path.stat()
    except OSError:
        return None
    return f"{st.st_size}:{st.st_mtime_ns}"


def _render_tested(workspace: Workspace, env: Any) -> bool:
    record = workspace.load_settings().get("fl_test")
    if not isinstance(record, dict) or not record.get("passed") or env.fl_executable is None:
        return False
    return (
        record.get("exe") == str(env.fl_executable)
        and record.get("fingerprint") == _exe_fingerprint(env.fl_executable)
    )


def h_environment(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    env = describe(workspace.load_settings())
    can_render, render_reason = render_fl.availability(env)
    strategy, stem_reason = stems_module.available_strategy(env)
    return {
        "platform": env.platform,
        "python": env.python_version,
        "pyflp": env.pyflp_version,
        "compatShim": env.pyflp_compat_shim,
        "flExecutable": str(env.fl_executable) if env.fl_executable else None,
        "flDiscovery": env.fl_discovery,
        "ffmpeg": str(env.ffmpeg) if env.ffmpeg else None,
        "canRender": can_render,
        "renderReason": render_reason,
        "stemStrategy": strategy.name if strategy else None,
        "stemReason": stem_reason,
        "flArchitecture": env.fl_architecture,
        "flArchitectureOk": env.fl_architecture_ok,
        "flFileVersion": env.fl_file_version,
        # "Ready" is a claim about rendering, and only a passing Test against
        # the executable that is still there can back it (TESTING_HANDOFF P1.1).
        "renderTested": _render_tested(workspace, env),
        "workspace": str(workspace.root),
        "exportRoot": str(workspace.export_root()),
        "providers": sorted(PROVIDERS),
        "build": buildinfo.describe().as_dict(),
        "safeMode": env.safe_mode,
        "exportRootCloud": cloud_sync_provider(workspace.export_root()),
        "suggestedExportRoot": str(Path.home() / "Prosody" / "Exports"),
        "database": db.check_integrity(workspace.db_path).detail,
    }


def h_settings_get(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    return workspace.load_settings()


def h_settings_set(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    return workspace.save_settings(payload.get("settings", {}))


def h_genres(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    out = []
    for name in profiles.available():
        profile = profiles.load(name)
        out.append(
            {
                "id": profile.genre,
                "label": profile.label or profile.genre.title(),
                "structures": sorted(profile.grammar),
                "rules": list(profile.rules),
            }
        )
    return {"genres": out}


#: A project far larger than any real one is a sign the path is not what the
#: user thinks it is. FL projects are kilobytes to low megabytes; 200 MB is
#: generous by two orders of magnitude (HARDENING P0.6).
MAX_SOURCE_BYTES = 200 * 1024 * 1024


def validate_source_path(path: Path) -> Path:
    """Check a path handed in from outside before anything opens it.

    Paths reach here from a drag-and-drop, a file dialog and the Library, and
    a dropped path is untrusted input: the user may have dropped a folder, a
    shortcut, a 4 GB WAV, or something that vanished between the drop and the
    read.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    if path.is_dir():
        raise ValueError(f"{path.name} is a folder. Drop a single .flp file.")
    if not path.is_file():
        raise ValueError(f"{path.name} is not a file.")
    if path.suffix.lower() != ".flp":
        raise ValueError(f"{path.name} is not an .flp file.")

    size = path.stat().st_size
    if size == 0:
        raise ValueError(f"{path.name} is empty.")
    if size > MAX_SOURCE_BYTES:
        raise ValueError(
            f"{path.name} is {size / 1024 / 1024:.0f} MB. That is far larger "
            "than any FL Studio project; Prosody will not open it."
        )

    # Existence is not readability: a file on a disconnected network share, or
    # one another program holds exclusively, fails here rather than midway
    # through a parse.
    try:
        with path.open("rb") as handle:
            handle.read(4)
    except OSError as exc:
        raise ValueError(f"{path.name} could not be read: {exc}") from exc

    return path


def _working_copy(workspace: Workspace, path: Path) -> WorkingCopy:
    """Take a private copy before anything parses the user's file.

    Copy-on-analyze is only a guarantee if it happens at the boundary. Doing
    it inside build() left the API layer parsing the original directly, which
    a test caught (HARDENING P0.3).
    """
    return working_copy(path, workspace.cache)


def _parse_original(backend: PyFLPBackend, copy_path: Path, original: Path) -> BeatProject:
    """Parse a working copy but record the user's path, not the cache path.

    The backend names whatever file it was handed, so parsing a copy would
    otherwise write a path under Cache/jobs into every export's project.json
    — a path that stops existing as soon as the cache is cleared, breaking the
    Library's "source still there?" check and any rebuild from disk.
    """
    project = backend.parse(copy_path)
    return project.model_copy(update={"source_path": str(original)})


def h_inspect(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    return _project_payload(validate_source_path(Path(payload["path"])), workspace)


def h_plan(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    """Generate an arrangement plan for preview. Writes nothing."""
    path = validate_source_path(Path(payload["path"]))
    backend = PyFLPBackend()
    with temporary_copy(path, workspace.cache) as copy:
        project = _parse_original(backend, copy.path, path)
    analysis = analyse_project(project, classify_state(project))
    level = PermissionLevel(int(payload.get("level", 0)))

    planner = get_planner(str(payload.get("provider", "rules")))
    plans = planner.plan(
        PlanRequest(
            project=project, analysis=analysis,
            genre=str(payload.get("genre", "hiphop")),
            structure=str(payload.get("structure", "balanced")),
            level=level, variants=3, seed=int(payload.get("seed", 1234)),
        )
    )
    roles = pattern_roles(project, analysis)
    lanes: dict[str, list[dict[str, int]]] = {}

    variant = str(payload.get("variant", "A"))
    plan = next((p for p in plans if p.variant == variant), plans[0])

    for op in plan.ops:
        if op.op != "tile" or op.role is None:
            continue
        lanes.setdefault(op.role.value, []).append(
            {"startBar": op.start_bar or 1, "bars": op.bars or 0}
        )

    return {
        "variant": plan.variant,
        "genre": plan.genre,
        "structure": plan.structure,
        "level": int(plan.level),
        "seed": plan.seed,
        "tempo": plan.tempo,
        "totalBars": plan.total_bars,
        "durationSeconds": round(
            plan.total_bars * (project.time_signature[0] or 4) * 60
            / (plan.tempo or 120), 1
        ),
        "planner": planner.name,
        "notes": plan.llm_notes,
        "sections": [
            {
                "name": s.name.value, "label": s.name.value.upper(),
                "startBar": s.start_bar, "bars": s.bars, "energy": s.energy,
                "roles": [r.value for r in s.active_roles],
                "dropoutBars": s.dropout_bars,
            }
            for s in plan.sections
        ],
        "lanes": [
            {"role": role, "label": role.replace("_", " ").title(), "blocks": blocks}
            for role, blocks in sorted(lanes.items())
        ],
        "patternRoles": [
            {"pattern": r.pattern, "name": r.name, "role": r.role.value}
            for r in roles
        ],
    }


def h_build(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    path = validate_source_path(Path(payload["path"]))
    settings = workspace.load_settings()
    export_root = Path(
        payload.get("exportRoot") or settings.get("export_root") or workspace.exports
    )

    options = build_module.BuildOptions(
        arrange=bool(payload.get("arrange", True)),
        extract=bool(payload.get("extract", True)),
        genre=str(payload.get("genre", "hiphop")),
        structure=str(payload.get("structure", "balanced")),
        level=PermissionLevel(int(payload.get("level", 0))),
        want_wav=bool(payload.get("wav", True)),
        want_mp3=bool(payload.get("mp3", True)),
        want_midi=bool(payload.get("midi", True)),
        want_zip=bool(payload.get("zip", True)),
        want_stems=bool(payload.get("stems", False)),
        seed=int(payload.get("seed", 1234)),
        variant=str(payload.get("variant", "A")),
    )

    def progress(stage: str, status: str, detail: str) -> None:
        emit({"event": "progress", "stage": stage, "status": status, "detail": detail})

    # Parse once here and hand the models to the builder: it saves a second
    # parse, and it guarantees the library row exists before a build references
    # it, whether or not the user inspected the project first.
    backend = PyFLPBackend()
    copy = _working_copy(workspace, path)
    resume_from = Path(payload["resumeFrom"]) if payload.get("resumeFrom") else None
    project = analysis = None
    if resume_from is not None:
        # Reuse the earlier parse and analysis only for the same bytes.
        try:
            prior = json.loads((resume_from / "job.json").read_text(encoding="utf-8"))
            if prior.get("sourceHash") == copy.source_hash:
                project = BeatProject.model_validate_json(
                    (resume_from / "data" / "project.json").read_text(encoding="utf-8"))
                analysis = Analysis.model_validate_json(
                    (resume_from / "data" / "analysis.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            project = analysis = None
    if project is None:
        project = _parse_original(backend, copy.path, path)
    if analysis is None:
        analysis = analyse_project(project, classify_state(project))
    health = check_project(project, source=copy.path)
    key, _ = guess_key(project)
    _remember(workspace, path, project, health.status, key, status="Building")

    result = build_module.build(
        path, export_root=export_root, options=options,
        project=project, analysis=analysis,
        env=describe(settings), progress=progress,
        # Cache belongs in the state root, not beside Exports: the export root
        # can be anywhere the user chose, including a OneDrive-synced Documents,
        # and scratch copies of their projects have no business syncing.
        cache_root=workspace.cache,
        resume_from=resume_from,
    )

    db.record_build(
        workspace.db_path, result.project_id, genre=options.genre,
        structure=options.structure, level=int(options.level),
        tier=result.tier.value, out_dir=result.out_dir,
    )
    _remember(
        workspace, path, project, health.status, key,
        status="Completed" if result.ok else "Warning",
        genre=options.genre if options.arrange else None,
        out_dir=result.out_dir,
    )

    return {
        "projectId": result.project_id,
        "outDir": result.out_dir,
        "tier": result.tier.value,
        "message": result.message,
        "ok": result.ok,
        "sourceUnchanged": result.source_hash_verified,
        "flpPath": result.flp_path,
        "previewWav": result.preview_wav,
        "previewMp3": result.preview_mp3,
        "stages": [
            {
                "name": s.name, "status": s.status.value, "detail": s.detail,
                "artifacts": [
                    {"kind": a.kind.value, "path": a.path, "label": a.label,
                     "bytes": a.bytes}
                    for a in s.artifacts
                ],
            }
            for s in result.stages
        ],
        "artifacts": [
            {"kind": a.kind.value, "path": a.path, "label": a.label, "bytes": a.bytes}
            for a in result.artifacts
        ],
    }


def h_library(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    db.migrate(workspace.db_path)
    entries = db.list_projects(workspace.db_path, int(payload.get("limit", 200)))
    return {
        "projects": [
            {
                "id": e.project_id, "name": e.name, "path": e.source_path,
                "tempo": e.tempo, "key": e.key, "lengthBars": e.length_bars,
                "genre": e.genre, "status": e.status, "health": e.health.value,
                "updatedAt": e.updated_at.isoformat(), "outDir": e.out_dir,
                "exists": Path(e.source_path).is_file(),
            }
            for e in entries
        ]
    }


def h_jobs_interrupted(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    """Export folders whose build never finished (HARDENING P0.4).

    Offered rather than cleaned up: a half-built folder may hold the only copy
    of something the user wants.
    """
    found = jobs.scan(workspace.export_root())
    return {"interrupted": [i.as_dict() for i in found], "count": len(found)}


def h_jobs_resume(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    """Run an interrupted build again, reusing every stage whose hashes match.

    The source is re-verified first: a changed file means nothing is reused.
    Output goes to a new versioned folder; the interrupted one is left for
    the user to discard (ARCHITECTURE_NOTES item 4, HARDENING P0.4).
    """
    out_dir = Path(payload["outDir"])
    data = json.loads((out_dir / "job.json").read_text(encoding="utf-8"))
    source = validate_source_path(Path(data["sourcePath"]))
    opts = dict(data.get("options") or {})
    request = {
        "path": str(source), "genre": opts.get("genre", "hiphop"),
        "structure": opts.get("structure", "balanced"), "level": opts.get("level", 0),
        "variant": opts.get("variant", "A"), "arrange": data.get("operation") == "arrange",
        "wav": opts.get("wav", True), "mp3": opts.get("mp3", True),
        "midi": opts.get("midi", True), "zip": opts.get("zip", True),
        "stems": opts.get("stems", False), "resumeFrom": str(out_dir),
    }
    if "seed" in opts:
        request["seed"] = opts["seed"]
    return h_build(request, workspace)


def h_jobs_discard(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    """Delete one interrupted export folder, by the user's explicit choice."""
    out_dir = Path(payload["outDir"])
    jobs.discard(out_dir, workspace.export_root())
    return {"discarded": str(out_dir)}


def h_jobs_clear_partials(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    """Remove stray .partial files, leaving every finished file alone."""
    removed = jobs.clear_partials(workspace.export_root())
    return {"removed": [str(p) for p in removed], "count": len(removed)}


def h_events(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    """Every event id in a project: counts, sizes, name previews.

    No note data, plugin state or sample paths — safe to paste into a report.
    Works on files the parser cannot read, which is when it is needed.
    """
    from prosody_core.parse.events_dump import as_text, inventory

    path = validate_source_path(Path(payload["path"]))
    with temporary_copy(path, workspace.cache) as copy:
        inv = inventory(copy.path)
    inv["file"] = path.name
    inv["report"] = as_text(inv)
    return inv


def h_samples_locate(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    """Find missing samples by filename under a folder the user chose.

    Returns candidates marked RELOCATED for the user to confirm. Nothing is
    written: the project's references stay exactly as FL saved them
    (HARDENING P1.6). Relinking is FL Studio's job; this answers "are they
    on this disk at all, and where?".
    """
    root = Path(payload["root"])
    if not root.is_dir():
        raise ValueError(f"{root} is not a folder")
    wanted = [str(p) for p in payload.get("samples", [])]
    if not wanted:
        return {"root": str(root), "results": [], "found": 0}

    by_name: dict[str, list[Path]] = {}
    scanned = 0
    for candidate in root.rglob("*"):
        if scanned > 200_000:
            break
        scanned += 1
        if candidate.is_file():
            by_name.setdefault(candidate.name.casefold(), []).append(candidate)

    results = []
    for original in wanted:
        name = Path(original.replace("\\", "/")).name
        hits = by_name.get(name.casefold(), [])
        results.append({
            "original": original,
            "state": "RELOCATED" if hits else "MISSING",
            "candidates": [str(h) for h in hits[:5]],
            "candidateCount": len(hits),
        })
    return {
        "root": str(root),
        "results": results,
        "found": sum(1 for r in results if r["state"] == "RELOCATED"),
        "scanned": scanned,
    }


def h_system_check(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    """Every capability, its verdict and why (HARDENING P1.4)."""
    result = systemcheck.run(workspace)
    result["report"] = systemcheck.sanitized_report(workspace)
    return result


def h_library_rebuild(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    """Reconstruct the library by rescanning the export folder.

    The index is an index, never the source of truth: every row it holds was
    written from a ``data/project.json`` that is still sitting in the export
    folder. That is what makes discarding a corrupt database safe, and this is
    the other half of that promise — it is also the repair when rows go stale
    or a database is restored from an older backup (HARDENING P0.2).
    """
    integrity = db.check_integrity(workspace.db_path)
    db.migrate(workspace.db_path)

    export_root = workspace.export_root()
    recovered = 0
    skipped: list[str] = []
    seen: set[str] = set()

    # Newest last, so that when one source has several builds the most recent
    # one wins the row.
    folders = sorted(
        (d for d in export_root.glob("*") if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
    ) if export_root.is_dir() else []

    for folder in folders:
        manifest = folder / "data" / "project.json"
        if not manifest.is_file():
            continue
        try:
            project = BeatProject.model_validate_json(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            skipped.append(f"{folder.name}: {exc}")
            continue

        health_file = folder / "reports" / "health.json"
        health = HealthStatus.UNKNOWN
        if health_file.is_file():
            try:
                raw = json.loads(health_file.read_text(encoding="utf-8")).get("status")
                health = HealthStatus(raw) if raw else HealthStatus.UNKNOWN
            except (OSError, ValueError):
                health = HealthStatus.UNKNOWN

        source = Path(project.source_path) if project.source_path else folder
        _remember(
            workspace, source, project, health, None,
            status="Built", out_dir=str(folder),
        )
        seen.add(project.id)
        recovered += 1

    return {
        "recovered": recovered,
        "projects": len(seen),
        "skipped": skipped,
        "scanned": str(export_root),
        "databaseWasCorrupt": not integrity.ok,
        "quarantined": str(integrity.quarantined) if integrity.quarantined else None,
    }


def h_library_forget(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    db.migrate(workspace.db_path)
    db.forget_project(workspace.db_path, str(payload["id"]))
    return {"removed": payload["id"]}


def h_verify(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    """Confirm a source file still hashes to what we recorded."""
    path = Path(payload["path"])
    return {"path": str(path), "hash": sha256_file(path) if path.is_file() else None}


def h_test_fl(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    """Settings -> Test Connection.

    Actually renders the bundled one-bar project unless asked not to. A path
    that exists proves nothing about whether FL will render from it, which is
    the question the button is really asking.
    """
    candidate = payload.get("path")
    settings = dict(workspace.load_settings())
    if candidate:
        settings["fl_executable"] = str(candidate)
    env = describe(settings)
    found = env.fl_executable is not None

    if not found or not payload.get("render", True):
        return {
            "ok": found,
            "path": str(env.fl_executable) if found else None,
            "detail": env.fl_discovery,
            "rendered": False,
        }

    project = payload.get("project")
    result = render_fl.test_connection(
        env, timeout=int(payload.get("timeout", 600)),
        project=Path(project) if project else None,
    )
    workspace.save_settings({"fl_test": {
        "exe": str(env.fl_executable),
        "fingerprint": _exe_fingerprint(env.fl_executable),
        "passed": result.ok,
        "at": datetime.now(timezone.utc).isoformat(),
        "detail": result.detail,
    }})
    return {
        "ok": result.ok,
        "path": str(env.fl_executable),
        "detail": result.detail,
        "seconds": round(result.seconds, 1),
        "rendered": result.ok,
        "duration": result.duration,
        "expected": result.expected,
        "command": result.command,
    }


HANDLERS: dict[str, Handler] = {
    "environment": h_environment,
    "settings.get": h_settings_get,
    "settings.set": h_settings_set,
    "genres": h_genres,
    "project.inspect": h_inspect,
    "arrange.plan": h_plan,
    "build.run": h_build,
    "library.list": h_library,
    "library.forget": h_library_forget,
    "library.rebuild": h_library_rebuild,
    "system.check": h_system_check,
    "project.events": h_events,
    "samples.locate": h_samples_locate,
    "jobs.interrupted": h_jobs_interrupted,
    "jobs.discard": h_jobs_discard,
    "jobs.resume": h_jobs_resume,
    "jobs.clearPartials": h_jobs_clear_partials,
    "project.verify": h_verify,
    "fl.test": h_test_fl,
}


def dispatch(method: str, payload: dict[str, Any], workspace: Workspace) -> None:
    handler = HANDLERS.get(method)
    if handler is None:
        emit({"event": "result", "ok": False, "error": "unknown_method",
              "detail": f"{method!r} is not an API method"})
        return
    try:
        data = handler(payload, workspace)
    except ParseError as exc:
        emit({"event": "result", "ok": False, "error": "parse_failed",
              "detail": f"This project could not be read: {exc.cause}"})
    except (PlanningError, FileNotFoundError, ValueError) as exc:
        emit({"event": "result", "ok": False, "error": "invalid_input",
              "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001 - the UI must always get an answer
        emit({"event": "result", "ok": False, "error": "internal",
              "detail": f"{type(exc).__name__}: {exc}",
              "trace": traceback.format_exc()[-2000:]})
    else:
        emit({"event": "result", "ok": True, "data": data})


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        emit({"event": "result", "ok": False, "error": "usage",
              "detail": "usage: python -m prosody_core.api <method> [json-payload]"})
        return 2

    method = argv[0]
    raw = argv[1] if len(argv) > 1 else "{}"
    if raw == "-":
        raw = sys.stdin.read() or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        emit({"event": "result", "ok": False, "error": "bad_payload",
              "detail": str(exc)})
        return 2

    workspace = Workspace.open(
        Path(payload["workspace"]) if payload.get("workspace") else None
    )
    dispatch(method, payload, workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
