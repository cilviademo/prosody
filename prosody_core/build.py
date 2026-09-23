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
from typing import Any

from prosody_core.ai.planner import PlanRequest, get_planner
from prosody_core.arrange.permissions import PermissionDenied
from prosody_core.classify.signals import ANALYSIS_VERSION, analyse_project
from prosody_core.env import Environment, describe
from prosody_core.extract import render_fl
from prosody_core.extract import stems as stems_module
from prosody_core.extract.midi import write_role_midi
from prosody_core.extract.package import package_project
from prosody_core.fs.safety import sha256_file, slugify, versioned_path
from prosody_core.fs.source import SourceChanged, working_copy
from prosody_core.health.check import check_project, classify_state, human_status
from prosody_core.jobs import JobManifest
from prosody_core.model.schemas import (
    Analysis,
    ArrangementPlan,
    Artifact,
    ArtifactKind,
    BeatProject,
    BuildResult,
    EvidenceStatus,
    Lineage,
    LineageStage,
    MutationOp,
    OperationSet,
    OutputTier,
    PermissionLevel,
    PipelineStage,
    StageRecord,
    StageResult,
    StageState,
    StageStatus,
)
from prosody_core.parse.pyflp_backend import PyFLPBackend
from prosody_core.validate import midi_check
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
    #: Set once the output folder exists, so an interrupted build is
    #: self-describing (HARDENING P0.4).
    manifest: JobManifest | None = None
    #: Applied to every artifact recorded without one (ARCHITECTURE_NOTES 2).
    lineage: Lineage | None = None
    #: The twelve named pipeline stages, with hashes (ARCHITECTURE_NOTES 4).
    pipeline: dict[PipelineStage, StageRecord] = field(default_factory=dict)
    configuration_hash: str | None = None

    def _pipe(self, stage: PipelineStage, **update: Any) -> None:
        current = self.pipeline.get(stage) or StageRecord(
            stage=stage, analysis_version=ANALYSIS_VERSION,
            configuration_hash=self.configuration_hash)
        self.pipeline[stage] = current.model_copy(update=update)
        if self.manifest is not None:
            self.manifest.pipeline = [r.model_dump(mode="json") for r in self.pipeline.values()]
            self.manifest.write()

    def stage_start(self, stage: PipelineStage, input_hash: str | None) -> None:
        self._pipe(stage, state=StageState.RUNNING, input_hash=input_hash,
                   analysis_version=ANALYSIS_VERSION,
                   configuration_hash=self.configuration_hash, started_at=_now())

    def stage_done(self, stage: PipelineStage, output_hash: str | None, detail: str = "",
                   resumed: bool = False) -> None:
        self._pipe(stage, state=StageState.RESUMED if resumed else StageState.COMPLETED,
                   output_hash=output_hash, detail=detail or None, completed_at=_now())

    def stage_skip(self, stage: PipelineStage, why: str) -> None:
        self._pipe(stage, state=StageState.SKIPPED, detail=why, completed_at=_now())

    def stage_fail(self, stage: PipelineStage, error: str) -> None:
        self._pipe(stage, state=StageState.FAILED, error=error, completed_at=_now())

    def begin(self, name: str, detail: str = "") -> None:
        if self.progress:
            self.progress(name, StageStatus.RUNNING.value, detail)

    def finish(
        self, name: str, status: StageStatus, detail: str = "",
        artifacts: tuple[Artifact, ...] = (),
    ) -> None:
        if self.lineage is not None:
            artifacts = tuple(
                a if a.lineage is not None else a.model_copy(update={"lineage": self.lineage})
                for a in artifacts
            )
        self.stages.append(
            StageResult(name=name, status=status, detail=detail, artifacts=artifacts)
        )
        self.artifacts.extend(artifacts)
        if self.manifest is not None:
            self.manifest.stage(name, status.value, detail)
        if self.progress:
            self.progress(name, status.value, detail)


class SafeModeError(RuntimeError):
    """Raised when a write is attempted in Safe Mode."""


