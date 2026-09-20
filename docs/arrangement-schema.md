# arrangement.json (ArrangementPlan)

**Status: contract only.** The model and its validators exist and are tested; no
planner produces a plan and no engine executes one. Phases 4 and 5.

Written to `out/<slug>/ARRANGEMENT/Arrangement_{A,B,C}.json`.

## Shape

```json
{
  "schema_version": "1.0",
  "variant": "A",
  "genre": "rnb",
  "structure": "balanced",
  "level": 0,
  "seed": 1234,
  "source_project_id": "<sha256 of the source .flp>",
  "tempo": 142.0,
  "total_bars": 80,
  "sections": [
    {"name": "intro", "start_bar": 1, "bars": 4, "energy": 0.25,
     "active_roles": ["chords", "melody"], "dropout_bars": 0}
  ],
  "ops": [
    {"op": "tile", "role": "chords", "pattern": 1, "start_bar": 1, "bars": 4}
  ],
  "llm_notes": "optional, advisory"
}
```

`seed` makes the planner reproducible: the same inputs always yield the same
variants.

## Validation happens in the type

This is the narrow point where an LLM's output meets the filesystem, so the
checks are model validators rather than a function someone might forget to call.
A plan that fails them cannot be constructed at all.

**Permission level.** Every `ops[].op` must appear in `ALLOWED_OPS_BY_LEVEL` for
the declared `level`. Default is 0.

| Level | Adds |
| --- | --- |
| 0 structure only | `tile`, `place`, `mute`, `duplicate_pattern`, `dropout`, `marker` |
| 1 conservative | `remove_notes`, `scale_velocity`, `octave_shift`, `halve_pattern`, `double_pattern`, `fill_from_existing` |
| 2 producer assist | `generate_counter_melody`, `generate_transition`, `generate_bass_variation` |

An unrecognised op name is refused at every level, so a hallucinated operation
cannot slip through as a no-op.

**Section contiguity.** Section *n* must start where section *n−1* ended,
beginning at bar 1. Gaps and overlaps are refused.

**Closed vocabulary.** `active_roles` and `ops[].role` accept only the eleven
values in ADR-0004. `name` accepts only known section types.

## Why enforcement lives here

SPEC.md section 2 rule 4: permission levels are enforced in code, not in prompts.
A prompt that says "you may only rearrange" is a request. A validator that
refuses `remove_notes` at level 0 is a guarantee — and it holds whether the plan
came from an LLM, a bug in our own planner, or a hand-edited JSON file.

Tested by `tests/unit/test_schemas.py` (17 tests, 6 of them permission cases).

## Still to design

`dropout_bars` semantics beyond "omit the final repetition of drum roles"; how
the engine reports an operation it cannot express at PyFLP's current
capability (SPEC.md section 6 requires reporting, never faking); whether
`total_bars` should be derived from `sections` rather than declared alongside it.
