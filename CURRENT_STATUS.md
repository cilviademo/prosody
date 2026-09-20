# CURRENT_STATUS

Asterism v0.1.0 · 2026-09-20

Verified on Linux with a synthetic four-bar project. **No real FL Studio
project and no FL Studio installation has been exercised yet** — the studio PC
is where that happens.

---

## WORKING

- **The whole loop, end to end, in the app:** drop or browse an `.flp` →
  analysis → choose Extract / Arrange / Extract + Arrange → genre → structure →
  creativity → timeline preview → Build → results with Open in FL Studio and
  Open output folder. Driven through the running UI, not just the API.
- **Native derivative `.flp` generation (Tier A).** A four-bar loop becomes an
  80-bar hip-hop or 88-bar R&B arrangement. Patterns, channels, notes, plugins,
  mixer and routing are copied **byte for byte**; only the playlist event is
  replaced and section markers are added.
- **The original is never modified.** Hashed before the build, re-verified
  after, reported in the result and in `reports/validation.json`.
- **Preserve Composition enforced in code**, at two independent gates: an
  `ArrangementPlan` model validator (an over-privileged plan cannot be
  constructed) and a runtime check immediately before bytes are written.
- **Six genre profiles as data** — hip-hop, R&B, pop, trap, EDM, drum & bass —
  with section grammar, energy targets, role weights, entry rules and dropouts.
- **Energy engine.** Density per section drives which existing roles play.
  Entry rules work: bass enters with the first hook in hip-hop; the kick drops
  out of an EDM breakdown.
- **Multi-signal role classification.** Channel name, sample filename, plugin,
  mixer track name, pitch range, polyphony, note duration, note density and
  on-beat ratio vote; confidence is margin-based and capped at 0.97.
- **Per-role MIDI export** at the project's PPQ and tempo, note count matching
  the source exactly.
- **Portable ZIP** with resolvable samples and a `MISSING_SAMPLES.txt` for the
  rest.
- **Arrangement timeline preview** — section blocks shaded by energy, one lane
  per role, before anything is written.
- **Library** (SQLite, migrations from v1) and **Settings** (FL path with Test
  Connection, render toggle, export folder, formats, creativity, planner).
- **Honest degradation everywhere.** Unavailable capabilities are disabled with
  the reason shown, and every other output still runs.
- **466 unit tests, lint clean.** They parse real FLP binaries, not mocks.

## PARTIAL

- **Key detection** — pitch-class histogram correlation. Labelled "approx" in
  the UI below 0.70 confidence. Untested against real music.
- **Creativity levels 1 and 2** — selectable, and the UI says plainly they are
  not implemented. The engine only ever repositions existing patterns.
- **AI planners** — `ArrangementPlanner` interface with Claude and OpenAI
  implementations that declare themselves unavailable and fall back to the
  deterministic planner. No network code exists. Rules-only is fully working.
- **Arrangement Pack (Tier B)** — the fallback triggers correctly and is
  described as a supported result, but has only been exercised by forcing it
  (a project with no notes), never by a real project that defeats the writer.
- **Patterns that mix roles** move as one block at Level 0. Reported in the
  plan notes rather than worked around; splitting them is a note edit.

## NOT YET WORKING

- **Audio rendering (WAV/MP3).** The FL command-line wrapper is written,
  captures command/exit/stdout/stderr/timing, and is gated behind FL discovery
  plus `render_enabled`. **It has never been run against FL Studio.**
- **Stems.** `solo-copy` writes correct per-role derivative projects (verified:
  only the chosen channels are enabled, all content preserved) but the render
  half is unexercised. `gui-export` is deliberately unimplemented — its click
  path must be verified against a real FL install before it is written.
- **The FL MIDI-export switch letter** is unconfirmed. `flpf doctor` prints
  `UNCONFIRMED`, and a render-tier test fails under `FLPF_RENDER=1` until
  someone records it. Per-role MIDI does not need it.
- **Windows installer.** Not produced here — Tauri cannot cross-compile a
  Windows bundle from Linux. Build it on the studio PC (README has the command).
- **Sample relinking.** Missing samples are detected and reported, never
  repaired.
- **Level 1 / 2 operations**, audio preview waveform, batch/queue processing.

## KNOWN ISSUES

1. **PyFLP 2.2.1 cannot parse anything on Python 3.11+** without the shim this
   project ships (`parse/_pyflp_compat.py`). Six tests pin it;
   `flpf doctor` and Settings → Environment report when it is active.
2. **An arrangement not terminated by `ArrangementsID.Current` is silently
   dropped by PyFLP** — no error, zero arrangements. Whether FL writes such a
   file is unknown. This is the most dangerous unknown because it fails quietly.
3. **FL 21 playlist items (60-byte) are untested.** The writer matches whatever
   the source uses and copies an existing item's trailing bytes; with no item
   to copy it zero-fills and warns. Only 32-byte items have been verified.
4. **Pattern length is inferred from note extents** when FL wrote no Length
   event, then rounded up to whole bars for tiling. Correct for the fixtures;
   unverified against projects with deliberate odd-length patterns.
5. **`state` thresholds** (≤8 bars = loop, <32 = partial) are guesses.
6. **Nothing has been tested above six small files.** The scan loop is
   synchronous; the resumable queue is designed, not built.
7. **The app needs Python 3.10+ on the machine.** It is not yet bundled as a
   standalone runtime; the window shows a clear message with the fix if Python
   is missing.

## NEXT PRIORITY

**Run it on the studio PC against real projects.** In order:

1. Point Asterism at a real four-bar `.flp` and confirm the derivative opens in
   FL Studio with its plugins, samples and mixer intact. This is the one
   result that decides whether the product works.
2. Set the FL Studio path, enable rendering, and run a build — confirming the
   `/R /E` switches, the wall time, and **whether FL leaves a process running
   afterwards** (this decides whether batch rendering is possible at all).
3. Record the MIDI-export switch letter from the local FL manual.
4. Then stems: `solo-copy` end to end, with a null test against the full mix.

Everything after that is scale and polish. These four answers are what turn
"verified on synthetic fixtures" into "verified".
