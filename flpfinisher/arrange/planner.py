"""Deterministic arrangement planning.

Given a parsed project, its role analysis and a genre profile, produce an
``ArrangementPlan``: a section grammar filled with the project's *existing*
patterns. Identical inputs always produce an identical plan; the seed only
varies which of several equally valid choices a variant takes.

The unit of arrangement at Level 0 is the **pattern**, because Level 0 may not
split or edit pattern content. Each pattern is assigned a primary role from its
channels, and a section plays a pattern when that role is active. A pattern
mixing drums and melody therefore moves as one block - a real limitation of
preserving composition, reported rather than worked around.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from flpfinisher.arrange.energy import active_roles, dropout_bars
from flpfinisher.model.roles import DRUM_ROLES, Role
from flpfinisher.model.schemas import (
    Analysis,
    ArrangementPlan,
    BeatProject,
    GenreProfile,
    PermissionLevel,
    PlaylistOp,
    Section,
    SectionType,
)

DEFAULT_STRUCTURE = "balanced"


class PlanningError(RuntimeError):
    """The project does not contain enough material to arrange."""


@dataclass(frozen=True)
class PatternRole:
    """A source pattern and the role it primarily carries."""

    pattern: int
    name: str
    role: Role
    roles: tuple[Role, ...]
    length_ticks: int
    note_count: int

    @property
    def is_drums(self) -> bool:
        return self.role in DRUM_ROLES


def pattern_roles(project: BeatProject, analysis: Analysis) -> tuple[PatternRole, ...]:
    """Assign each non-empty pattern a primary role, weighted by note count."""
    by_channel = {
        a.channel: a for a in analysis.roles if a.channel is not None
    }

    out: list[PatternRole] = []
    for pattern in project.patterns:
        if not pattern.notes:
            continue
        weight: defaultdict[Role, float] = defaultdict(float)
        for note in pattern.notes:
            assignment = by_channel.get(note.channel)
            if assignment is None or assignment.role is Role.UNKNOWN:
                continue
            # Weight by confidence so an uncertain channel does not capture a
            # pattern from a confident one.
            weight[assignment.role] += max(assignment.confidence, 0.05)

        if not weight:
            primary, roles = Role.UNKNOWN, ()
        else:
            primary = max(weight.items(), key=lambda kv: kv[1])[0]
            roles = tuple(sorted(weight, key=lambda r: -weight[r]))

        length = pattern.length_ticks or max(
            (n.position + n.length for n in pattern.notes), default=0
        )
        out.append(
            PatternRole(
                pattern=pattern.index,
                name=pattern.name or f"Pattern {pattern.index}",
                role=primary,
                roles=roles,
                length_ticks=length,
                note_count=len(pattern.notes),
            )
        )
    return tuple(out)


def parse_grammar(entries: tuple[str, ...]) -> list[tuple[SectionType, int]]:
    """``["intro:4", "hook:8"]`` -> ``[(INTRO, 4), (HOOK, 8)]``."""
    parsed: list[tuple[SectionType, int]] = []
    for entry in entries:
        name, _, bars = entry.partition(":")
        parsed.append((SectionType(name), int(bars)))
    return parsed


def _loop_bars(project: BeatProject, patterns: tuple[PatternRole, ...]) -> int:
    """How many bars the source material naturally occupies."""
    beats_per_bar = project.time_signature[0] or 4
    ticks_per_bar = max(project.ppq * beats_per_bar, 1)
    longest = max((p.length_ticks for p in patterns), default=0)
    return max(round(longest / ticks_per_bar) or 1, 1)


def build_plan(
    project: BeatProject,
    analysis: Analysis,
    profile: GenreProfile,
    *,
    structure: str = DEFAULT_STRUCTURE,
    level: PermissionLevel = PermissionLevel.STRUCTURE_ONLY,
    variant: str = "A",
    seed: int = 0,
) -> ArrangementPlan:
    """Turn a loop into a song structure using only its existing patterns."""
    patterns = pattern_roles(project, analysis)
    if not patterns:
        raise PlanningError(
            "This project has no patterns with notes, so there is nothing to "
            "arrange. Try Extract instead."
        )

    grammar = profile.grammar.get(structure) or profile.grammar[DEFAULT_STRUCTURE]
    entries = parse_grammar(grammar)

    available = {p.role for p in patterns if p.role is not Role.UNKNOWN}
    if not available:
        # Nothing classified confidently: arrange everything as one block
        # rather than refusing. Honest degradation, reported in the plan.
        available = {Role.UNKNOWN}

    first_index: dict[SectionType, int] = {}
    for index, (section_type, _) in enumerate(entries):
        first_index.setdefault(section_type, index)

    rng = random.Random(seed)
    loop_bars = _loop_bars(project, patterns)

    # One playlist track per pattern, so nothing overlaps on a shared lane.
    track_of = {p.pattern: i for i, p in enumerate(patterns)}

    sections: list[Section] = []
    ops: list[PlaylistOp] = []
    bar = 1

    for index, (section_type, bars) in enumerate(entries):
        energy = profile.energy_for(section_type)
        if variant != "A":
            # Variants nudge energy slightly; the grammar itself is unchanged so
            # the song remains recognisable.
            energy = min(1.0, max(0.0, energy + rng.choice((-0.1, 0.0, 0.1))))

        roles = active_roles(
            profile, section_type, energy, available,
            section_index=index, first_index=first_index,
        )
        next_type = entries[index + 1][0] if index + 1 < len(entries) else None
        drop = dropout_bars(profile, next_type, bars)

        for pattern in patterns:
            role = pattern.role if pattern.role is not Role.UNKNOWN else Role.UNKNOWN
            if role not in roles and not (role is Role.UNKNOWN and Role.UNKNOWN in roles):
                continue
            # Drums stop early where the genre wants a transition.
            span = bars - drop if (drop and pattern.is_drums) else bars
            if span <= 0:
                continue
            ops.append(
                PlaylistOp(
                    op="tile", role=pattern.role, pattern=pattern.pattern,
                    track=track_of[pattern.pattern], start_bar=bar, bars=span,
                )
            )

        ops.append(
            PlaylistOp(op="marker", start_bar=bar, bars=bars, role=None)
        )
        sections.append(
            Section(
                name=section_type, start_bar=bar, bars=bars, energy=round(energy, 3),
                active_roles=roles, dropout_bars=drop,
            )
        )
        bar += bars

    total_bars = bar - 1
    notes = _describe(patterns, available, loop_bars)

    return ArrangementPlan(
        variant=variant,
        genre=profile.genre,
        structure=structure,
        level=level,
        seed=seed,
        source_project_id=project.id,
        tempo=project.tempo or 120.0,
        total_bars=total_bars,
        sections=tuple(sections),
        ops=tuple(ops),
        llm_notes=notes,
    )


def _describe(
    patterns: tuple[PatternRole, ...], available: set[Role], loop_bars: int
) -> str:
    mixed = [p for p in patterns if len(p.roles) > 1]
    parts = [
        f"{len(patterns)} source patterns over {loop_bars} bars; "
        f"roles present: {', '.join(sorted(r.value for r in available))}."
    ]
    if mixed:
        names = ", ".join(p.name for p in mixed[:3])
        parts.append(
            f"{len(mixed)} pattern(s) mix several roles ({names}) and move as "
            "one block at this creativity level."
        )
    return " ".join(parts)


def build_variants(
    project: BeatProject,
    analysis: Analysis,
    profile: GenreProfile,
    *,
    structure: str = DEFAULT_STRUCTURE,
    level: PermissionLevel = PermissionLevel.STRUCTURE_ONLY,
    count: int = 3,
    seed: int = 1234,
) -> tuple[ArrangementPlan, ...]:
    """A/B/C variants of the same grammar. Variant A is always the plain one."""
    letters = "ABCDEFG"[:count]
    return tuple(
        build_plan(
            project, analysis, profile, structure=structure, level=level,
            variant=letter, seed=seed + i,
        )
        for i, letter in enumerate(letters)
    )
