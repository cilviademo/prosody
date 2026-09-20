"""Line-delimited JSON API for the Asterism desktop shell.

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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from flpfinisher import build as build_module
from flpfinisher.ai.planner import PROVIDERS, PlanRequest, get_planner
from flpfinisher.arrange import profiles
from flpfinisher.arrange.planner import PlanningError, pattern_roles
from flpfinisher.classify.signals import analyse_project
from flpfinisher.env import describe
from flpfinisher.extract import render_fl
from flpfinisher.extract import stems as stems_module
from flpfinisher.fs.safety import sha256_file
from flpfinisher.health.check import check_project, classify_state
from flpfinisher.index import db
from flpfinisher.model.roles import Role
from flpfinisher.model.schemas import (
    BeatProject,
    HealthStatus,
    LibraryEntry,
    PermissionLevel,
)
from flpfinisher.parse.adapter import ParseError
from flpfinisher.parse.pyflp_backend import PyFLPBackend
from flpfinisher.workspace import Workspace

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


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


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
    project = backend.parse(path)
    analysis = analyse_project(project, classify_state(project))
    health = check_project(project)
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
            "label": _health_label(health.status),
            "checks": [
                {"name": c.name, "ok": c.ok, "detail": c.detail}
                for c in health.checks
            ],
            "missing": [a.identifier for a in health.missing_assets],
        },
        "canArrange": bool(patterns),
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


def _health_label(status: HealthStatus) -> str:
    return {
        HealthStatus.READY: "Ready",
        HealthStatus.PARTIAL: "Partly readable",
        HealthStatus.REQUIRES_FREEZE: "Missing samples",
        HealthStatus.BLOCKED: "Cannot be used",
        HealthStatus.UNKNOWN: "Ready to analyse",
    }[status]


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #


def h_environment(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    env = describe()
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
        "workspace": str(workspace.root),
        "exportRoot": str(workspace.export_root()),
        "providers": sorted(PROVIDERS),
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


def h_inspect(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    path = Path(payload["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist")
    if path.suffix.lower() != ".flp":
        raise ValueError(f"{path.name} is not an .flp file")
    return _project_payload(path, workspace)


def h_plan(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    """Generate an arrangement plan for preview. Writes nothing."""
    path = Path(payload["path"])
    backend = PyFLPBackend()
    project = backend.parse(path)
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
    path = Path(payload["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist")
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
    project = backend.parse(path)
    analysis = analyse_project(project, classify_state(project))
    health = check_project(project)
    key, _ = guess_key(project)
    _remember(workspace, path, project, health.status, key, status="Building")

    result = build_module.build(
        path, export_root=export_root, options=options,
        project=project, analysis=analysis, progress=progress,
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


def h_library_forget(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    db.migrate(workspace.db_path)
    db.forget_project(workspace.db_path, str(payload["id"]))
    return {"removed": payload["id"]}


def h_verify(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    """Confirm a source file still hashes to what we recorded."""
    path = Path(payload["path"])
    return {"path": str(path), "hash": sha256_file(path) if path.is_file() else None}


def h_test_fl(payload: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    """Settings -> Test Connection."""
    candidate = payload.get("path")
    if candidate:
        import os

        os.environ["FLPF_FL_EXE"] = str(candidate)
    env = describe()
    found = env.fl_executable is not None
    return {
        "ok": found,
        "path": str(env.fl_executable) if found else None,
        "detail": env.fl_discovery,
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
              "detail": "usage: python -m flpfinisher.api <method> [json-payload]"})
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
