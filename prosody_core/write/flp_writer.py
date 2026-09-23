"""Write a derivative .flp by rewriting only its playlist.

The source is never touched. We read it into a verbatim event stream, replace
the playlist event's payload with clips generated from an ``ArrangementPlan``,
add playlist tracks and section markers if needed, and write the result to a new
versioned filename.

Every other event - channels, plugins, patterns, notes, mixer, routing,
automation, samples, and events no parser recognises - is copied byte for byte.
That is what makes Preserve Composition a structural guarantee rather than a
promise: at Level 0 the writer has no code path that can alter a note.

If anything cannot be expressed safely, the writer says so and the caller falls
back to an Arrangement Pack. It never writes a file it could not verify.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from prosody_core.arrange import compile as compile_module
from prosody_core.arrange.permissions import assert_plan_allowed
from prosody_core.fs.source import assert_not_the_source
from prosody_core.model.schemas import (
    ArrangementPlan,
    BeatProject,
    MutationKind,
    MutationOp,
    PermissionLevel,
)
from prosody_core.write.eventstream import Event, FLPFile, read_flp, write_flp

# Event ids used here.
ID_ARRANGEMENT_NEW = 99
ID_ARRANGEMENT_NAME = 241
ID_PLAYLIST = 233
ID_TRACK_NAME = 239
ID_TRACK_DATA = 238
ID_ARRANGEMENTS_CURRENT = 100
ID_TIMEMARKER_POSITION = 148
ID_TIMEMARKER_NAME = 205

PATTERN_BASE = 20480
MAX_TRACK_INDEX = 499

ITEM_LEGACY = 32
ITEM_MODERN = 60

_ITEM_HEAD = struct.Struct("<IHHIHH2sH4sff")


class WriteUnsupported(RuntimeError):
    """This project cannot be rewritten safely. Caller should fall back."""


@dataclass
class WriteReport:
    """What the writer did, for the operation log and the UI."""

    output: Path
    clips_written: int = 0
    tracks_added: int = 0
    markers_written: int = 0
    item_size: int = ITEM_LEGACY
    operations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Layer C, with a result on each (ARCHITECTURE_NOTES item 3).
    mutations: tuple[MutationOp, ...] = ()

    def log(self, message: str) -> None:
        self.operations.append(message)


def _text(value: str) -> bytes:
    return value.encode("utf-16-le") + b"\x00\x00"


def detect_item_size(flp: FLPFile) -> tuple[int, bytes]:
    """Playlist item size in this file, plus a template tail for modern items.

    PyFLP decides the format with ``not len(data) % 60``. Matching whatever the
    source already uses avoids that ambiguity entirely.
    """
    index = flp.index_of(ID_PLAYLIST)
    if index is None:
        return ITEM_LEGACY, b""

    payload = flp.events[index].payload
    if payload and len(payload) % ITEM_MODERN == 0:
        # Reuse an existing item's trailing bytes rather than inventing them.
        return ITEM_MODERN, payload[_ITEM_HEAD.size:ITEM_MODERN]
    if payload and len(payload) % ITEM_LEGACY == 0:
        return ITEM_LEGACY, b""
    return ITEM_LEGACY, b""


def build_clip(
    *, position_ticks: int, pattern: int, length_ticks: int, track: int,
    item_size: int, tail: bytes,
) -> bytes:
    head = _ITEM_HEAD.pack(
        position_ticks,
        PATTERN_BASE,
        PATTERN_BASE + pattern,
        length_ticks,
        MAX_TRACK_INDEX - track,
        0,
        b"\x78\x00",
        64,
        bytes([64, 100, 128, 128]),
        0.0,
        0.0,
    )
    if item_size == ITEM_MODERN:
        pad = tail if len(tail) == ITEM_MODERN - _ITEM_HEAD.size else b"\x00" * 28
        return head + pad
    return head


def _pattern_lengths(project: BeatProject) -> dict[int, int]:
    """Kept for callers; the arithmetic lives in arrange.compile."""
    return compile_module.pattern_lengths(project)


def plan_to_clips(
    plan: ArrangementPlan, project: BeatProject
) -> list[tuple[int, int, int, int]]:
    """(position, pattern, length, track) clips — Layer C, as the writer sees it.

    Compiled by ``arrange.compile.compile_plan``; the writer no longer derives
    anything from a Layer B op itself (ARCHITECTURE_NOTES item 3).
    """
    return compile_module.clips_from(compile_module.compile_plan(plan, project))


def _ensure_tracks(flp: FLPFile, needed: int, report: WriteReport) -> None:
    """Append playlist track definitions until ``needed`` tracks exist."""
    existing = flp.count(ID_TRACK_DATA)
    if existing >= needed:
        return

    insert_at = max(flp.indexes_of(ID_TRACK_DATA) or [-1]) + 1
    if insert_at == 0:
        anchor = flp.index_of(ID_PLAYLIST) or flp.index_of(ID_ARRANGEMENT_NAME)
        if anchor is None:
            raise WriteUnsupported(
                "this project has no playlist or arrangement events to extend"
            )
        insert_at = anchor + 1

    new_events: list[Event] = []
    for index in range(existing, needed):
        new_events.append(Event(ID_TRACK_NAME, _text(f"Track {index + 1}")))
        new_events.append(
            Event(ID_TRACK_DATA, struct.pack("<IIIB", index + 1, 0, 0, 1))
        )
    flp.events[insert_at:insert_at] = new_events
    report.tracks_added = needed - existing
    report.log(f"ADD_PLAYLIST_TRACKS count={report.tracks_added}")


def _write_markers(
    flp: FLPFile, mutations: tuple[MutationOp, ...], report: WriteReport
) -> None:
    """One named time marker per WRITE_MARKER mutation, before the track list."""
    # Drop markers the source already had, so rebuilding is idempotent.
    flp.events = [
        e for e in flp.events
        if e.id not in (ID_TIMEMARKER_POSITION, ID_TIMEMARKER_NAME)
    ]

    anchor = flp.index_of(ID_PLAYLIST)
    if anchor is None:
        return
    insert_at = anchor + 1

    events: list[Event] = []
    written = 0
    for m in mutations:
        if m.kind is not MutationKind.WRITE_MARKER:
            continue
        events.append(Event(ID_TIMEMARKER_POSITION, struct.pack("<I", m.start_tick)))
        events.append(Event(ID_TIMEMARKER_NAME, _text(m.label or "SECTION")))
        m.result = "applied"
        written += 1
    flp.events[insert_at:insert_at] = events
    report.markers_written = written
    report.log(f"WRITE_MARKERS count={report.markers_written}")


def write_arrangement(
    source: Path,
    destination: Path,
    plan: ArrangementPlan,
    project: BeatProject,
    *,
    markers: bool = True,
    protect: Path | None = None,
) -> WriteReport:
    """Produce a derivative .flp with the planned playlist.

    ``source`` is the file to read, which is normally a working copy in the
    cache. ``protect`` is the user's real original, which the destination is
    checked against — before anything is written, not after.

    Raises:
        WriteUnsupported: the project cannot be rewritten safely.
        PermissionDenied: the plan exceeds its creative level.
        SourceWouldBeModified: the destination resolves to a protected file.
    """
    # Second permission gate, immediately before any bytes are produced.
    assert_plan_allowed(plan)

    # Checked here, at the start, because a check after the write protects
    # nothing (HARDENING P0.3).
    assert_not_the_source(destination, Path(source))
    if protect is not None:
        assert_not_the_source(destination, Path(protect))

    flp = read_flp(source)
    report = WriteReport(output=Path(destination))

    if flp.index_of(ID_ARRANGEMENT_NEW) is None:
        raise WriteUnsupported("no arrangement found in the source project")

    item_size, tail = detect_item_size(flp)
    report.item_size = item_size
    if item_size == ITEM_MODERN and not tail:
        report.warnings.append(
            "source uses FL 21 playlist items but carries none to copy; "
            "new clips use zeroed trailing fields"
        )

    mutations = compile_module.compile_plan(plan, project)
    clips = compile_module.clips_from(mutations)
    report.mutations = mutations
    if not clips:
        raise WriteUnsupported(
            "the plan produced no playlist clips for this project's patterns"
        )

    highest_track = max(track for _, _, _, track in clips)
    _ensure_tracks(flp, highest_track + 1, report)

    payload = b"".join(
        build_clip(
            position_ticks=position, pattern=pattern, length_ticks=length,
            track=track, item_size=item_size, tail=tail,
        )
        for position, pattern, length, track in clips
    )

    index = flp.index_of(ID_PLAYLIST)
    if index is None:
        anchor = flp.index_of(ID_ARRANGEMENT_NAME) or flp.index_of(ID_ARRANGEMENT_NEW)
        flp.events.insert(anchor + 1, Event(ID_PLAYLIST, payload))
        report.log("CREATE_PLAYLIST")
    else:
        flp.events[index] = Event(ID_PLAYLIST, payload)
        report.log("REPLACE_PLAYLIST")

    report.clips_written = len(clips)
    for m in mutations:
        if m.kind is MutationKind.PLACE_PLAYLIST_INSTANCE:
            m.result = "applied"
        elif m.kind is MutationKind.OMIT_PLAYLIST_INSTANCE:
            m.result = "applied: placements within the span were omitted"
    for op in plan.ops:
        if op.op == "tile":
            report.log(
                f"TILE_PATTERN pattern={op.pattern} role="
                f"{op.role.value if op.role else '-'} start_bar={op.start_bar} "
                f"bars={op.bars} track={op.track}"
            )

    if markers:
        try:
            _write_markers(flp, mutations, report)
        except Exception as exc:  # noqa: BLE001 - markers are optional
            report.warnings.append(f"section markers not written: {exc}")
            for m in mutations:
                if m.kind is MutationKind.WRITE_MARKER and m.result is None:
                    m.result = f"skipped: {exc}"
    else:
        for m in mutations:
            if m.kind is MutationKind.WRITE_MARKER:
                m.result = "skipped: markers disabled"

    # Final gate inside the writer itself, so no caller can bypass it.
    write_flp(flp, Path(destination), source=Path(protect or source))
    report.log(f"SAVE path={destination} clips={len(clips)}")
    return report


def level_permits_note_edits(level: PermissionLevel) -> bool:
    return level is not PermissionLevel.STRUCTURE_ONLY
