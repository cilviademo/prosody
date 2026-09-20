# ADR-0005: Repository name vs. product name

Date: 2026-09-20
Status: Accepted (reversible)

## Context

SPEC.md section 11, founder decision #1, leaves the working name open with the
default `flp-finisher`. The git repository this work lands in is named
`prosody`.

## Decision

- Git repository: `prosody` (unchanged — renaming is the founder's call).
- Python distribution: `flp-finisher`.
- Python package and import root: `flpfinisher`.
- CLI entry point: `flpf`.

The package name follows SPEC.md because every path in the spec, EXECUTE.md and
CLAUDE.md assumes `flpfinisher/`.

## Consequences

Reversible in one commit if the founder picks a product name. Recorded under
FOUNDER DECISION REQUIRED in PHASE_REPORT.md.
