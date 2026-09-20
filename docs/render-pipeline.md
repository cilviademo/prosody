# Render pipeline

**Status: not implemented.** No rendering code exists. This records what is
known, what is assumed, and what must be measured on the studio PC. Phase 2.

FL Studio is the only renderer. Nothing in this project synthesises audio,
emulates a plugin, or guesses what a VST would produce.

## Command-line switches

| Purpose | Switch | Confidence |
| --- | --- | --- |
| Render a project | `/R<filename>` | documented, **unverified here** |
| Pick export formats | `/E<fmt,fmt>` | documented, **unverified here** |
| Render every `.flp` in a folder | `/F<folder>` | documented, **unverified here** |
| Export MIDI | unknown letter | **unconfirmed — do not guess** |

`flpf doctor` prints this table and marks the MIDI switch `UNCONFIRMED`.
`tests/render/test_midi_export_switch_has_been_confirmed` **fails** whenever
`FLPF_RENDER=1` until someone records the real letter from the local FL manual
(Save/Export → "command line", `fformats_save_export.htm#commandline_export`).

A failing test is the honest representation of an unknown. Hardcoding a guessed
switch would not be.

## FL Studio discovery

`prosody_core/env.py`, in order: `FLPF_FL_EXE` override → registry
(`HKLM\SOFTWARE\Image-Line\Shared\Paths`, plus the WOW6432Node mirror) →
conventional install roots → `PATH`. No path is hardcoded as the only option.

On a non-Windows host FL Studio is reported absent rather than guessed at, and
render-dependent stages stay disabled.

## Environment gates

| Flag | Enables |
| --- | --- |
| `FLPF_RENDER=1` | FL command-line rendering. Studio PC only. |
| `FLPF_GUI=1` | pywinauto GUI automation. Interactive desktop session only. |

Neither defaults on. `flpf doctor` exits non-zero when `FLPF_RENDER=1` but FL
Studio cannot be found.

## Must be measured before any render code is trusted (EXECUTE.md T3)

Wall time per project; exit codes; whether output lands where expected; rendered
duration against `bars × 4 × 60 / bpm` (accept within 2%); **whether FL leaves a
process running afterwards** — which decides whether batch rendering is possible
at all. Every invocation captures command, source, destination, exit state,
stdout, stderr and runtime logs.

CLI rendering is reported to need an interactive Windows session, so the render
worker runs as a logged-in user task (Task Scheduler, "run only when user is
logged on"), never as a service.

## Stems: two strategies, one interface

`StemStrategy.render(project, out_dir) -> list[StemFile]`.

- **S1 solo-copy** — PyFLP writes N derived `.flp` files, each with one role's
  mixer track unmuted; render the folder in one call. Headless and parallel-safe.
  Depends entirely on PyFLP save being lossless, which is **unverified**
  (docs/flp-compatibility.md). Kill criterion: save fails or changes the project
  on ≥ 2 of 25 corpus files.
- **S2 gui-export** — pywinauto drives File → Export → Wave file with "Split
  mixer tracks". Native FL stems, exact routing, but needs an interactive desktop
  and breaks when dialogs change. Kill criterion: fails on ≥ 3 of 10 runs.
- **S3 manual** — the user exports once and we ingest. Always works; fallback.

Decision rule (SPEC.md section 5): S1 becomes the default if it passes on ≥ 23 of
25 corpus files; otherwise S2 is the default and S1 stays disabled until PyFLP
save is trusted.

Rules for every strategy: WAV only (24-bit, project sample rate) — MP3 adds
leading silence and breaks alignment; stems named by role (`Kick.wav`), not mixer
number; a bundle is rejected if any file's duration differs from `Full.wav` by
more than 1 ms; stems are rendered from the original loop and then tiled, never
re-rendered per arrangement.