def artifact(
    kind: ArtifactKind, path: Path, label: str, lineage: Lineage | None = None,
) -> Artifact:
    path = Path(path)
    return Artifact(
        kind=kind, path=str(path), label=label,
        bytes=path.stat().st_size if path.is_file() else 0,
        lineage=lineage,
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
    resume_from: Path | None = None,
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
    # Falls back beside Exports only when no cache root was given, which is the
    # CLI's direct-call path; the app always passes the state root.
    cache = Path(cache_root) if cache_root else (export_root.parent / "Cache")
    try:
        copy = working_copy(source, cache)
        working = copy.path
    except (OSError, SourceChanged) as exc:
        raise SourceChanged(f"could not take a working copy of {source}: {exc}") from exc

    recorder.configuration_hash = configuration_hash(options)
    recorder.stage_start(PipelineStage.INGESTED, source_hash)
    recorder.stage_done(PipelineStage.INGESTED, copy.source_hash, f"working copy at {working}")

    # -- parse ------------------------------------------------------------- #
    recorder.begin("Preparing project")
    recorder.stage_start(PipelineStage.PROJECT_PARSED, copy.source_hash)
    parsed_resumed = False
    if project is not None:
        parsed_resumed = _reused(resume_from, PipelineStage.PROJECT_PARSED, copy.source_hash,
                                 recorder.configuration_hash, _digest(project))
    else:
        ok, _ = _resumable(resume_from, PipelineStage.PROJECT_PARSED, copy.source_hash,
                           recorder.configuration_hash)
        if ok:
            try:
                project = BeatProject.model_validate_json(
                    (Path(resume_from) / "data" / "project.json").read_text(encoding="utf-8"))  # type: ignore[arg-type]
                parsed_resumed = True
            except (OSError, ValueError):
                project = None
        if project is None:
            project = backend.parse(working)
    recorder.stage_done(PipelineStage.PROJECT_PARSED, _digest(project),
                        f"{len(project.patterns)} patterns, {len(project.channels)} channels",
                        resumed=parsed_resumed)

    recorder.stage_start(PipelineStage.MIDI_ANALYZED, _digest(project))
    analysis_resumed = False
    if analysis is not None:
        analysis_resumed = _reused(resume_from, PipelineStage.MIDI_ANALYZED, _digest(project),
                                   recorder.configuration_hash, _digest(analysis))
    else:
        ok, _ = _resumable(resume_from, PipelineStage.MIDI_ANALYZED, _digest(project),
                           recorder.configuration_hash)
        if ok:
            try:
                analysis = Analysis.model_validate_json(
                    (Path(resume_from) / "data" / "analysis.json").read_text(encoding="utf-8"))  # type: ignore[arg-type]
                analysis_resumed = True
            except (OSError, ValueError):
                analysis = None
        if analysis is None:
            analysis = analyse_project(project, classify_state(project))
    recorder.stage_done(PipelineStage.MIDI_ANALYZED, _digest(analysis),
                        f"{len(analysis.roles)} role assignments", resumed=analysis_resumed)
    recorder.stage_skip(PipelineStage.AUDIO_ANALYZED, "no audio analysis in this version")
    recorder.stage_skip(PipelineStage.MIXER_ANALYZED, "mixer inserts are read, not analysed")
    recorder.stage_start(PipelineStage.STRUCTURE_INFERRED, _digest(analysis))
    recorder.stage_done(PipelineStage.STRUCTURE_INFERRED, _digest(analysis),
                        f"state: {analysis.state.value}", resumed=analysis_resumed)

    health = check_project(project, source=working)
    recorder.stage_start(PipelineStage.ASSETS_RESOLVED, _digest(project))
    recorder.stage_done(PipelineStage.ASSETS_RESOLVED, _digest(health),
                        f"{len(health.missing_assets)} missing")
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

    recorder.lineage = Lineage(
        parent_project_id=project.id, parent_hash=source_hash,
        stage=LineageStage.EXPORTED,
    )
    recorder.manifest = JobManifest(
        out_dir=out_dir,
        source_path=str(source),
        source_hash=source_hash,
        parent_project_id=project.id,
        operation="arrange" if options.arrange else "extract",
        options={
            "genre": options.genre, "structure": options.structure,
            "level": int(options.level), "variant": options.variant,
            "wav": options.want_wav, "mp3": options.want_mp3,
            "midi": options.want_midi, "zip": options.want_zip,
            "stems": options.want_stems,
        },
        working_copy=str(working),
    )
    recorder.manifest.write()

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
    validation_level: str | None = None

    # -- arrange ----------------------------------------------------------- #
    if options.arrange:
        recorder.begin("Planning arrangement")
        try:
            plan_input = _digest(analysis)
            recorder.stage_start(PipelineStage.ARRANGEMENT_READY, plan_input)
            ok, _ = _resumable(resume_from, PipelineStage.USER_REVIEWED, plan_input,
                               recorder.configuration_hash)
            plan = None
            planner_name = "reused from the earlier build"
            if ok:
                try:
                    plan = ArrangementPlan.model_validate_json(
                        (Path(resume_from) / "data" / "arrangement.json").read_text(encoding="utf-8"))  # type: ignore[arg-type]
                except (OSError, ValueError):
                    plan = None
            if plan is not None:
                recorder.stage_done(PipelineStage.ARRANGEMENT_READY, plan.operation_set_id,
                                    "reused from the earlier build", resumed=True)
                recorder.stage_skip(PipelineStage.OPTIONS_GENERATED, "reused the chosen plan")
                recorder.stage_start(PipelineStage.USER_REVIEWED, plan_input)
                recorder.stage_done(PipelineStage.USER_REVIEWED, plan.operation_set_id,
                                    f"variant {plan.variant}", resumed=True)
            else:
                planner = get_planner(str(_setting(env, "rules")))
                planner_name = planner.name
                plans = planner.plan(
                    PlanRequest(
                        project=project, analysis=analysis, genre=options.genre,
                        structure=options.structure, level=options.level,
                        variants=3, seed=options.seed,
                    )
                )
                recorder.stage_done(PipelineStage.ARRANGEMENT_READY,
                                    _digest([p.operation_set_id for p in plans]),
                                    f"{len(plans)} variants ({planner.name})")
                recorder.stage_start(PipelineStage.OPTIONS_GENERATED, plan_input)
                recorder.stage_done(PipelineStage.OPTIONS_GENERATED,
                                    _digest([p.operation_set_id for p in plans]),
                                    ", ".join(p.variant for p in plans))
                plan = next((p for p in plans if p.variant == options.variant), plans[0])
                recorder.stage_start(PipelineStage.USER_REVIEWED, plan_input)
                recorder.stage_done(PipelineStage.USER_REVIEWED, plan.operation_set_id,
                                    f"variant {plan.variant} chosen")
            # Choosing a variant is the user's decision; the other variants
            # stay GENERATED/PROPOSED (ARCHITECTURE_NOTES items 1 and 2).
            plan = plan.model_copy(update={"evidence_status": EvidenceStatus.USER_APPROVED})
            # The chosen plan is the user's working copy; everything from here
            # descends from this exact operation set.
            recorder.lineage = recorder.lineage.model_copy(
                update={"operation_set_id": plan.operation_set_id}
            ) if recorder.lineage else None
            if recorder.manifest is not None:
                recorder.manifest.operation_set_id = plan.operation_set_id
                recorder.manifest.write()
            _dump(out_dir / "data" / "arrangement.json", plan)
            recorder.finish(
                "Planning arrangement", StageStatus.OK,
                f"{len(plan.sections)} sections, {plan.total_bars} bars "
                f"({planner_name})",
                (artifact(ArtifactKind.JSON,
                          out_dir / "data" / "arrangement.json", "arrangement.json"),),
            )
        except Exception as exc:  # noqa: BLE001 - a bad plan must not kill the build
            recorder.stage_fail(PipelineStage.ARRANGEMENT_READY, str(exc))
            recorder.finish("Planning arrangement", StageStatus.FAILED, str(exc))

        # -- native derivative .flp ---------------------------------------- #
        if plan is not None:
            recorder.begin("Writing FL Studio project")
            destination = out_dir / f"{artifact_stem}.flp"
            try:
                recorder.stage_start(PipelineStage.PROJECT_COMPILED, plan.operation_set_id)
                report = write_arrangement(
                    working, destination, plan, project, protect=source,
                )
                recorder.stage_done(PipelineStage.PROJECT_COMPILED, sha256_file(destination),
                                    f"{report.clips_written} clips")
                recorder.stage_start(PipelineStage.EXPORT_VALIDATED, sha256_file(destination))
                result = validate_derivative(
                    source, destination, project, plan, backend,
                    source_hash=source_hash,
                )
                _dump(out_dir / "reports" / "validation.json", result)
                validation_level = result.level.value
                if result.passed:
                    recorder.stage_done(PipelineStage.EXPORT_VALIDATED, _digest(result), result.level.value)
                else:
                    recorder.stage_fail(PipelineStage.EXPORT_VALIDATED, result.level_detail or "validation failed")
                # All three layers, with the writer's result on every
                # mutation, so any change in the file can be followed back to
                # the intent that asked for it (ARCHITECTURE_NOTES item 3).
                _dump(
                    out_dir / "data" / "operations.json",
                    OperationSet(
                        operation_set_id=plan.operation_set_id,
                        layer_a=plan.sections,
                        layer_b=tuple(
                            op.model_copy(update={"result": _op_result(i, report.mutations)})
                            for i, op in enumerate(plan.ops)
                        ),
                        layer_c=report.mutations,
                    ),
                )
                # The plan's own validation status follows what the writer
                # proved about the file it produced.
                plan = plan.model_copy(update={"validation_status": result.level})
                _dump(out_dir / "data" / "arrangement.json", plan)
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
                    # Keep the file, out of Exports. Deleting it destroys the
                    # only evidence of why the writer got it wrong, and an
                    # unvalidated project must never look like a deliverable
                    # (HARDENING P1.1).
                    failed = [c.name for c in result.checks if c.ok is False]
                    quarantine = cache / "unvalidated"
                    quarantine.mkdir(parents=True, exist_ok=True)
                    kept = quarantine / f"{destination.stem}.unvalidated.flp"
                    try:
                        destination.replace(kept)
                    except OSError:
                        # Different volume, or the file is gone; either way the
                        # build must not stop over where a diagnostic landed.
                        destination.unlink(missing_ok=True)
                        kept = None
                    recorder.finish(
                        "Writing FL Studio project", StageStatus.WARNING,
                        f"validation failed ({', '.join(failed)}); building an "
                        "Arrangement Pack instead"
                        + (f". The unvalidated file is kept at {kept}" if kept else ""),
                    )
            except (WriteUnsupported, PermissionDenied) as exc:
                recorder.stage_skip(PipelineStage.PROJECT_COMPILED, f"native write unavailable: {exc}")
                recorder.stage_skip(PipelineStage.EXPORT_VALIDATED, "nothing compiled to validate")
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

    if not options.arrange:
        for st in (PipelineStage.ARRANGEMENT_READY, PipelineStage.OPTIONS_GENERATED,
                   PipelineStage.USER_REVIEWED, PipelineStage.PROJECT_COMPILED,
                   PipelineStage.EXPORT_VALIDATED):
            recorder.stage_skip(st, "extract only; no arrangement requested")

    # -- MIDI -------------------------------------------------------------- #
    if options.want_midi:
        recorder.begin("Exporting MIDI")
        try:
            files = write_role_midi(project, analysis, out_dir / "midi")
            if files:
                # A .mid that exists is not a .mid that is right, and a wrong
                # one is invisible until the user drags it into a DAW and hears
                # nothing. Reopen every file we just wrote (HARDENING P1.3).
                checks = [midi_check.reopens(f) for f in files]
                _dump_json(
                    out_dir / "reports" / "midi-verification.json",
                    [c.as_dict() for c in checks],
                )
                broken = [c for c in checks if not c.ok]
                recorder.finish(
                    "Exporting MIDI",
                    StageStatus.WARNING if broken else StageStatus.OK,
                    f"{len(files)} role files"
                    + (
                        f" · {len(broken)} could not be read back: "
                        f"{broken[0].path.name} — {broken[0].detail}"
                        if broken
                        else ", all verified by reopening them"
                    ),
                    tuple(
                        artifact(ArtifactKind.MIDI, c.path, c.path.name)
                        for c in checks if c.ok
                    ),
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
            render_target = flp_path or working

            # Check the disk before launching FL: a render that runs out of
            # space leaves a truncated WAV and a machine with nothing left
            # (HARDENING P0.5).
            minutes = (plan.total_bars if plan else project.length_bars) * 4 * 60 / (
                project.tempo or 120
            ) / 60
            needed = render_fl.estimate_render_bytes(
                minutes, stem_count=len(analysis.roles) if options.want_stems else 0
            )
            enough, headroom = render_fl.disk_headroom(out_dir, needed)
            if not enough:
                # Reported by the shared handler below, like any other
                # unsuccessful render, so there is one place that decides.
                result = render_fl.RenderResult(ok=False, message=headroom)
            else:
                result = render_fl.render_project(
                    render_target, out_dir / "preview", formats=formats, env=env,
                    timeout=render_fl.render_timeout(
                        minutes,
                        stem_count=len(analysis.roles) if options.want_stems else 0,
                    ),
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
                # FL renders silence for a sample it cannot find. The file
                # exists and plays, so it is a warning with a count, not a
                # success and not a failure (TESTING_HANDOFF P1.5).
                absent = len(health.missing_assets)
                recorder.finish(
                    "Rendering audio",
                    StageStatus.WARNING if absent else StageStatus.OK,
                    f"{len(produced)} file(s) in {result.seconds:.0f}s"
                    + (f"; incomplete: {absent} sample{'s' if absent != 1 else ''} missing"
                       if absent else ""),
                    tuple(produced),
                )
            else:
                recorder.finish(
                    "Rendering audio",
                    StageStatus.WARNING if result.closed_by_user else StageStatus.FAILED,
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
        lineage=recorder.lineage,
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

    # Mark the manifest finished last. Anything that stops the build before
    # this line leaves it unfinished, which is exactly what the startup sweep
    # looks for (HARDENING P0.4).
    if recorder.manifest is not None:
        recorder.manifest.outputs = [
            {
                "path": str(a.path), "kind": a.kind.value,
                "parentProjectId": a.lineage.parent_project_id if a.lineage else None,
                "parentHash": a.lineage.parent_hash if a.lineage else None,
                "operationSetId": a.lineage.operation_set_id if a.lineage else None,
            }
            for a in recorder.artifacts
        ]
        recorder.manifest.finish(validation_level)
    return result


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _digest(model: object) -> str:
    """Content hash of a model, for stage input/output hashes."""
    import hashlib

    payload = model.model_dump_json() if hasattr(model, "model_dump_json") else json.dumps(model, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def configuration_hash(options: BuildOptions) -> str:
    """The choices that shape a build; a resumed stage needs the same ones."""
    import hashlib

    fields = {
        "arrange": options.arrange, "extract": options.extract, "genre": options.genre,
        "structure": options.structure, "level": int(options.level),
        "variant": options.variant, "seed": options.seed,
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _resumable(resume_from: Path | None, stage: PipelineStage, input_hash: str,
               config_hash: str) -> tuple[bool, dict[str, Any]]:
    """Whether an earlier build's record for ``stage`` can be reused.

    Reused only when the same bytes were analysed the same way with the same
    choices: input_hash, analysis_version and configuration_hash all equal.
    """
    if resume_from is None:
        return False, {}
    try:
        data = json.loads((Path(resume_from) / "job.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, {}
    for rec in data.get("pipeline") or []:
        if rec.get("stage") != stage.value:
            continue
        ok = (
            rec.get("state") in ("COMPLETED", "RESUMED")
            and rec.get("input_hash") == input_hash
            and rec.get("analysis_version") == ANALYSIS_VERSION
            and rec.get("configuration_hash") == config_hash
        )
        return ok, data
    return False, data


def _reused(resume_from: Path | None, stage: PipelineStage, input_hash: str,
            config_hash: str, output_hash: str) -> bool:
    """Whether a model the caller handed in is byte-for-byte the earlier build's.

    The caller may pre-load project.json/analysis.json from the interrupted
    folder; the stage is recorded RESUMED only when the earlier record matches
    on input, configuration and output hashes, never on the caller's word.
    """
    ok, data = _resumable(resume_from, stage, input_hash, config_hash)
    if not ok:
        return False
    rec = next((r for r in data.get("pipeline") or [] if r.get("stage") == stage.value), {})
    return rec.get("output_hash") == output_hash


def _op_result(index: int, mutations: tuple[MutationOp, ...]) -> str:
    """What became of one Layer B op, from the mutations compiled from it."""
    mine = [m for m in mutations if m.from_op == index]
    if not mine:
        return "compiled to nothing"
    applied = sum(1 for m in mine if (m.result or "").startswith("applied"))
    return f"{applied} of {len(mine)} mutations applied"


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


def _dump_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


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
