"""Energy -> which roles play. Deterministic, no randomness beyond the seed.

A section carries an energy target in 0..1. The engine walks the genre's role
priority order, switching roles on until their accumulated weight reaches the
target. Roles the project does not actually have are skipped - **the engine
never invents material it was not given**.
"""

from __future__ import annotations

from flpfinisher.model.roles import DRUM_ROLES, Role
from flpfinisher.model.schemas import GenreProfile, SectionType

#: Roles that should stay on once they enter, so a track does not flicker.
_STICKY = frozenset({Role.CHORDS, Role.MELODY, Role.VOCAL})


def _entry_blocked(
    profile: GenreProfile,
    role: Role,
    section: SectionType,
    section_index: int,
    first_index: dict[SectionType, int],
) -> bool:
    """Apply the profile's data-driven entry rules."""
    for rule in profile.entry_rules:
        if rule.role is not role:
            continue
        if section in rule.absent_from:
            return True
        if rule.not_before is not None:
            gate = first_index.get(rule.not_before)
            if gate is None or section_index < gate:
                return True
    return False


def active_roles(
    profile: GenreProfile,
    section: SectionType,
    energy: float,
    available: set[Role],
    *,
    section_index: int = 0,
    first_index: dict[SectionType, int] | None = None,
) -> tuple[Role, ...]:
    """Roles that play in this section, in the profile's priority order.

    Args:
        profile: the genre profile supplying weights, priority and entry rules.
        section: which section type this is.
        energy: 0..1 density target.
        available: roles the source project actually contains.
        section_index: position of this section in the arrangement.
        first_index: first occurrence index of each section type, for
            "bass does not enter before the first hook"-style rules.
    """
    first_index = first_index or {}
    priority = profile.role_priority or tuple(profile.role_weights)

    chosen: list[Role] = []
    accumulated = 0.0
    for role in priority:
        if role not in available or role is Role.UNKNOWN:
            continue
        if _entry_blocked(profile, role, section, section_index, first_index):
            continue
        if accumulated >= energy and role not in _STICKY:
            continue
        chosen.append(role)
        accumulated += profile.role_weights.get(role, 0.0)

    # A section with any energy at all should not be silent: if weights are too
    # small to reach the target, take the highest-priority available role.
    if not chosen and energy > 0 and available:
        for role in priority:
            if role in available:
                chosen.append(role)
                break

    return tuple(chosen)


def dropout_bars(
    profile: GenreProfile, next_section: SectionType | None, bars: int
) -> int:
    """Bars of drum dropout at the end of a section, as a transition.

    Only applied before the sections the genre names, and never to a section so
    short that the dropout would swallow it.
    """
    if next_section is None or next_section not in profile.dropout_before:
        return 0
    if bars < 4:
        return 0
    return 1


def drum_roles_in(roles: tuple[Role, ...]) -> tuple[Role, ...]:
    return tuple(r for r in roles if r in DRUM_ROLES)
