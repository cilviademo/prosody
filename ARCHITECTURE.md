# ARCHITECTURE.md

How FLP Finisher is put together, and which boundaries are load-bearing.

Status: the full loop is implemented — drop → analyse → classify → plan →
write derivative `.flp` → export. Audio rendering and stems are written but
unexercised against FL Studio. See CURRENT_STATUS.md for the precise state.

---

## 1. The one architectural idea

**AI reasoning is separated from deterministic project mutation.**

An LLM may produce or rank an `ArrangementPlan`. It never touches `.flp` bytes,
playlist positions, or file paths. The pipeline is one-directional:

```
.flp  →  parser backend  →  BeatProject  →  classifier  →  Analysis
                                               ↓
                              genre profile + Analysis
                                               ↓
                                   planner (deterministic)
                                               ↓
                                  ArrangementPlan (validated)
                                               ↓
                              [ LLM may rank / annotate here ]
                                               ↓
                              arrangement engine (deterministic)
                                               ↓
                                     derivative .flp
                                               ↓
                                  validator (re-parse + render)
```

The narrow point is `ArrangementPlan`. It is a pydantic model with validators,
so an LLM-authored plan that exceeds its permission level or describes
discontiguous sections is rejected *by the type*, before any file is opened. A
plan that fails validation cannot reach the engine, whatever produced it.

## 2. Layers and their rules

| Layer | Package | May import | Rule |
| --- | --- | --- | --- |
| Domain | `model/` | nothing but pydantic | No third-party library object appears in a field type |
| Parse | `parse/` | PyFLP | The only place PyFLP may be imported (with `write/` later) |
| Filesystem | `fs/` | stdlib | The only place that hashes, slugifies, or names an output path |
| Analysis | `health/`, `classify/` | `model/` | Pure functions over models; no file I/O |
| Arrangement | `arrange/` | `model/` | Genre behaviour is JSON data, not functions |
| Orchestration | `pipeline.py` | all of the above | Stage functions: paths/models in, paths/models out, no globals |
| Orchestration | `build.py` | stages | One call per user action; every stage reports its own outcome |
| Interface | `api.py`, `cli.py` | `build.py` | Marshal arguments, call one function, serialise the result |
| Desktop | `apps/desktop` | `api.py` over stdio | Tauri + React; no business logic |

The import direction is strictly downward. `model/` imports nothing from the
application; `cli.py` imports everything.

### Why adapters, and only here

Premature abstraction is avoided everywhere except the four boundaries where a
third party can break us:

- **`parse/adapter.py`** — `ParserBackend` protocol. PyFLP's behaviour on new FL
  versions is the single largest project risk (SPEC.md section 10), and Phase 0
  already found a breaking incompatibility (ADR-0002). A second backend must be
  droppable in without any other module changing.
- **`fs/safety.py`** — every path decision in one place, so "never modify the
  original" is a property of the code rather than a habit.
- **FL Studio runner** (Phase 2) — a subprocess with its own failure modes.
- **LLM provider** (Phase 10) — `ArrangementPlanner` interface, with a
  deterministic rules-only implementation that is always present.

There is deliberately no dependency-injection framework, no plugin registry and
no event bus. Stage functions are called directly.

## 2a. The desktop shell

```
apps/desktop/
  src/                React UI: views, components, a typed API client
  src-tauri/          Rust window: locates Python, forwards calls, opens files
```

The Rust layer does four things a browser cannot: pick files, reveal a folder,
launch FL Studio, and read a render back for the preview player. Everything
else is a call into the Python API.

**The bridge is one short-lived process per call**, speaking line-delimited
JSON on stdout: `{"event":"progress",…}` lines, then one `{"event":"result",…}`.
A backend crash therefore cannot take the window down, and long builds stream
stage-by-stage progress without a socket or a daemon.

In release builds the backend ships as a bundled resource; in debug builds the
repository checkout wins, so editing Python takes effect on the next call
instead of the next `cargo build`. Getting that precedence backwards silently
pins a stale snapshot of the backend — it cost an hour once already.

## 2b. The writer

The derivative writer does **not** use `pyflp.save()`, which rebuilds every
event from its parsed value and recomputes the header. Instead
`write/eventstream.py` reads the file as an ordered list of
`(id, raw_payload)` pairs and writes exactly those bytes back, substituting
only the playlist event and inserting section markers.

Everything else — plugin state, automation, mixer routing, sample references,
and events no parser understands — survives because it is literally the same
bytes. A round trip with no edits is byte-identical, which is asserted by a
test. That is what makes Preserve Composition structural: at Level 0 the
writer has no code path that can alter a note.

## 3. Data contract

`model/schemas.py` is the only data contract. Five documents are serialised:

| Document | Written to | Produced by |
| --- | --- | --- |
| `BeatProject` | `DATA/project.json` | parse |
| `Analysis` | `DATA/analysis.json` | classify |
| `HealthReport` | `REPORTS/health.json` | health |
| `ArrangementPlan` | `ARRANGEMENT/Arrangement_{A,B,C}.json` | planner (Phase 4) |
| `ValidationResult` | `REPORTS/validation.json` | validator (Phase 5) |

