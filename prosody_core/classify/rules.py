"""Tier-1 role hinting from channel and pattern names only.

This is **not** the Phase 5 classifier. It reads names and nothing else, so it
is wrong whenever a producer names a channel ``asdf`` or ``Pattern 3`` - which
SPEC.md section 10 lists as a certainty, not a risk.

It exists because the first deliverable asks for "inferred musical roles where
confidence is sufficient", and because having the plumbing (a RoleAssignment
carrying confidence, method and sources) under test now means the real
classifier slots in behind the same contract later.

Confidence is capped below :data:`CONFIDENCE_THRESHOLD` for every guess that is
not an exact vocabulary match, so nothing here can be mistaken for fact. The
real signals - pitch range, polyphony, note density, channel kind, plugin,
sample filename - arrive in Phase 5.
"""

from __future__ import annotations

import re

from prosody_core.model.roles import ROLE_ALIASES, Role, normalise_role
from prosody_core.model.schemas import (
    Analysis,
    BeatProject,
    ClassificationMethod,
    ProjectState,
    RoleAssignment,
)

#: Substrings that suggest a role, longest-first so "open hat" beats "hat".
_NAME_HINTS: tuple[tuple[str, Role], ...] = tuple(
    sorted(
        (
            *((alias, role) for alias, role in ROLE_ALIASES.items()),
            *((role.value, role) for role in Role if role is not Role.UNKNOWN),
            ("drum", Role.PERC),
            ("shaker", Role.PERC),
            ("tom", Role.PERC),
            ("kik", Role.KICK),
            ("bd", Role.KICK),
            ("sd", Role.SNARE),
            ("hh", Role.HATS),
            ("string", Role.CHORDS),
            ("guitar", Role.MELODY),
            ("flute", Role.MELODY),
            ("bell", Role.MELODY),
            ("synth", Role.MELODY),
        ),
        key=lambda pair: -len(pair[0]),
    )
)

#: A name that is only "Pattern 4", "Insert 3", "Channel 1" or similar carries
#: no information at all, and must not produce even a weak guess.
_PLACEHOLDER = re.compile(
    r"^(pattern|insert|channel|track|audio|clip|untitled)\s*\d*$", re.IGNORECASE
)

_EXACT_CONFIDENCE = 0.65  # deliberately below CONFIDENCE_THRESHOLD (0.70)
_SUBSTRING_CONFIDENCE = 0.45


def role_from_name(name: str | None) -> tuple[Role, float, tuple[str, ...]]:
    """Guess a role from a name. Returns (role, confidence, sources)."""
    if not name or _PLACEHOLDER.match(name.strip()):
        return Role.UNKNOWN, 0.0, ()

    exact = normalise_role(name)
    if exact is not Role.UNKNOWN:
        return exact, _EXACT_CONFIDENCE, ("name_exact",)

    haystack = name.lower()
    for needle, role in _NAME_HINTS:
        if _matches(needle, haystack):
            return role, _SUBSTRING_CONFIDENCE, ("name_substring",)

    return Role.UNKNOWN, 0.0, ()


#: Hints this short match far too eagerly as bare substrings ("sd" in "asdf"),
#: so they only count as a whole word.
_SHORT_HINT_CHARS = 3


def _matches(needle: str, haystack: str) -> bool:
    if len(needle) > _SHORT_HINT_CHARS:
        return needle in haystack
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def hint_roles(project: BeatProject) -> tuple[RoleAssignment, ...]:
    """One RoleAssignment per channel, in channel order. UNKNOWN is kept."""
    out: list[RoleAssignment] = []
    for channel in project.channels:
        role, confidence, sources = role_from_name(channel.name)
        out.append(
            RoleAssignment(
                channel=channel.index,
                role=role,
                confidence=confidence,
                method=ClassificationMethod.RULES,
                sources=sources,
            )
        )
    return tuple(out)


def analyse(project: BeatProject, state: ProjectState) -> Analysis:
    """Assemble the Analysis document for the inspect slice."""
    roles = hint_roles(project)
    named = sum(1 for r in roles if r.role is not Role.UNKNOWN)
    completion = (named / len(roles)) if roles else 0.0
    return Analysis(
        project_id=project.id,
        state=state,
        roles=roles,
        completion_estimate=round(completion, 3),
    )
