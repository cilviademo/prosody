"""Stage functions. Pure: (paths/models in) -> (paths/models out), no globals.

The CLI does nothing but parse arguments and call one of these.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from prosody_core.classify.rules import analyse
from prosody_core.fs.safety import ReadOnlyCorpus, find_flps, output_dir
from prosody_core.health.check import check_project, classify_state
from prosody_core.model.schemas import Analysis, BeatProject, HealthReport
from prosody_core.obs.log import RunLog, run_log
from prosody_core.parse.adapter import ParseError, ParserBackend
from prosody_core.parse.pyflp_backend import PyFLPBackend


def default_backend() -> ParserBackend:
    return PyFLPBackend()


@dataclass(frozen=True)
class InspectResult:
    """One project, fully inspected, plus where its artefacts were written."""

    project: BeatProject
    analysis: Analysis
    health: HealthReport
    out_dir: Path | None


@dataclass(frozen=True)
class ScanRow:
    """One row of the scan report. ``error`` is set iff parsing failed."""

    path: Path
    sha256: str
    ok: bool
    fl_version: str | None = None
    tempo: float | None = None
    ppq: int | None = None
    patterns: int | None = None
    channels: int | None = None
    playlist_items: int | None = None
    notes: int | None = None
    warnings: int | None = None
    health: str | None = None
    error: str | None = None


def inspect_project(
    source: Path,
    *,
    out_root: Path | None = None,
    backend: ParserBackend | None = None,
    can_check_plugins: bool = False,
    log: RunLog | None = None,
) -> InspectResult:
    """Parse one .flp and derive analysis + health. Writes nothing unless
    ``out_root`` is given, and never touches ``source``.
    """
    source = Path(source)
    backend = backend or default_backend()
    guard = ReadOnlyCorpus.snapshot([source])

    project = backend.parse(source)
    state = classify_state(project)
    analysis = analyse(project, state)
    health = check_project(project, can_check_plugins=can_check_plugins, source=source)

    if log is not None:
        log.op(
            "PARSE_FLP",
            path=source,
            sha256=project.id,
            backend=project.backend,
            tempo=project.tempo,
            patterns=len(project.patterns),
            warnings=len(project.parse_warnings),
            health=health.status.value,
        )

    out_dir: Path | None = None
    if out_root is not None:
        out_dir = write_artifacts(project, analysis, health, out_root)
        if log is not None:
            log.op("WRITE_ARTIFACTS", out_dir=out_dir)

    # The source must be byte-identical to what we started from.
    guard.verify()
    return InspectResult(
        project=project, analysis=analysis, health=health, out_dir=out_dir
    )


def write_artifacts(
    project: BeatProject,
    analysis: Analysis,
    health: HealthReport,
    out_root: Path,
) -> Path:
    """Write DATA/ and REPORTS/ for one project under ``out/<slug>/``."""
    target = output_dir(Path(out_root), Path(project.source_path))
    data = target / "DATA"
    reports = target / "REPORTS"
    data.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)

    _dump(data / "project.json", project)
    _dump(data / "analysis.json", analysis)
    _dump(reports / "health.json", health)

    missing = reports / "missing-files.txt"
    missing.write_text(
        "".join(f"{asset.identifier}\n" for asset in health.missing_assets),
        encoding="utf-8",
    )
    plugins = reports / "plugins.txt"
    plugins.write_text(
        "".join(f"{plugin.name}\n" for plugin in project.plugins), encoding="utf-8"
    )
    return target


def scan_directory(
    root: Path,
    *,
    out_root: Path,
    backend: ParserBackend | None = None,
    write_artifacts_per_project: bool = False,
    can_check_plugins: bool = False,
) -> list[ScanRow]:
    """Parse every .flp under ``root``. One bad file never stops the batch.

    The whole set is hashed up front and re-verified at the end, so the command
    can prove it did not modify the corpus.
    """
    backend = backend or default_backend()
    paths = find_flps(Path(root))
    guard = ReadOnlyCorpus.snapshot(paths)
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    rows: list[ScanRow] = []
    with run_log(out_root / "scan.log") as log:
        log.op("SCAN_BEGIN", root=str(root), files=len(paths), backend=backend.name)
        for path in paths:
            digest = guard.digest(path)
            try:
                result = inspect_project(
                    path,
                    out_root=out_root if write_artifacts_per_project else None,
                    backend=backend,
                    can_check_plugins=can_check_plugins,
                    log=log,
                )
            except ParseError as exc:
                log.op("PARSE_FAILED", path=path, error=str(exc.cause))
                rows.append(
                    ScanRow(path=path, sha256=digest, ok=False,
                            error=f"{type(exc.cause).__name__}: {exc.cause}")
                )
                continue
            except Exception as exc:  # noqa: BLE001 - one bad file must not kill the batch
                log.op("PARSE_CRASHED", path=path, error=repr(exc))
                rows.append(
                    ScanRow(path=path, sha256=digest, ok=False,
                            error=f"{type(exc).__name__}: {exc}")
                )
                continue

            project = result.project
            rows.append(
                ScanRow(
                    path=path,
                    sha256=digest,
                    ok=True,
                    fl_version=project.fl_version,
                    tempo=project.tempo,
                    ppq=project.ppq,
                    patterns=len(project.patterns),
                    channels=len(project.channels),
                    playlist_items=sum(len(a.clips) for a in project.arrangements),
                    notes=project.note_count,
                    warnings=len(project.parse_warnings),
                    health=result.health.status.value,
                )
            )
        log.op("SCAN_END", parsed=sum(1 for r in rows if r.ok), total=len(rows))

    guard.verify()
    return rows


SCAN_COLUMNS = (
    "path", "sha256", "ok", "fl_version", "tempo", "ppq", "patterns",
    "channels", "playlist_items", "notes", "warnings", "health", "error",
)


def write_scan_report(rows: list[ScanRow], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCAN_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: _cell(getattr(row, c)) for c in SCAN_COLUMNS})
    return path


def write_scan_errors(rows: list[ScanRow], path: Path) -> Path:
    """Every failure, verbatim (EXECUTE.md T1)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    failures = [r for r in rows if not r.ok]
    path.write_text(
        "".join(f"{r.path}\n    {r.error}\n" for r in failures), encoding="utf-8"
    )
    return path


def _cell(value: object) -> object:
    return "" if value is None else value


def _dump(path: Path, model: BeatProject | Analysis | HealthReport) -> None:
    path.write_text(
        json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
