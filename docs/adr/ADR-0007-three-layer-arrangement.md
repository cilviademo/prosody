# ADR-0007: Three-layer arrangement model

Status: accepted · 2026-09-23 · Source: ARCHITECTURE_NOTES.md item 3

## Context

The arrangement pipeline already had three distinct things in it — sections
with an energy and active roles, semantic ops in bars, and the playlist
items the writer emitted in ticks — but only the first two were models, and
the writer derived the third from the second itself. "AI may only produce
intent and semantic ops; only deterministic code touches the file" was true
in behaviour and invisible in data.

## Decision

Name what exists and move the one piece of arithmetic that crossed a layer:

- **Layer A** — `Section`, now with a `goal`: the intent.
- **Layer B** — `PlaylistOp`, now with `reason`, `evidence`, `confidence`,
  `permission_level`, `reversibility` and `result`: what a planner asked for,
  in bars, and why. This is the most an AI planner can produce, because an
  `ArrangementPlan` has no field that could hold anything lower.
- **Layer C** — `MutationOp` (`PLACE_PLAYLIST_INSTANCE`,
  `OMIT_PLAYLIST_INSTANCE`, `WRITE_MARKER`) in ticks, produced only by
  `arrange.compile.compile_plan`, deterministically. The writer consumes
  these and nothing else, and records a `result` on each.

`operations.json` beside `arrangement.json` holds all three layers for a
build, with results.

## Consequences

The bar→tick arithmetic moved into the compiler verbatim, so a derivative is
byte-for-byte what it was before the layers were named; the goldens did not
change. `reversibility` is always "reversible" today because every op acts
on a derivative and the original is never touched — the field exists so a
future op that is not has to say so.
