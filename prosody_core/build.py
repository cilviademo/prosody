"""The build orchestrator: one call per user action, with honest staging.

This is what the desktop app drives. Each stage reports OK, WARNING, FAILED or
SKIPPED with a reason, and a failure in one stage never cancels the others -
the user still receives everything that did work.

Output tiers:
  NATIVE  a derivative .flp that passed structural validation
  PACK    an Arrangement Pack (audio, MIDI, plan, reports) when native writing
          was not safe for this project. A supported result, not an error.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from prosody_core.ai.planner import PlanRequest, get_planner
from prosody_core.arrange.permissions import PermissionDenied
from prosody_core.classify.signals import analyse_project
from prosody_core.env import Environment, describe
from prosody_core.extract import render_fl
from prosody_core.extract import stems as stems_module
from prosody_core.extract.midi import write_role_midi
from prosody_core.extract.package import package_project
from prosody_core.fs.safety import sha256_file, slugify, versioned_path
from prosody_core.fs.source import SourceChanged, working_copy
from prosody_core.health.check import check_project, classify_state, human_status
from prosody_core.model.schemas import (
    Analysis,
    ArrangementPlan,
    Artifact,
    ArtifactKind,
    BeatProject,
    BuildResult,
    OutputTier,
    PermissionLevel,
    StageResult,
    StageStatus,
)
from prosody_core.parse.pyflp_backend import PyFLPBackend
from prosody_core.validate.validator import validate_derivative
from prosody_core.write.flp_writer import WriteUnsupported, write_arrangement

ProgressFn = Callable[[str, str, str], None]  # (stage, status, detail)

APP_TAG = "PROSODY"


@dataclass
class BuildOptions:
    """Everything the UI can ask for in one build."""

    arrange: bool = True
    extract: bool = True
    genre: str = "hiphop"
    structure: str = "balanced"
    level: PermissionLevel = PermissionLevel.STRUCTURE_ONLY
    want_wav: bool = True
    want_mp3: bool = True
    want_midi: bool = True
    want_zip: bool = True
    want_stems: bool = False
    seed: int = 1234
    variant: str = "A"


@dataclass
class _Recorder:
    """Collects stage results and streams progress to the caller."""

    progress: ProgressFn | None = None
    stages: list[StageResult] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)

    def begin(self, name: str, detail: str = "") -> None:
        if self.progress:
            self.progress(name, StageStatus.RUNNING.value, detail)

    def finish(
        self, name: str, status: StageStatus, detail: str = "",
        artifacts: tuple[Artifact, ...] = (),
    ) -> None:
        self.stages.append(
            StageResult(name=name, status=status, detail=detail, artifacts=artifacts)
        )
        self.artifacts.extend(artifacts)
        if self.progress:
            self.progress(name, status.value, detail)


class SafeModeError(RuntimeError):
    """Raised when a write is attempted in Safe Mode."""


def artifact(kind: ArtifactKind, path: Path, label: str) -> Artifact:
    path = Path(path)
    return Artifact(
        kind=kind, path=str(path), label=label,
        bytes=path.stat().st_size if path.is_file() else 0,
    )


def output_stem(source: Path, genre: str, version: int) -> str:
    """``Starfall__PROSODY_RNB_V001`` - the name shared by the folder and its
    generated project, so a file is identifiable once moved out of its folder."""
    return f"{source.stem}__{APP_TAG}_{genre.upper()}_V{version:03d}"


def output_name(source: Path, genre: str, version: int = 1) -> str:
    return output_stem(source, genre, version)


def prepare_output_dir(export_root: Path, source: Path, genre: str) -> Path:
    """``<exports>/<Source__PROSODY_GENRE_Vnnn>/`` - versioned, never reused."""
    parent = Path(export_root)
    parent.mkdir(parents=True, exist_ok=True)
    for version in range(1, 1000):
        candidate = parent / output_stem(source, genre, version)
        if not candidate.exists():
            candidate.mkdir(parents=True)
            return candidate
    raise FileExistsError(
        f"exhausted 999 versions of {source.stem} for {genre}"
    )


def build(
    source: Path,
    *,
    export_root: Path,
    options: BuildOptions,
    project: BeatProject | None = None,
    analysis: Analysis | None = None,
    env: Environment | None = None,
    progress: ProgressFn | None = None,
    cache_root: Path | None = None,
) -> BuildResult:
    """Run a full build. Always returns a result; never raises for user input."""
    source = Path(source)
    env = env or describe()
    if env.safe_mode:
        # Safe Mode exists so a user whose last session ended badly can still
        # open Prosody, look at their library and read Diagnostics. Refusing
        # here rather than part-way through is the point: nothing is written.
        raise SafeModeError(
            "Safe Mode is on, so nothing is written. Restart Prosody normally "
            "to build, or remove safemode.flag from the Prosody folder."
        )
    backend = PyFLPBackend()
    recorder = _Recorder(progress=progress)

    source_hash = sha256_file(source)

    # Work from a private copy. Every stage below reads `working`, so nothing
    # downstream can reach the user's file even by mistake — and a source that
    # FL Studio currently has open is still a stable set of bytes to parse
    # (HARDENING P0.3).
    try:
        copy = working_copy(source, cache_root or (export_root.parent / "Cache"))
        working = copy.path
    except (OSError, SourceChanged) as exc:
        raise SourceChanged(f"could not take a working copy of {source}: {exc}") from exc

    # -- parse ------------------------------------------------------------- #
    recorder.begin("Preparing project")
    if project is None:
        project = backend.parse(working)
    if analysis is None:
        analysis = analyse_project(project, classify_state(project))
    health = check_project(project)
    genre_tag = options.genre if options.arrange else "extract"
    out_dir = prepare_output_dir(export_root, source, genre_tag)
    # The folder name already carries the version; artefacts reuse it verbatim.
    artifact_stem = out_dir.name
    recorder.finish(
        "Preparing project", StageStatus.OK,
        f"{len(project.patterns)} patterns, {len(project.channels)} channels"
        f" · {human_status(health.status).lower()}",
    )

    for sub in ("preview", "stems", "midi", "data", "reports"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)

    _dump(out_dir / "data" / "project.json", project)
    _dump(out_dir / "data" / "analysis.json", analysis)
    _dump(out_dir / "reports" / "health.json", health)
    (out_dir / "reports" / "missing-assets.json").write_text(
        json.dumps(
            [a.model_dump(mode="json") for a in health.missing_assets], indent=2
        ) + "\n",
        encoding="utf-8",
    )

    plan: ArrangementPlan | None = None
    tier = OutputTier.NONE
    flp_path: Path | None = None

    # -- arrange ----------------------------------------------------------- #
    if options.arrange:
        recorder.begin("Planning arrangement")
        try:
            planner = get_planner(str(_setting(env, "rules")))
            plans = planner.plan(
                PlanRequest(
                    project=project, analysis=analysis, genre=options.genre,
                    structure=options.structure, level=options.level,
                    variants=3, seed=options.seed,
                )
            )
            plan = next((p for p in plans if p.variant == options.variant), plans[0])
            _dump(out_dir / "data" / "arrangement.json", plan)
            recorder.finish(
                "Planning arrangement", StageStatus.OK,
                f"{len(plan.sections)} sections, {plan.total_bars} bars "
                f"({planner.name})",
                (artifact(ArtifactKind.JSON,
                          out_dir / "data" / "arrangement.json", "arrangement.json"),),
            )
        except Exception as exc:  # noqa: BLE001 - a bad plan must not kill the build
            recorder.finish("Planning arrangement", StageStatus.FAILED, str(exc))

        # -- native derivative .flp ---------------------------------------- #
        if plan is not None:
            recorder.begin("Writing FL Studio project")
            destination = out_dir / f"{artifact_stem}.flp"
            try:
                report = write_arrangement(
                    working, destination, plan, project, protect=source,
                )
                result = validate_derivative(
                    source, destination, project, plan, backend,
                    source_hash=source_hash,
                )
                _dump(out_dir / "reports" / "validation.json", result)
                (out_dir / "reports" / "operations.log").write_text(
                    "\n".join(report.operations) + "\n", encoding="utf-8"
                )

                if result.passed:
                    tier = OutputTier.NATIVE
                    flp_path = destination
                    detail = (
                        f"{report.clips_written} clips, "
                        f"{report.markers_written} section markers, all "
                        "patterns and channels preserved"
                    )
                    status = StageStatus.WARNING if report.warnings else StageStatus.OK
                    if report.warnings:
                        detail += f" - {report.warnings[0]}"
                    recorder.finish(
                        "Writing FL Studio project", status, detail,
                        (artifact(ArtifactKind.FLP, destination, destination.name),),
                    )
                else:
                    destination.unlink(missing_ok=True)
                    failed = [c.name for c in result.checks if c.ok is False]
                    recorder.finish(
                        "Writing FL Studio project", StageStatus.WARNING,
                        f"validation failed ({', '.join(failed)}); building an "
                        "Arrangement Pack instead",
                    )
            except (WriteUnsupported, PermissionDenied) as exc:
                destination.unlink(missing_ok=True)
                recorder.finish(
                    "Writing FL Studio project", StageStatus.WARNING,
                    f"{exc} - building an Arrangement Pack instead",
                )
            except Exception as exc:  # noqa: BLE001
                destination.unlink(missing_ok=True)
                recorder.finish(
                    "Writing FL Studio project", StageStatus.WARNING,
                    f"unexpected writer error: {exc} - building an Arrangement "
                    "Pack instead",
                )

    # -- MIDI -------------------------------------------------------------- #
    if options.want_midi:
        recorder.begin("Exporting MIDI")
        try:
            files = write_role_midi(project, analysis, out_dir / "midi")
            if files:
                recorder.finish(
                    "Exporting MIDI", StageStatus.OK, f"{len(files)} role files",
                    tuple(artifact(ArtifactKind.MIDI, f, f.name) for f in files),
                )
            else:
                recorder.finish(
                    "Exporting MIDI", StageStatus.SKIPPED,
                    "this project has no note data to export",
                )
        except Exception as exc:  # noqa: BLE001
            recorder.finish("Exporting MIDI", StageStatus.FAILED, str(exc))

    # -- audio ------------------------------------------------------------- #
    preview_wav = preview_mp3 = None
    if options.want_wav or options.want_mp3:
        # FL Studio shows its own window during a command-line render and there
        # is no switch to suppress it. Saying so up front is the difference
        # between "working" and "something just hijacked my screen".
        recorder.begin(
            "Rendering audio",
            "FL Studio will open briefly while it renders.",
        )
        can_render, reason = render_fl.availability(env)
        if not can_render:
            recorder.finish(
                "Rendering audio", StageStatus.SKIPPED,
                f"{reason}. Set it up in Settings to render audio.",
            )
        else:
            formats = tuple(
                f for f, want in (("wav", options.want_wav), ("mp3", options.want_mp3))
                if want
            )
            render_target = flp_path or source
            result = render_fl.render_project(
                render_target, out_dir / "preview", formats=formats, env=env,
            )
            (out_dir / "reports" / "render.json").write_text(
                json.dumps(result.as_log(), indent=2) + "\n", encoding="utf-8"
            )
            if result.ok:
                produced = []
                for path in result.outputs:
                    kind = (
                        ArtifactKind.WAV if path.suffix.lower() == ".wav"
                        else ArtifactKind.MP3
                    )
                    if kind is ArtifactKind.WAV and preview_wav is None:
                        preview_wav = path
                    if kind is ArtifactKind.MP3 and preview_mp3 is None:
                        preview_mp3 = path
                    produced.append(artifact(kind, path, path.name))
                recorder.finish(
                    "Rendering audio", StageStatus.OK,
                    f"{len(produced)} file(s) in {result.seconds:.0f}s",
                    tuple(produced),
                )
            else:
                recorder.finish(
                    "Rendering audio", StageStatus.FAILED,
                    result.message or "FL Studio did not produce audio",
                )

    # -- stems ------------------------------------------------------------- #
    if options.want_stems:
        recorder.begin("Creating stems")
        strategy, why = stems_module.available_strategy(env)
        if strategy is None:
            recorder.finish("Creating stems", StageStatus.SKIPPED, why)
        else:
            stem_result = strategy.render(
                flp_path or source, project, analysis, out_dir / "stems", env=env,
            )
            if stem_result.ok:
                recorder.finish(
                    "Creating stems", StageStatus.OK,
                    f"{len(stem_result.stems)} stems via {stem_result.strategy}",
                    tuple(
                        artifact(ArtifactKind.STEM, s.path, s.path.name)
                        for s in stem_result.stems
                    ),
                )
            else:
                recorder.finish(
                    "Creating stems", StageStatus.WARNING,
                    stem_result.message or "no stems produced",
                )

    # -- package ----------------------------------------------------------- #
    if options.want_zip:
        recorder.begin("Packaging project")
        try:
            zip_source = flp_path or source
            zip_path = out_dir / f"{artifact_stem}.zip"
            extra = {}
            plan_file = out_dir / "data" / "arrangement.json"
            if plan_file.is_file():
                extra["arrangement.json"] = plan_file
            report = package_project(zip_source, project, zip_path, extra=extra)
            status = (
                StageStatus.WARNING if report.samples_missing else StageStatus.OK
            )
            detail = f"{report.files} files, {report.samples_included} samples"
            if report.samples_missing:
                detail += f", {len(report.samples_missing)} samples not found"
            recorder.finish(
                "Packaging project", status, detail,
                (artifact(ArtifactKind.ZIP, zip_path, zip_path.name),),
            )
        except Exception as exc:  # noqa: BLE001
            recorder.finish("Packaging project", StageStatus.FAILED, str(exc))

    # -- decide the tier --------------------------------------------------- #
    if tier is not OutputTier.NATIVE and options.arrange:
        has_pack = any(
            s.status in (StageStatus.OK, StageStatus.WARNING) and s.artifacts
            for s in recorder.stages
        )
        tier = OutputTier.PACK if has_pack else OutputTier.NONE
    elif not options.arrange:
        tier = OutputTier.PACK if recorder.artifacts else OutputTier.NONE

    unchanged = sha256_file(source) == source_hash
    message = _message(tier, options)

    result = BuildResult(
        project_id=project.id,
        out_dir=str(out_dir),
        tier=tier,
        stages=tuple(recorder.stages),
        artifacts=tuple(recorder.artifacts),
        flp_path=str(flp_path) if flp_path else None,
        preview_wav=str(preview_wav) if preview_wav else None,
        preview_mp3=str(preview_mp3) if preview_mp3 else None,
        source_hash_verified=unchanged,
        message=message,
    )
    _dump(out_dir / "reports" / "build.json", result)
    return result


def _message(tier: OutputTier, options: BuildOptions) -> str:
    if tier is OutputTier.NATIVE:
        return "Your arranged FL Studio project is ready to open."
    if tier is OutputTier.PACK and options.arrange:
        return (
            "Native project generation isn't available for this project. "
            "An Arrangement Pack was created instead."
        )
    if tier is OutputTier.PACK:
        return "Your export is ready."
    return "Nothing could be produced for this project."


def _setting(env: Environment, default: str) -> str:
    del env
    return default


def _dump(path: Path, model: object) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump(mode="json")  # type: ignore[attr-defined]
    Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def copy_into(source: Path, destination_dir: Path) -> Path:
    destination = Path(destination_dir) / Path(source).name
    shutil.copy2(source, destination)
    return destination


def suggest_name(source: Path, genre: str) -> str:
    return slugify(f"{Path(source).stem}-{genre}")


__all__ = [
    "BuildOptions",
    "BuildResult",
    "build",
    "copy_into",
    "output_name",
    "prepare_output_dir",
    "suggest_name",
    "versioned_path",
]
