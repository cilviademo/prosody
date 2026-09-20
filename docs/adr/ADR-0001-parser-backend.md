# ADR-0001: PyFLP behind a Backend protocol

Date: 2026-09-20
Status: Accepted

## Context

Everything downstream depends on reading `.flp` files. SPEC.md section 10 rates
"PyFLP fails on newer FL versions in the corpus" as high likelihood with
project-blocking impact, and PyFLP 2.2.1 (September 2026) is the newest release
with no successor on PyPI.

Alternatives considered:

- **PyFLP** — mature, Python-native, models channels/patterns/playlist/mixer,
  and can write. GPL-3.0.
- **flpdiff** — TypeScript, clean-room, 2026. Would require a subprocess bridge
  and would not give us a writer.
- **Hand-rolled parser** — the FLP container is simple (see
  `tests/fixtures/flp_builder.py`), but the event catalogue is large and
  undocumented. Months of work to reach parity.

## Decision

Use PyFLP, but never import it outside `flpfinisher/parse/` and (later)
`flpfinisher/write/`. All access goes through the `ParserBackend` protocol in
`parse/adapter.py`, which returns the application's own `BeatProject`.

No PyFLP type appears in any field of any model.

## Consequences

- A second backend is a new class implementing one protocol; no other module
  changes. `flpdiff` remains the candidate if PyFLP fails on the real corpus.
- We pay a mapping layer between PyFLP's models and ours. This is also where
  graceful degradation lives, so the cost buys something.
- PyFLP is GPL-3.0. Distributing a binary that links it has licensing
  consequences. Not an issue for a local-first personal tool; flagged in
  KNOWN_LIMITATIONS.md before any distribution decision.
- The protocol is `runtime_checkable` and asserted in tests, so a backend that
  drifts from the interface fails the unit tier.
