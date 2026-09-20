"""The closed musical-role vocabulary.

SPEC.md section 7 fixes the vocabulary to eleven values. The product brief uses a
finer-grained list (``hi_hat``, ``808``, ``sub_bass``, ``pad`` ...). Rather than
pick one and lose the other, the finer terms are accepted as *aliases* that
normalise onto the closed set - see docs/adr/ADR-0004-role-vocabulary.md.

Nothing outside this module may invent a role string.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """The only role labels that may appear in an Analysis or ArrangementPlan."""

    CHORDS = "chords"
    MELODY = "melody"
    COUNTER = "counter"
    BASS = "bass"
    KICK = "kick"
    SNARE = "snare"
    HATS = "hats"
    PERC = "perc"
    FX = "fx"
    VOCAL = "vocal"
    UNKNOWN = "unknown"


#: Finer-grained vocabulary from the product brief, mapped onto the closed set.
#: Keys are matched case-insensitively after stripping separators.
ROLE_ALIASES: dict[str, Role] = {
    "hi_hat": Role.HATS,
    "hihat": Role.HATS,
    "open_hat": Role.HATS,
    "openhat": Role.HATS,
    "closed_hat": Role.HATS,
    "cymbal": Role.PERC,
    "ride": Role.PERC,
    "crash": Role.PERC,
    "clap": Role.SNARE,
    "rim": Role.SNARE,
    "percussion": Role.PERC,
    "sub_bass": Role.BASS,
    "subbass": Role.BASS,
    "sub": Role.BASS,
    "808": Role.BASS,
    "pad": Role.CHORDS,
    "keys": Role.CHORDS,
    "piano": Role.CHORDS,
    "arp": Role.MELODY,
    "lead": Role.MELODY,
    "pluck": Role.MELODY,
    "counter_melody": Role.COUNTER,
    "countermelody": Role.COUNTER,
    "texture": Role.FX,
    "riser": Role.FX,
    "sweep": Role.FX,
    "impact": Role.FX,
    "vox": Role.VOCAL,
}

#: Roles that belong to the drum kit. Used by density/dropout logic later.
DRUM_ROLES: frozenset[Role] = frozenset(
    {Role.KICK, Role.SNARE, Role.HATS, Role.PERC}
)

#: Roles that carry pitched musical content.
PITCHED_ROLES: frozenset[Role] = frozenset(
    {Role.CHORDS, Role.MELODY, Role.COUNTER, Role.BASS, Role.VOCAL}
)


def normalise_role(value: str) -> Role:
    """Map an arbitrary role-ish string onto the closed vocabulary.

    Unrecognised input becomes :attr:`Role.UNKNOWN` rather than raising, because
    this is fed by heuristics over user-authored channel names.
    """
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    try:
        return Role(key)
    except ValueError:
        pass
    return ROLE_ALIASES.get(key, Role.UNKNOWN)
