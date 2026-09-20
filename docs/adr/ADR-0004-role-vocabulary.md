# ADR-0004: One closed role vocabulary, with aliases

Date: 2026-09-20
Status: Accepted

## Context

The two governing documents disagree.

- SPEC.md section 7 and CLAUDE.md: the vocabulary is **closed** at eleven —
  `chords, melody, counter, bass, kick, snare, hats, perc, fx, vocal, unknown`.
- The product brief section 4 lists twenty, splitting `hi_hat`/`open_hat`,
  `bass`/`sub_bass`/`808`, `chords`/`pad`, `melody`/`arp`/`lead`, and adding
  `clap`, `cymbal`, `counter_melody`, `texture`, `percussion`.

CLAUDE.md states SPEC.md is the contract, so the eleven win. But the finer terms
are what producers actually name channels, and discarding them would throw away
the strongest signal the classifier has.

## Decision

`Role` is the closed eleven. `ROLE_ALIASES` in `model/roles.py` maps the finer
vocabulary onto it, and `normalise_role()` is the only sanctioned way to turn a
string into a `Role`.

Nothing outside `model/roles.py` may invent a role string. Unrecognised input
becomes `Role.UNKNOWN` rather than raising, because the input is user-authored
channel names.

## Consequences

- Arrangement logic, genre profiles and stem naming all work over eleven values.
- A channel named "Open Hat" or "808" is still recognised, and normalises to
  `hats` and `bass`.
- Information is lost: `open_hat` and `hi_hat` both become `hats`, so an
  arrangement cannot currently hold back open hats until the hook. If that turns
  out to matter musically, the fix is a `subrole` field, not a wider `Role` —
  which would be a new ADR.
- `808 → bass` is a musical judgement, not a neutral mapping. In trap an 808 is
  simultaneously bass and kick. Revisit when a trap genre profile is written.
