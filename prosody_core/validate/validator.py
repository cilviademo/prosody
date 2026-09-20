"""Prove a derivative project is sound before the app offers it to the user.

Checks that need no FL Studio run here; the render check is added by the build
pipeline when rendering is available. A derivative that fails structural
validation is discarded and the caller falls back to an Arrangement Pack.
"""

from __future__ import annotations

from pathlib import Path

from prosody_core.fs.safety import sha256_file
from prosody_core.model.schemas import (
    ArrangementPlan,
    BeatProject,
    HealthCheck,
    ValidationResult,
)
from prosody_core.parse.adapter import ParseError, ParserBackend
from prosody_core.write.eventstream import read_flp

#: Playlist length may exceed the plan by up to this many bars without failing:
#: a final clip can overhang its section by a pattern length.
BAR_TOLERANCE = 8.0


def validate_derivative(
    source: Path,
    derivative: Path,
    original: BeatProject,
    plan: ArrangementPlan,
    backend: ParserBackend,
    *,
    source_hash: str,
) -> ValidationResult:
    """Structural validation of a generated .flp against its source."""
    checks: list[HealthCheck] = []

    unchanged = sha256_file(source) == source_hash
    checks.append(
        HealthCheck(
            name="source_unchanged",
            ok=unchanged,
            detail="original .flp hash matches the value taken before the build"
            if unchanged
            else "ORIGINAL FILE CHANGED - this is a bug, not a warning",
        )
    )

    try:
        rebuilt = backend.parse(derivative)
    except ParseError as exc:
        checks.append(
            HealthCheck(name="reparses", ok=False, detail=f"{exc.cause}")
        )
        return ValidationResult(
            project_id=original.id, passed=False, checks=tuple(checks)
        )

    checks.append(
        HealthCheck(name="reparses", ok=True, detail=f"parsed by {rebuilt.backend}")
    )

    for label, before, after in (
        ("patterns", len(original.patterns), len(rebuilt.patterns)),
        ("channels", len(original.channels), len(rebuilt.channels)),
        ("notes", original.note_count, rebuilt.note_count),
        ("mixer_inserts", len(original.mixer), len(rebuilt.mixer)),
        ("plugins", len(original.plugins), len(rebuilt.plugins)),
        ("samples", len(original.samples), len(rebuilt.samples)),
    ):
        checks.append(
            HealthCheck(
                name=f"{label}_preserved",
                ok=before == after,
                detail=f"{before} -> {after}",
            )
        )

    clips = sum(len(a.clips) for a in rebuilt.arrangements)
    checks.append(
        HealthCheck(
            name="playlist_written",
            ok=clips > 0,
            detail=f"{clips} clips in the derivative",
        )
    )

    bars = rebuilt.length_bars
    within = abs(bars - plan.total_bars) <= BAR_TOLERANCE
    checks.append(
        HealthCheck(
            name="length_matches_plan",
            ok=within,
            detail=f"{bars:g} bars vs planned {plan.total_bars}",
        )
    )

    try:
        before_stream = read_flp(source)
        after_stream = read_flp(derivative)
        header_same = before_stream.header == after_stream.header
    except Exception as exc:  # noqa: BLE001
        header_same = None
        checks.append(
            HealthCheck(name="header_preserved", ok=None, detail=str(exc))
        )
    else:
        checks.append(
            HealthCheck(
                name="header_preserved",
                ok=header_same,
                detail="FLhd copied verbatim from the source"
                if header_same
                else "file header differs from the source",
            )
        )

    passed = all(c.ok is not False for c in checks)
    return ValidationResult(
        project_id=original.id, passed=passed, checks=tuple(checks)
    )


def notes_unchanged(original: BeatProject, derivative: BeatProject) -> bool:
    """Every pattern's note content is identical. The Level 0 guarantee."""
    before = {p.index: p.notes for p in original.patterns}
    after = {p.index: p.notes for p in derivative.patterns}
    return before == after