All models are `frozen=True, extra="forbid"`: a typo in a dict literal fails at
construction rather than silently creating a field nobody reads. Changing a
model requires an ADR (CLAUDE.md).

**Units.** Ticks everywhere internally. Bars appear only at the CLI boundary and
inside `ArrangementPlan`, which is a human- and LLM-facing document.

## 4. Safety properties, and how each is enforced

These are the product's reason to exist, so none of them is left to convention.

| Property | Enforced by | Proven by |
| --- | --- | --- |
| Originals are never modified | `ReadOnlyCorpus` hashes on entry, `verify()` before every stage function returns | `test_fs_safety.py`, `test_pipeline.py::test_a_source_mutated_mid_run_fails_the_run` |
| Outputs are contained | `fs.safety.output_dir` is the only sanctioned write root | `test_all_artifacts_land_under_out_slug` |
| Generated projects are versioned, never overwritten | `fs.safety.versioned_path` | `test_versioned_path_never_overwrites` |
| Permission levels are machine-enforced | `ArrangementPlan` model validator against `ALLOWED_OPS_BY_LEVEL` | `test_schemas.py`, 6 tests |
| Low-confidence guesses are never facts | `RoleAssignment.is_confident` against `CONFIDENCE_THRESHOLD` | `test_no_name_only_guess_ever_reaches_the_confidence_threshold` |
| Uncertainty is never hidden | `HealthCheck.ok` is `bool \| None`; `None` drags status to `UNKNOWN` | `test_undeterminable_checks_report_none_not_a_pass` |
| One bad file never kills a batch | `scan_directory` catches per-file and records a row | `test_one_unparseable_file_does_not_stop_the_batch` |
| Unknown FLP events are preserved | Byte-exact event stream; `unknown_event_ids` | `test_write.py::test_reading_and_rewriting_is_byte_identical` |
| Note content is never altered at Level 0 | Writer only replaces the playlist event | `test_write.py::test_note_content_is_byte_identical` |
| A missing capability is never faked | Strategies report availability; stages report SKIPPED with a reason | `test_extract.py::test_stems_never_fabricate_audio` |
| No project data leaves the machine | No network imports anywhere in the package | `test_boundaries.py::test_no_network_capability_anywhere_in_the_package` |

## 5. Graceful degradation

Old projects are assumed to be broken in every way SPEC.md and the product brief
list: missing plugins, moved sample libraries, unnamed or empty patterns, odd
time signatures, multiple arrangements.

The parse adapter therefore wraps **every** sub-extraction. A failure inside one
section records a `ParseWarning` and returns an empty value; only an unreadable
file header is fatal. A project whose channel list cannot be read still yields
tempo, PPQ, FL version and patterns.

Three severities distinguish honestly between kinds of trouble:

- `ERROR` — the file is damaged
- `WARNING` — we failed to read something we expected to read
- `INFO` — the file genuinely does not describe this (e.g. a project with no
  mixer `Params` event cannot describe its effect chains). This does not degrade
  health status.

## 6. Batch from the start

`scan_directory` is the real entry point; `inspect_project` is the single-file
case of it, not the other way round. Every source is hashed up front, each file
is isolated, and failures become rows rather than exceptions. `Job`/`JobStatus`
exist in the domain model for the SQLite-backed resumable queue (Phase 2+); the
current implementation is a synchronous loop, which is the smallest thing that
preserves the shape.

## 7. Modes (both accommodated, neither complete)

- **Native mode** — clone the parsed original and rewrite only its playlist, so
  VSTs, MIDI, mixer routing, automation and samples survive untouched.
- **Freeze/stem mode** — render elements to audio first and arrange audio.
  The fallback for fragile legacy projects.

`HealthReport.recommended_mode` already routes between them: a project with
missing samples reports `stem`. Neither engine is implemented.

## 8. Output tiers

A build always produces the strongest result it safely can:

- **NATIVE** — an editable derivative `.flp` that passed structural validation
  (re-parses; pattern, channel, note, plugin and mixer counts equal the
  original; playlist length matches the plan; header copied verbatim).
- **PACK** — an Arrangement Pack: the plan, per-role MIDI, and any audio that
  rendered. Used when the writer cannot safely rewrite a project, or when the
  derivative fails validation. The derivative is deleted rather than shipped
  unverified, and the UI says so in plain language.

The tier is decided by the validator, not by optimism.

## 9. What is deliberately absent

No LLM network code — the provider interface exists and the implementations
declare themselves unavailable rather than pretending. No GUI stem automation:
its click path must be verified against a real FL install before it is written,
and a blind implementation would silently click the wrong dialog. No batch
queue yet; `Job`/`JobStatus` exist in the domain model and the scan loop is
still synchronous.

CURRENT_STATUS.md lists all of it, with what would move each item.
