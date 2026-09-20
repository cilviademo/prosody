# PHASE_REPORT.md

Date: 2026-09-20 · Development host: Linux, Python 3.12.3, PyFLP 2.2.1, no FL
Studio, **empty corpus**.

EXECUTE.md asks four questions. Two can be answered here; two cannot be answered
on any machine without the corpus and FL Studio, and are reported as blocked
rather than estimated.

---

## Summary — the four questions

| # | Question | Answer |
| --- | --- | --- |
| 1 | What fraction of the 25-file corpus does PyFLP parse? | **BLOCKED — corpus is empty.** 6/6 synthetic FLP binaries parse (100%), which does not answer this. Also: PyFLP parses **0%** of anything on Python 3.11+ until our shim is applied — see below. |
| 2 | Does PyFLP save round-trip losslessly? | **BLOCKED — needs the corpus.** Not attempted. Source reading shows the header `channel_count` is recomputed, not preserved, so byte-identity is already doubtful. |
| 3 | Does the FL command line render a file, a folder and MIDI? | **BLOCKED — FL Studio is Windows-only and absent here.** The MIDI-export switch letter remains unconfirmed and is wired as a failing render-tier test. |
| 4 | Which stem strategy works, S1 or S2? | **BLOCKED — depends on (2) and (3).** |

**The one substantive finding of this phase was not on the list:**

> **PyFLP 2.2.1 cannot parse any `.flp` file on Python 3.11, 3.12 or 3.13 —
> including the Python 3.12 that CLAUDE.md mandates.** Every parse raises
> `TypeError` on the first event of every file. A four-line shim fixes it; it
> ships, and it is directly tested.

Had this not been found first, the corpus run would have reported a 0% parse rate
and the obvious conclusion — "PyFLP cannot read our projects" — would have been
wrong.

### T-task status

| Task | Status |
| --- | --- |
| T0 Scaffold | **Done.** Package, Typer CLI (`doctor`, `scan`, `inspect`), three test tiers with automatic gating, 5 ADRs, 12 documents. |
| T1 Parse-rate spike | **Partial.** Machinery complete and exercised: `flpf scan` writes `scan_report.csv` and `scan_errors.log`, prints the rate against the 80% target, and records unknown event ids. No corpus to run it on. |
| T2 Round-trip spike | **Not started.** Blocked on corpus. |
| T3 FL CLI spike | **Not started.** Blocked on FL Studio. |
| T4 Stem spike | **Not started.** Blocked on T2 and T3. |
| T5 This report | Done. |

---

## 1. Parse rate

### By FL version

| FL version | Files | Parsed | Notes |
| --- | --- | --- | --- |
| 21.2.3 (synthetic) | 6 | 6 (100%) | fixtures from `tests/fixtures/flp_builder.py` |
| **any real project, any version** | **0** | **—** | **corpus is empty; the SPEC criterion is unmeasured** |

### Measured on synthetic binaries

Six fixture shapes, all parsing: empty project, one-pattern 4-bar loop,
multi-pattern loop with drums and chords, project with a missing sample, 7/4 time
signature, and a 16-bar arranged project. Tempo, PPQ, FL version, time signature,
channels, patterns, notes, mixer inserts, playlist clips and sample resolution
all extract correctly, verified against known inputs.

### The Python 3.11+ blocker (measured)

PyFLP resolves every event id via `EventEnum(id)`. `EventEnum` has no members of
its own; the real member lives on a subclass and is found by `_missing_`.
CPython 3.11 added a guard to `Enum.__new__` that raises **before** `_missing_`
runs:

```python
if not cls._member_map_:
    raise TypeError("%r has no members defined" % cls)
```

| Python | `EventEnum(199)` — `FLVersion`, in every real project |
| --- | --- |
| 3.10.20 | `ProjectID.FLVersion` |
| 3.11.15 | `TypeError: has no members defined` |
| 3.12.3 | `TypeError: has no members` |
| 3.13.12 | guard present, same failure |

PyFLP 2.2.1 is the newest release on PyPI; there is no fixed version to move to.

**Fix shipped:** `parse/_pyflp_compat.py` seeds `_member_map_` with one sentinel
valued `-1`, outside the 0–255 id range. The guard passes, `_missing_` runs as
upstream intends, `_member_names_` is untouched so public enum behaviour is
unchanged. `apply()` is idempotent and becomes a no-op if PyFLP fixes this
upstream. Six tests pin the behaviour, including that unknown ids still become
pseudo-members so unknown events are preserved (EXECUTE.md T1). Full reasoning:
[ADR-0002](docs/adr/ADR-0002-pyflp-enum-compat.md).

