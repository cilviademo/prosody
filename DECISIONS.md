# DECISIONS

Significant choices, with reasoning. Detailed ones get an ADR in `docs/adr/`.
Architecture is not changed silently: if a decision here is reversed, it is
edited here and the reason recorded.

## Architecture Decision Records

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](docs/adr/ADR-0001-parser-backend.md) | PyFLP behind a `ParserBackend` protocol; flpdiff as candidate second backend | Accepted |
| [0002](docs/adr/ADR-0002-pyflp-enum-compat.md) | Ship a 4-line compatibility shim so PyFLP works on Python 3.11+ | Accepted |
| [0003](docs/adr/ADR-0003-synthetic-fixtures.md) | Synthetic real-binary `.flp` fixtures for the unit tier | Accepted |
| [0004](docs/adr/ADR-0004-role-vocabulary.md) | One closed 11-value role vocabulary, with aliases for the finer terms | Accepted |
| [0005](docs/adr/ADR-0005-repo-name.md) | Repo `prosody`, package `flpfinisher`, CLI `flpf` | Accepted (reversible) |

## Smaller decisions

**Models are frozen and forbid extra fields.** `extra="forbid"` turns a typo in
a dict literal into an immediate error instead of a silently ignored field.
`frozen=True` means a stage function cannot mutate its input, which is what makes
"stage functions are pure" checkable rather than aspirational.

**Permission levels are enforced by a model validator, not a separate module.**
SPEC.md requires enforcement in code rather than prompts. Putting it in
`ArrangementPlan`'s validator means an invalid plan cannot be *constructed*, so
there is no code path — including a future LLM integration, a bug in our own
planner, or a hand-edited JSON file — that can bypass it by forgetting to call a
checker. `arrange/permissions.py` is therefore not a separate module yet.

**`HealthCheck.ok` is `bool | None`, not `bool`.** "Never hide uncertainty"
needs three states. Plugin availability genuinely cannot be determined without FL
Studio, so it reports `None` and drags the overall status to `UNKNOWN` rather
than passing by default.

**Three warning severities.** A project with no mixer `Params` event cannot
describe its effect chains — that is a property of the file, not damage, so it
is `INFO` and does not degrade health. Distinguishing this from a real read
failure keeps `PARTIAL` meaningful.

**Warnings are deduplicated by `(code, message)`.** A 100-channel project
emitting 100 copies of one notice buries the signal.

**The batch path is the real one.** `scan_directory` is primary;
`inspect_project` is its single-file case. Per SPEC.md, one failed FLP must never
kill a batch, which is hard to retrofit onto a single-project design.

**No SQLite yet.** The schema is designed (`Job`, `JobStatus` exist), but
indexing unverified parse output would mean building a search index over data we
have not yet confirmed is correct. Deferred to Phase 1 proper, after the corpus
run.

**No `arrange/permissions.py`, `write/`, `extract/` or `index/` stubs.** Empty
modules that import cleanly read as "implemented" at a glance. Absence is
honest; ARCHITECTURE.md section 8 lists what is missing and why.

**The unconfirmed FL MIDI-export switch is a failing render-tier test.**
`FL_SWITCHES["midi_export"]` is `None`, `doctor` prints `UNCONFIRMED`, and
`tests/render/` fails under `FLPF_RENDER=1` until someone records the real
letter. A guessed switch that silently produces nothing would be worse.

## Contradictions found in the specification set

Resolved per CLAUDE.md's rule that SPEC.md is the contract.

| # | Contradiction | Resolution |
| --- | --- | --- |
| 1 | `BUILD.md` is referenced as the specification but did not exist; the repo was empty | Created `BUILD.md` as an index to SPEC/EXECUTE/CLAUDE, which are the real documents |
| 2 | Role vocabulary: 11 closed values (SPEC §7, CLAUDE.md) vs 20 (brief §4) | Closed 11 + alias map — [ADR-0004](docs/adr/ADR-0004-role-vocabulary.md) |
| 3 | Phase numbering: SPEC §9 has 10 phases, brief §22 has 13, same work | Reconciled in ROADMAP.md; SPEC numbering wins because the tags follow it |
| 4 | Brief §14 wants SQLite "with migrations from the beginning"; SPEC puts the index in Phase 1 and EXECUTE.md forbids features beyond the spikes | Deferred, recorded above and in ROADMAP.md |
| 5 | Brief §3 names ~25 domain models; SPEC §7 names 5 as "the shared contract" | All five serialised documents implemented; the brief's finer types appear as sub-models (`Note`, `PlaylistClip`, `MixerInsert`, …). Types with no consumer yet (`RenderJob`, `RenderArtifact`) are not invented |
| 6 | CLAUDE.md mandates Python 3.12, on which PyFLP 2.2.1 cannot parse anything | Shim makes 3.12 work — [ADR-0002](docs/adr/ADR-0002-pyflp-enum-compat.md). Requirement kept |
| 7 | SPEC §8: measure "never against synthetic projects"; §16 of the brief: never commit real projects | Two tiers with different jobs — [ADR-0003](docs/adr/ADR-0003-synthetic-fixtures.md). Synthetic results are never reported as corpus results |
| 8 | Brief §19 describes a drop-zone UI; SPEC §1 defers all UI to Phase 8 | UI deferred. No UI code exists |
| 9 | EXECUTE.md T0 lists `mido`, `numpy`, `soundfile` as Phase 0 dependencies, but nothing in Phase 0 uses them | Declared as optional extras with reasons, not installed. Keeps the dependency surface honest |
