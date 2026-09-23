"""Layer B → Layer C: bars and intent become ticks and playlist items.

ARCHITECTURE_NOTES item 3. A planner — rules or AI — produces semantic
operations in bars. This module, and nothing else, turns them into the
concrete playlist mutations the writer applies. It is deterministic: the
same plan and project always compile to the same mutations, and the AI never
gets closer to the file than the plan.

The arithmetic here is the writer's, moved verbatim so the derivative is
identical to what it was before the layers were named.
"""

from __future__ import annotations

from prosody_core.model.schemas import (
    ArrangementPlan,
    BeatProject,
    MutationKind,
    MutationOp,
)


def ticks_per_bar(project: BeatProject) -> int:
    beats_per_bar = project.time_signature[0] or 4
    return max(project.ppq * beats_per_bar, 1)


def pattern_lengths(project: BeatProject) -> dict[int, int]:
    """Tiling length per pattern, rounded up to a whole number of bars.

    A pattern's measured extent is where its last note *ends*, which is
    almost never a bar line: a four-bar kick whose final hit is a 16th long
    measures 1464 ticks, not 1536. Tiling at the measured length would slide
    every repetition earlier than the beat, and the drift compounds across an
    80-bar arrangement. FL snaps playlist clips to the grid, so we do too.
    """
    tpb = ticks_per_bar(project)
    lengths: dict[int, int] = {}
    for pattern in project.patterns:
        measured = pattern.length_ticks or max(
            (n.position + n.length for n in pattern.notes), default=0
        )
        if not measured:
            continue
        bars = max(1, -(-measured // tpb))  # ceil division
        lengths[pattern.index] = bars * tpb
    return lengths


def compile_plan(plan: ArrangementPlan, project: BeatProject) -> tuple[MutationOp, ...]:
    """Every Layer C mutation the plan implies, in file order.

    ``tile`` expands to one placement per whole repetition — never a
    stretched clip, so nothing depends on FL's clip looping — and a remainder
    shorter than the pattern is dropped rather than truncated, because
    trimming a clip is not a Level 0 operation. ``place`` and
    ``duplicate_pattern`` are single placements; ``mute`` and ``dropout``
    are omissions over a span, applied to placements on the same track;
    ``marker`` writes a named marker at a bar. Unknown ops compile to nothing
    and say so in their result.
    """
    tpb = ticks_per_bar(project)
    lengths = pattern_lengths(project)
    out: list[MutationOp] = []

    for index, op in enumerate(plan.ops):
        start = ((op.start_bar or 1) - 1) * tpb
        span = (op.bars or 0) * tpb
        track = op.track if op.track is not None else 0

        if op.op == "tile":
            if op.pattern is None or not lengths.get(op.pattern):
                continue
            length = lengths[op.pattern]
            position = start
            while position + length <= start + span:
                out.append(MutationOp(
                    kind=MutationKind.PLACE_PLAYLIST_INSTANCE, from_op=index,
                    pattern_id=op.pattern, track=track,
                    start_tick=position, end_tick=position + length,
                ))
                position += length
        elif op.op in ("place", "duplicate_pattern"):
            if op.pattern is None or not lengths.get(op.pattern):
                continue
            length = lengths[op.pattern]
            out.append(MutationOp(
                kind=MutationKind.PLACE_PLAYLIST_INSTANCE, from_op=index,
                pattern_id=op.pattern, track=track,
                start_tick=start, end_tick=start + (span or length),
            ))
        elif op.op in ("mute", "dropout"):
            out.append(MutationOp(
                kind=MutationKind.OMIT_PLAYLIST_INSTANCE, from_op=index,
                pattern_id=op.pattern, track=op.track,
                start_tick=start, end_tick=start + span,
            ))
        elif op.op == "marker":
            section = next(
                (s for s in plan.sections if s.start_bar == op.start_bar), None
            )
            out.append(MutationOp(
                kind=MutationKind.WRITE_MARKER, from_op=index,
                start_tick=start, end_tick=start,
                label=(section.name.value if section else "SECTION").upper(),
            ))

    # Omissions remove the placements they cover on the same track (any
    # track when none is named), then are kept as a record of having done so.
    omissions = [m for m in out if m.kind is MutationKind.OMIT_PLAYLIST_INSTANCE]
    if omissions:
        kept: list[MutationOp] = []
        for m in out:
            if m.kind is MutationKind.PLACE_PLAYLIST_INSTANCE and any(
                (o.track is None or o.track == m.track)
                and (o.pattern_id is None or o.pattern_id == m.pattern_id)
                and m.start_tick >= o.start_tick and m.end_tick <= o.end_tick
                for o in omissions
            ):
                continue
            kept.append(m)
        out = kept

    placements = sorted(
        (m for m in out if m.kind is MutationKind.PLACE_PLAYLIST_INSTANCE),
        key=lambda m: (m.start_tick, m.pattern_id or 0, m.end_tick, m.track or 0),
    )
    others = [m for m in out if m.kind is not MutationKind.PLACE_PLAYLIST_INSTANCE]
    return tuple(placements + others)


def clips_from(mutations: tuple[MutationOp, ...]) -> list[tuple[int, int, int, int]]:
    """``(position, pattern, length, track)`` for every placement — the writer's shape."""
    return [
        (m.start_tick, m.pattern_id or 0, m.end_tick - m.start_tick, m.track or 0)
        for m in mutations
        if m.kind is MutationKind.PLACE_PLAYLIST_INSTANCE
    ]