### PyFLP fragilities found (measured)

Each raises where it should return empty. The adapter degrades each to a
`ParseWarning` and still returns a usable project.

| Condition | PyFLP | Ours |
| --- | --- | --- |
| No channels | `KeyError: ChannelID.New` | warning; tempo, PPQ, version, patterns still returned |
| Channel without `GroupNum` | `KeyError` | warning |
| No `DisplayGroup` events | `IndexError` | warning |
| Insert slots without mixer `Params` | `KeyError: 'params'` | INFO note (a property of the file, not damage) |
| Arrangement not terminated by `ArrangementsID.Current` | **silently yields nothing** | **not detectable** — see UNVERIFIED |

---

## 2. Round-trip verdicts

**Not run.** `pyflp.save()` has not been invoked against anything.

One observation from reading the source, which does not substitute for the test:

```python
num_channels = len(project.channels)
header = FLP_HEADER.pack(b"FLhd", 6, project.format, num_channels, project.ppq)
```

The header's `channel_count` is recomputed from the parsed channel list rather
than carried over from the original header. Where those differ, a save is not
byte-identical. Whether FL Studio cares is unknown.

This result gates the writer (Phase 5) **and** S1 stems (Phase 6), and needs only
the corpus — no FL Studio. It is the highest-value single measurement available.

---

## 3. CLI render results

**Not run.** FL Studio is Windows-only and absent from this host.

| Purpose | Switch | Status |
| --- | --- | --- |
| Render a project | `/R<filename>` | documented, unverified here |
| Export formats | `/E<fmt,fmt>` | documented, unverified here |
| Render a folder | `/F<folder>` | documented, unverified here |
| Export MIDI | unknown | **UNCONFIRMED — not guessed** |

What exists instead: FL discovery (`FLPF_FL_EXE` override → registry → default
roots → `PATH`, no single hardcoded path); `flpf doctor` printing the switch
table with `UNCONFIRMED` marked; `doctor` exiting non-zero when `FLPF_RENDER=1`
but FL is missing; and a render-tier test that **fails** under `FLPF_RENDER=1`
until the MIDI switch is recorded. A guessed switch that silently produced
nothing would be worse than a failing test.

Still to measure on the studio PC: wall time per project, exit codes, output
paths, rendered duration vs `bars × 4 × 60 / bpm`, and **whether FL leaves a
process running afterwards** — which decides whether batch rendering is viable.

---

## 4. Stem strategy verdict

**No verdict possible.** S1 depends on the unmeasured save round-trip; S2
requires an interactive Windows desktop. The decision rule stands unchanged
(SPEC.md section 5): S1 becomes the default if it passes on ≥ 23 of 25 corpus
files, otherwise S2 is the default and S1 stays disabled.

Neither is implemented. No `StemStrategy` stub was written, because an empty
module that imports cleanly reads as "implemented" at a glance.

---

## What was built instead

Rather than stop at four blocked spikes, the session built the vertical slice the
blocked work will need, and proved it.

**Working end to end:** drop an `.flp` → normalised `BeatProject` → state
classification → health report → JSON on disk, with the source provably
unmodified.

```
flpf doctor                     what this machine can and cannot do
flpf inspect beat.flp           summary + role hints + health, writes DATA/ and REPORTS/
flpf scan corpus/               batch parse, parse rate vs the 80% target, CSV + error log
```

Against the first-deliverable checklist (product brief section 23): filename,
FL version, BPM, duration, patterns, note counts, channels, plugins, mixer
tracks, playlist contents, automation, referenced samples, missing samples,
inferred roles with confidence, and health status — all present. Audio clips are
recognised as playlist items but not examined in detail; `key_guess` is not
implemented and is reported as `null` rather than guessed.

**Safety properties, each enforced in code and proven by a test:** originals
hash-verified unmodified; all output confined to `out/<slug>/`; generated names
versioned, never overwritten; permission levels enforced by a model validator so
an over-privileged plan cannot be constructed at all; low-confidence role guesses
structurally incapable of reaching the confidence threshold; undeterminable
health checks reported as `UNKNOWN` rather than passing; one bad file never
stopping a batch.

**Tests: 217 passing, 3 corpus + 2 render correctly skipped**, in under a
second. The unit tier parses real FLP binaries, not mocks — building the fixture writer required
learning the container format precisely, which the Phase 5 writer will need
anyway.

---

## UNVERIFIED

Everything in this section is unknown, not assumed-good.

