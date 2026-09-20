# BUILD.md — specification index

There was no `BUILD.md` in this repository when work started; the repository was
empty. The product specification arrived as three documents, and this file is
the index to them so that "read BUILD.md" resolves to something real.

**If these disagree, `SPEC.md` wins** (CLAUDE.md states it is the contract).
Disagreements found so far are recorded in
[DECISIONS.md](DECISIONS.md#contradictions-found-in-the-specification-set).

| Document | Role | Stability |
| --- | --- | --- |
| [SPEC.md](SPEC.md) | The contract: scope, principles, architecture, schemas, phases, exit criteria | Stable |
| [EXECUTE.md](EXECUTE.md) | The current phase's directive (Phase 0 spikes) | Replaced each phase |
| [CLAUDE.md](CLAUDE.md) | Repo conventions for agents working here | Stable |

## The product in one line

Drop an FLP → analyse → classify → choose genre/structure → extract and/or
arrange → validate → output an editable FLP plus WAV, stems, MIDI and a portable
project.

## The three rules that outrank everything

1. **Originals are immutable.** Read-only source, hashed on entry, re-verified
   on exit. A changed hash fails the run.
2. **FL Studio is the only renderer.** No plugin emulation, no guessed audio.
3. **AI plans, deterministic code executes.** An LLM never touches `.flp` bytes,
   playlist positions or file paths.

## Where implementation stands

[PHASE_REPORT.md](PHASE_REPORT.md) is the authoritative answer, and distinguishes
between *measured*, *unverified* and *blocked*. [ROADMAP.md](ROADMAP.md) maps
phases to exit criteria. [ARCHITECTURE.md](ARCHITECTURE.md) explains the
structure.

## Development order

`SPEC.md` section 9 and the product brief section 22 give slightly different
phase numbering for the same work. `ROADMAP.md` reconciles them into a single
list and is the one to follow.
