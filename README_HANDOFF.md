# Prosody handoff bundle — 2026-09-23

Read in this order. Each file is self-contained; the order is priority.

| # | File | What it is | When it applies |
| --- | --- | --- | --- |
| 1 | TESTING_HANDOFF.md | Findings from real local testing on the studio PC (FL Studio 2026). P0 items block the core workflow. | **Start here. Do P0 first.** |
| 2 | HARDENING.md | First-run reliability, validation levels, packaging, security, licensing. | After TESTING_HANDOFF P0/P1 |
| 3 | RELEASE.md | Standalone Windows release: portable ZIP + installer, clean-account test. | Every release build |
| 4 | ARCHITECTURE_NOTES.md | Five data-contract changes to make now; everything else deferred to docs/ROADMAP.md. | After TESTING_HANDOFF P0 |
| 5 | SPEC.md | Original build spec: principles, schemas, pipeline, phases. Still the contract where not superseded above. | Reference |
| 6 | CLAUDE.md | Repo conventions. Keep at repo root. | Always |
| 7 | EXECUTE.md | Original Phase 0 spike directive (parse rate, round-trip, FL CLI, stems). The round-trip spike (T2) still has not been run. | Reference; T2 still owed |

Precedence when files disagree: TESTING_HANDOFF > HARDENING > RELEASE > ARCHITECTURE_NOTES > SPEC.

Non-negotiables that appear in every file: originals are never modified (hash before/after), FL Studio is the only renderer, AI plans and deterministic code executes, no fake capabilities, no global Python/Node for end users.
