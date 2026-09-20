"""Project health: what we know, what we don't, and what that implies.

The governing rule (product brief section 10) is *never hide uncertainty*. A
check whose answer cannot be determined on this machine reports ``ok=None`` and
drags the overall status toward ``UNKNOWN`` rather than quietly passing.

Plugin availability is the clearest example: it can only be answered on the
studio PC with FL installed, so everywhere else it is honestly undetermined.
"""

from __future__ import annotations

from flpfinisher.model.schemas import (
    BeatProject,
    HealthCheck,
    HealthReport,
    HealthStatus,
    MissingAsset,
    ProjectState,
    Severity,
)

#: Human wording for each status. Raw enum names never reach a primary
#: surface; they stay in diagnostics where the precision is wanted.
STATUS_LABELS: dict[HealthStatus, str] = {
    HealthStatus.READY: "Ready",
    HealthStatus.PARTIAL: "Partly readable",
    HealthStatus.REQUIRES_FREEZE: "Missing samples",
    HealthStatus.BLOCKED: "Cannot be used",
    HealthStatus.UNKNOWN: "Ready to analyse",
}


def human_status(status: HealthStatus) -> str:
    return STATUS_LABELS.get(status, status.value)


def classify_state(project: BeatProject) -> ProjectState:
    """How finished the source project looks, from structure alone."""
    if not project.channels and not project.patterns:
        return ProjectState.EMPTY
    if not project.note_count and not any(a.clips for a in project.arrangements):
        return ProjectState.EMPTY

    clips = [clip for a in project.arrangements for clip in a.clips]
    if not clips:
        return ProjectState.LOOP

    bars = project.length_bars
    if bars <= 8:
        return ProjectState.LOOP
    if bars < 32:
        return ProjectState.PARTIAL
    return ProjectState.ARRANGED


def check_project(
    project: BeatProject, *, can_check_plugins: bool = False
) -> HealthReport:
    """Compute a health report from an already-parsed project.

    Args:
        project: The normalised project.
        can_check_plugins: True only where FL Studio and the VST folders are
            present. When False, plugin availability is reported as undetermined
            instead of assumed.
    """
    checks: list[HealthCheck] = []
    missing: list[MissingAsset] = []

    checks.append(
        HealthCheck(name="flp_readable", ok=True,
                    detail=f"parsed by {project.backend}")
    )
    checks.append(
        HealthCheck(
            name="fl_version",
            ok=project.fl_version is not None,
            detail=project.fl_version or "not recorded in the file header",
        )
    )
    checks.append(
        HealthCheck(
            name="tempo",
            ok=project.tempo is not None,
            detail=f"{project.tempo} BPM" if project.tempo else "no tempo event found",
        )
    )
    checks.append(
        HealthCheck(
            name="patterns",
            ok=bool(project.patterns),
            detail=f"{len(project.patterns)} patterns, {project.note_count} notes",
        )
    )
    checks.append(
        HealthCheck(
            name="channels",
            ok=bool(project.channels),
            detail=f"{len(project.channels)} channels",
        )
    )

    clip_count = sum(len(a.clips) for a in project.arrangements)
    checks.append(
        HealthCheck(
            name="playlist",
            ok=clip_count > 0,
            detail=f"{clip_count} clips across {len(project.arrangements)} arrangements",
        )
    )

    found = sum(1 for s in project.samples if s.found)
    absent = [s for s in project.samples if not s.found]
    for sample in absent:
        missing.append(
            MissingAsset(kind="sample", identifier=sample.path,
                         detail="path does not resolve on this machine")
        )
    checks.append(
        HealthCheck(
            name="samples",
            ok=not absent if project.samples else True,
            detail=f"{found} found, {len(absent)} missing of {len(project.samples)}",
        )
    )

    # Plugin availability is only answerable where FL Studio and the VST folders
    # exist. Anywhere else it is undetermined, not "fine".
    checks.append(
        HealthCheck(
            name="plugins_available",
            ok=True if can_check_plugins else None,
            detail=(
                f"{len(project.plugins)} plugins referenced"
                if can_check_plugins
                else f"{len(project.plugins)} plugins referenced; availability is not "
                     "checkable without FL Studio on this machine"
            ),
        )
    )

    errors = [w for w in project.parse_warnings if w.severity is Severity.ERROR]
    warnings = [w for w in project.parse_warnings if w.severity is Severity.WARNING]
    notes = [w for w in project.parse_warnings if w.severity is Severity.INFO]
    checks.append(
        HealthCheck(
            name="parse_clean",
            # INFO notices record what this file cannot describe, not damage.
            ok=not (errors or warnings),
            detail=(
                "no degradation"
                if not project.parse_warnings
                else f"{len(errors)} errors, {len(warnings)} warnings, {len(notes)} notes"
            ),
        )
    )

    checks.append(
        HealthCheck(
            name="write_compatibility",
            ok=None,
            detail="PyFLP save round-trip unverified - Phase 0 spike T2 not yet run "
                   "against a real corpus",
        )
    )

    status = _status(checks, has_missing=bool(absent))
    return HealthReport(
        project_id=project.id,
        status=status,
        checks=tuple(checks),
        samples_found=found,
        samples_missing=len(absent),
        missing_assets=tuple(missing),
        render_test="skipped",
        recommended_mode="stem" if absent else "native",
        notes=(
            "Render validation was not attempted; set FLPF_RENDER=1 on the studio "
            "PC to enable it.",
        ),
    )


def _status(checks: list[HealthCheck], *, has_missing: bool) -> HealthStatus:
    by_name = {c.name: c for c in checks}

    def failed(name: str) -> bool:
        return by_name[name].ok is False

    if failed("flp_readable") or (failed("patterns") and failed("channels")):
        return HealthStatus.BLOCKED
    if has_missing:
        return HealthStatus.REQUIRES_FREEZE
    if failed("tempo") or failed("parse_clean") or failed("patterns"):
        return HealthStatus.PARTIAL
    if any(c.ok is None for c in checks):
        # Something material could not be determined here. Say so.
        return HealthStatus.UNKNOWN
    return HealthStatus.READY
