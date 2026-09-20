# ADR-0003: Synthetic .flp fixtures for the unit tier

Date: 2026-09-20
Status: Accepted

## Context

SPEC.md section 8 is emphatic: exit criteria are measured against 25 real `.flp`
files, "never against synthetic projects". Section 16 of the product brief is
equally emphatic that copyrighted or personal projects never enter git.

Both are right, and together they leave the unit tier with nothing to parse. CI
and any fresh clone would have zero coverage of the parser — the component the
whole product rests on.

## Decision

Add `tests/fixtures/flp_builder.py`, which emits **real FLP binaries**: the
actual `FLhd`/`FLdt` container with real event records, parsed by PyFLP exactly
as an FL-saved file is. It is a test fixture, not a project writer, and lives
outside `prosody_core/` so no application code can depend on it.

The two tiers have different and non-overlapping jobs:

| Tier | Input | Answers |
| --- | --- | --- |
| unit | synthetic fixtures | Does the adapter map the format correctly? Does it degrade gracefully? Do the safety properties hold? |
| corpus | 25 real projects | Does PyFLP survive what FL Studio actually writes? |

A synthetic fixture **cannot** answer the corpus question and is never reported
as if it had. Every corpus-derived number in PHASE_REPORT.md stays marked
UNVERIFIED until the real corpus is attached.

## Consequences

- The unit tier runs anywhere, in seconds, with no corpus and no FL Studio.
- Golden tests (`tests/golden/*.json`) pin normalised output for six fixture
  shapes, so unintended parser changes surface as a diff.
- Building the fixtures forced us to learn the container format precisely, which
  is documented in `docs/flp-compatibility.md` and will be needed by the writer.
- **Risk, stated plainly:** the fixtures are written to the format as PyFLP
  reads it. If PyFLP misreads something, a fixture can encode the same
  misunderstanding and the test still passes. Only the corpus tier catches that.
  This is why the corpus tier is not optional, merely deferred.
