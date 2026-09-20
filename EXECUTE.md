# EXECUTE.md — FLP Finisher, Phase 0

You are building FLP Finisher: a local Python CLI that turns unfinished FL Studio
.flp loops into arranged derivative projects, stems and per-role MIDI. SPEC.md is
the contract. CLAUDE.md has repo conventions. Read both before writing code.

## Mission for this phase
Produce PHASE_REPORT.md with measured answers to four questions, plus the repo
scaffold. Do not build features beyond what the spikes need.

1. What fraction of the 25-file corpus does PyFLP parse? (target ≥ 80%)
2. Does PyFLP save round-trip losslessly? (parse → save → parse → structural diff)
3. Does the FL command line render a file, a folder, and MIDI on this machine?
4. Which stem strategy works here, S1 solo-copy or S2 gui-export?

## Hard rules (never break, never ask to break)
- corpus/ is read-only. Never write, move, rename or "fix" anything in it.
  Hash every file at scan; re-hash at the end of every command; fail on change.
- All outputs go under out/<slug>/. Nothing else on disk is touched.
- FL Studio is the only renderer. Never emulate plugins or guess audio.
- LLM calls: none in Phase 0. Later phases log every call to DATA/llm_log.jsonl.
- Anything you cannot verify goes in PHASE_REPORT.md under
  "FOUNDER DECISION REQUIRED" or "UNVERIFIED". Pick the reversible default and
  continue; do not stop to ask.
- No UI, no web server, no Tauri, no React, no Docker.
- No GUI automation runs unless FLPF_GUI=1 is set in the environment.
- No render runs unless FLPF_RENDER=1 is set (studio PC only).
- Do not add a dependency without a one-line reason in pyproject.toml comments.
- Code wins over documentation when they disagree; note the disagreement in the report.

## Tasks, in order

### T0 Scaffold
- python 3.12, uv or pip, pyproject.toml, package `flpfinisher`, Typer CLI `flpf`
- deps: pyflp, mido, numpy, soundfile, pydantic>=2, typer, rich, sqlite (stdlib)
- tests/ with pytest; tiers: unit (always), corpus (needs corpus/), render (FLPF_RENDER=1)
- `flpf doctor`: locate FL64.exe (registry + default paths), print PyFLP version,
  ffmpeg presence, corpus file count, and the FL manual's command-line switches it
  will use. Exit non-zero if FL is not found and FLPF_RENDER=1.
- docs/adr/ADR-0001-parser-backend.md: PyFLP behind a Backend protocol; flpdiff
  listed as candidate second backend.

### T1 Spike: parse rate
- `flpf scan corpus/` → for each .flp: sha256, FL version (from header), tempo,
  ppq, pattern count, channel count, playlist item count, parse ok/error.
- Write out/scan_report.csv and a summary table in PHASE_REPORT.md grouped by FL
  version. Record every exception verbatim in out/scan_errors.log.
- Keep unknown PyFLP events; never drop them.

### T2 Spike: save round-trip
- For each parsed file: pyflp.save() to out/<slug>/roundtrip.flp, parse it back,
  diff: counts of channels, patterns, notes, playlist items, mixer inserts,
  plugin names, sample paths. Report byte-size delta and any structural diff.
- Verdict per file: lossless / changed / failed. Aggregate in PHASE_REPORT.md.

### T3 Spike: FL command line (only with FLPF_RENDER=1)
- Confirm the exact switches from the local manual page
  (FL Studio manual → Save/Export → "command line"). Verified so far:
  /R[filename] renders a project, /E<fmt,fmt> picks formats, /F<folder> renders
  every .flp in a folder. The MIDI export switch exists; confirm its letter and
  record it.
- Run three renders with timeouts and captured stdout/stderr:
  1. one project → wav+mp3   2. a temp folder of 3 projects → wav   3. MIDI export
- Report wall time per project, exit codes, output paths, duration vs expected
  (bars × 4 × 60 / bpm), and whether FL leaves a process running afterwards.

### T4 Spike: stems, S1 vs S2 (one project, FLPF_RENDER=1)
- S1: using PyFLP, write N copies with all but one mixer track (or channel group)
  muted; render the folder with /R /Ewav /F; check N stems exist, equal length,
  non-silent, and that mixing them back approximates Full.wav (null test, report
  peak residual in dB).
- S2 (only with FLPF_GUI=1): pywinauto script that opens the project, drives
  File → Export → Wave file with "Split mixer tracks" checked, waits, and lists
  the resulting files. Reference: the open-source AutoHotkey FL batch-export
  script for the click path. Ten runs; report pass count.
- Verdict per SPEC section 5's kill criteria.

### T5 PHASE_REPORT.md
Sections, in this order: Summary (four answers, one line each) · Parse rate table
by FL version · Round-trip verdicts · CLI render results · Stem strategy verdict ·
UNVERIFIED · FOUNDER DECISION REQUIRED · Recommendation: go / no-go for Phase 1,
and which backend and stem strategy to build on.

## Definition of done
- `flpf doctor` and `flpf scan corpus/` run clean on the studio PC
- unit tier green; corpus tier green or failures explained in the report
- PHASE_REPORT.md complete; git tag flpf-v0.0-spikes on branch phase-0
- No file in corpus/ changed (hashes match)

## How to report progress
One line per task in PHASE_REPORT.md as it lands. No narrative in commit
messages beyond "T2: round-trip diff, 23/25 lossless". Surface blockers in the
report, then move to the next task.
