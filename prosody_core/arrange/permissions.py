"""Runtime enforcement of creative permission levels.

``ArrangementPlan`` already refuses to *construct* with operations above its
level. This module is the second gate: the engine calls :func:`assert_allowed`
before executing anything, so a plan that was mutated after validation, or
assembled by a future code path that bypassed the model, still cannot write
notes at Level 0.

Two independent checks is deliberate. This is the rule the product exists to
guarantee - that a user's composition is not rewritten without being asked.
"""

from __future__ import annotations

from prosody_core.model.schemas import (
    ALLOWED_OPS_BY_LEVEL,
    ArrangementPlan,
    PermissionLevel,
    PlaylistOp,
)


class PermissionDenied(RuntimeError):
    """An operation was attempted above the granted creative level."""


#: Operations that change note content. None of these may run at Level 0,
#: whatever a plan, a prompt or a provider claims.
NOTE_MUTATING_OPS = frozenset({
    "remove_notes", "scale_velocity", "octave_shift", "halve_pattern",
    "double_pattern", "fill_from_existing", "generate_counter_melody",
    "generate_transition", "generate_bass_variation",
})


def allowed_ops(level: PermissionLevel) -> frozenset[str]:
    return ALLOWED_OPS_BY_LEVEL[level]


def is_allowed(op: PlaylistOp | str, level: PermissionLevel) -> bool:
    name = op if isinstance(op, str) else op.op
    return name in ALLOWED_OPS_BY_LEVEL[level]


def assert_allowed(op: PlaylistOp | str, level: PermissionLevel) -> None:
    """Raise unless ``op`` is permitted at ``level``."""
    name = op if isinstance(op, str) else op.op
    if name not in ALLOWED_OPS_BY_LEVEL[level]:
        raise PermissionDenied(
            f"operation {name!r} is not permitted at creativity level "
            f"{level.value} ({describe(level)})"
        )


def assert_plan_allowed(plan: ArrangementPlan) -> None:
    """Re-check every operation in a plan immediately before executing it."""
    for op in plan.ops:
        assert_allowed(op, plan.level)

    if plan.level is PermissionLevel.STRUCTURE_ONLY:
        offending = sorted({o.op for o in plan.ops if o.op in NOTE_MUTATING_OPS})
        if offending:
            raise PermissionDenied(
                f"Preserve Composition forbids note changes, but the plan "
                f"contains {offending}"
            )


def describe(level: PermissionLevel) -> str:
    return {
        PermissionLevel.STRUCTURE_ONLY: "Preserve Composition",
        PermissionLevel.CONSERVATIVE: "Conservative",
        PermissionLevel.PRODUCER_ASSIST: "Producer Assist",
    }[level]
