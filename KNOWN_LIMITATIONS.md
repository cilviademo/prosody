# KNOWN LIMITATIONS

What does not work, stated plainly. Nothing here is marked complete because it
compiles or because a test passes against a fixture.

## The big one: no real FL Studio project has ever been parsed by this code

The corpus is empty on the development machine. Every number in SPEC.md's exit
criteria — the ≥ 80% parse rate above all — is **unmeasured**, not passed.

The 217 passing tests parse real FLP *binaries*, but ones this repository wrote
(ADR-0003). If PyFLP misreads something FL Studio writes, a fixture can encode
the same misunderstanding and the test still passes. A green unit tier is not
evidence that your projects parse.

## PyFLP save round-trip is completely unverified

`pyflp.save()` has never been run here against any project. Reading its source
shows it recomputes the header's `channel_count` from the parsed channel list
rather than preserving the original header value, so a save is not guaranteed to
be byte-identical.

This gates **both** the FLP writer (Phase 5) and the S1 stem strategy (Phase 6).
It is the single highest-value unknown and it needs only the corpus — no FL
Studio.

## PyFLP is broken on Python 3.11+ without our shim

PyFLP 2.2.1 cannot parse any `.flp` on Python 3.11, 3.12 or 3.13 — including the
Python 3.12 the spec mandates. We ship a four-line shim
([ADR-0002](docs/adr/ADR-0002-pyflp-enum-compat.md)) and test it directly. It
depends on two PyFLP internals; an upstream change fails the unit tier loudly
rather than corrupting a parse. This should be fixed upstream.

## PyFLP raises where it should return empty

The adapter converts each of these into a `ParseWarning`, but the underlying
fragility is real (details in [docs/flp-compatibility.md](docs/flp-compatibility.md)):

- a project with no channels raises `KeyError` on channel iteration
- a channel with no `GroupNum` event raises `KeyError`
- a project with no `DisplayGroup` events raises `IndexError`
- insert slots raise `KeyError: 'params'` without a mixer `Params` event

**One of these fails silently:** an arrangement not terminated by an
`ArrangementsID.Current` event is not yielded at all, with no error. Whether FL
Studio ever writes such a file is unverified. If it does, we would report zero
arrangements for a project that has one.

## Not implemented at all

- **Rendering.** No FL Studio invocation exists. The MIDI-export switch letter is
  unconfirmed; `doctor` says `UNCONFIRMED` and the render tier fails under
  `FLPF_RENDER=1` until it is recorded.
- **Stems.** Neither S1 nor S2. The decision between them needs the save
  round-trip result.
- **MIDI extraction, WAV/MP3 preview, project packaging.**
- **FLP writing.** Nothing creates a derivative project.
- **The arrangement planner.** Genre profiles and permission enforcement exist as
  validated data and types; nothing turns a profile into a plan.
- **SQLite index and `flpf find`.**
- **LLM anything.** No provider, no prompts, no network code.
- **UI.** Deferred to Phase 8 by the spec.

## Weak by design, for now

**Role classification is name-only.** It reads channel names and nothing else,
so it is wrong whenever a producer names a channel `asdf` or leaves it as
`Pattern 3` — which SPEC.md calls a certainty. Confidence is capped at 0.65,
below the 0.70 threshold, so **nothing it produces is ever treated as fact**.
The real signals (pitch range, polyphony, density, channel kind, plugin, sample
filename) arrive in Phase 3.

**Project length** is the longest playlist extent, or the longest pattern when
there is no playlist. A project with a stray clip at bar 400 reports 400 bars.

**`state` thresholds** (≤ 8 bars = loop, < 32 = partial, else arranged) are
guesses, not measurements. They need the corpus to calibrate.

**Sample resolution is exact-path only.** A moved sample library reports every
sample missing. Relink-by-filename/hash across configured drives is Phase 2.

**Key detection** is not implemented; `key_guess` is always `null`.

**Automation and audio clips** are not examined.

## Environmental

- FL Studio is Windows-only, so rendering cannot be developed or tested on
  Linux/macOS. macOS is out of scope for v1.
- CLI rendering is reported to need an interactive Windows session; the render
  worker must run as a logged-in user task, never as a service.
- PyFLP is GPL-3.0. Distributing a binary that links it has licensing
  consequences — not an issue for a local personal tool, but it must be settled
  before any distribution.

## Scale

Nothing has been tested above six small files. Hashing streams in 1 MB chunks so
large projects will not exhaust memory, but the scan loop is synchronous and
single-threaded. SPEC.md anticipates hundreds or thousands of FLPs; the resumable
SQLite-backed queue that needs is designed (`Job`, `JobStatus`) and not built.