1. **Whether any real FL Studio project parses.** The 80% criterion is
   unmeasured. One command answers it.
2. **Whether PyFLP save preserves a project.** Gates Phase 5 and Phase 6.
3. **Every FL command-line switch**, and whether FL exits cleanly after a render.
4. **The MIDI-export switch letter.**
5. **Stem viability**, S1 or S2.
6. **Silent arrangement loss.** A project whose event stream is not terminated by
   `ArrangementsID.Current` yields zero arrangements with no error. Whether FL
   ever writes such a file is unknown; if it does, we would silently report no
   playlist. This is the most dangerous unknown in the parser because it fails
   quietly. Detectable by cross-checking `ArrangementID.New` counts against
   yielded arrangements — worth doing in Phase 1 proper.
7. **`state` thresholds** (≤ 8 bars = loop, < 32 = partial) are guesses.
8. **Real-world FL version coverage.** No project older than the synthetic
   21.2.3 fixtures has been parsed.
9. **Automation clips, audio clips, Patcher, layered channels, unusual routing,
   multiple real arrangements, projects above ~50 MB** — none examined.
10. **Scale.** Nothing tested above six small files.
11. **Whether name-based role hints are useful at all** on real projects. They
    are capped below the confidence threshold precisely because this is unknown.

## FOUNDER DECISION REQUIRED

Reversible defaults have been taken in every case; work continued.

| # | Decision | Default taken | Reversal cost |
| --- | --- | --- | --- |
| 1 | Product/repo name. Repo is `prosody`; spec says `flp-finisher` | Repo unchanged; package `flpfinisher`, CLI `flpf` ([ADR-0005](docs/adr/ADR-0005-repo-name.md)) | One commit |
| 2 | **Corpus location and the 25 files** | None chosen — `corpus/README.md` documents the required composition and the junction/symlink command | **Blocking: nothing about real projects can be measured until this is done** |
| 3 | Studio PC OS and FL version | Recorded by `doctor` when run there | None |
| 4 | Where `out/` lives | `./out`, overridable with `--out`; spec suggests `D:/FLPF/out` | Flag |
| 5 | Stems dry or through master | Not reached | — |
| 6 | v1 genres | hiphop + rnb, shipped as validated JSON | Add a file |
| 7 | LLM provider | None wired. No network code exists | — |
| 8 | Preview format | Not reached | — |
| 9 | Standalone repo or under Inceptive/MZA | Standalone | — |
| 10 | Priority vs BTZ | Phase 0 only, as instructed | — |
| 11 | **New: Python version policy** | `requires-python >=3.10`, target 3.12, shim shipped. Alternative was pinning 3.10 (EOL Oct 2026) | [ADR-0002](docs/adr/ADR-0002-pyflp-enum-compat.md) |
| 12 | **New: contribute the PyFLP fix upstream?** | Not done. We carry a local shim | Small PR |
| 13 | **New: PyFLP is GPL-3.0** | Fine for a local personal tool; must be settled before distributing a binary | Backend swap or licence choice |

## Recommendation

**GO for Phase 1, conditionally — but do two things first, in this order.**

1. **Attach the corpus and run `flpf scan corpus/`.** One command. It answers
   question 1 and either validates PyFLP or sends us to the flpdiff backend
   before anything is built on top.
2. **Run the save round-trip spike (T2).** Needs the corpus, not FL Studio. It
   gates the writer and the stem strategy simultaneously — the two largest
   remaining risks.

Only then continue Phase 1 (SQLite index, `flpf find`), and run T3/T4 on the
studio PC.

**Backend:** PyFLP, behind the `ParserBackend` protocol
([ADR-0001](docs/adr/ADR-0001-parser-backend.md)). It handles every fixture
correctly and its fragilities are contained. The Python 3.11+ incompatibility is
a point against upstream's robustness, so the protocol stays and flpdiff remains
a live candidate if the corpus run disappoints.

**Stem strategy:** undecided, and it should stay undecided until T2 produces a
number. Guessing here would mean building on the unmeasured assumption the spec
explicitly warns about.

**What would change this to NO-GO:** a corpus parse rate below 80% that the
backend protocol cannot rescue, or a save round-trip that corrupts projects with
no viable alternative writer. Both are one afternoon's work away from being known.

### The honest headline

The scaffold, the domain model, the safety guarantees and the inspection slice
are real and tested. **The FL Studio workflows this product depends on are still
entirely unproven**, and the brief's own instruction — "do not claim FLP
arranging works until this test succeeds" — applies to every one of them. The
next unit of work is measurement, not features.
