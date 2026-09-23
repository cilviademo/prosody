# ADR-0006: Provenance and lineage on the data contract

Status: accepted · 2026-09-23 · Source: ARCHITECTURE_NOTES.md items 1 and 2

## Context

`schemas.py` is the only data contract, and it had no way to say *where a
value came from* or *what a derivative was made from*. A tempo read from the
file, a key inferred by the classifier and a section invented by the planner
all looked the same, and a generated `.flp` could not be tied to the exact
bytes it descended from.

## Decision

Two orthogonal enums, never overloaded into one field:

- `EvidenceStatus`: EXTRACTED | MEASURED | INFERRED | GENERATED |
  USER_APPROVED | UNKNOWN — how a value came to be.
- `ValidationStatus` is `ValidationLevel`, which already existed with the
  four required states — how far a value has been checked.

Parser output defaults to EXTRACTED / UNVERIFIED; classifier output is
INFERRED with its existing confidence; planner output is GENERATED; the plan
a user chooses to build becomes USER_APPROVED.

Lineage on every derivative: `parent_project_id`, `parent_hash` (SHA-256 of
the original at read time) and `operation_set_id` (a hash of the exact ops
that produced it) on every `Artifact`, on `BuildResult`, and in `job.json`.
The only chain is ORIGINAL → PROPOSED → USER_WORKING → EXPORTED, and
ORIGINAL is never mutated. The `.flp` itself carries nothing extra: its bytes
stay exactly what the writer produced; lineage lives beside it.

## Consequences

`SCHEMA_VERSION` is unchanged: every new field has a default, so existing
`project.json`/`build.json` files still validate. `operation_set_id` is
derived from ops alone, so two plans that would change the file identically
share an id whatever their variant letter or seed.
