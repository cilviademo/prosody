# ROADMAP

SPEC.md section 9 and the product brief section 22 number the same work
differently. This reconciles them into one list. Phase numbers follow SPEC.md,
because the git tags do.

Rule: **a phase cannot be tagged while any test tier that applies to it is red**,
and nothing after Phase 5 starts until one real beat has been finished with the
tool.

| Phase | Builds | Exit criteria (measured on the 25-file corpus) | Tag | State |
| --- | --- | --- | --- | --- |
| 0 | Scaffold, `doctor`, spikes: parse rate, PyFLP save round-trip, FL CLI render, stems S1 vs S2 | PHASE_REPORT.md with all four answers; go/no-go recorded | `flpf-v0.0-spikes` | **Partial** — scaffold done, spike A partial, B/C/D/E/F blocked (no corpus, no FL Studio) |
| 1 | `scan`, `inspect`, BeatProject, SQLite index | ≥ 80% parse; 5 golden projects match on tempo, bars, pattern count | `flpf-v0.1-reader` | **Mostly done** — `scan`/`inspect`/BeatProject work; SQLite index not started; parse rate unmeasured |
| 2 | `extract`: per-role MIDI, Full.wav/mp3, zip, health report | MIDI re-imports cleanly; ≥ 80% render; health on all 25 | `flpf-v0.2-extractor` | Health report done; extraction not started |
| 3 | Classifier: rules + LLM fallback, `analysis.json`, `find` | ≥ 90% role agreement on the golden five; < 30% of patterns need the LLM | `flpf-v0.3-classifier` | Name-only tier-1 hinting exists and is capped below the confidence threshold; real classifier not started |
| 4 | Arranger + preview: hiphop/rnb profiles, planner, energy, permissions, stitched previews | 3 variants per starter; previews < 10 s; ≥ 1 of 3 rated "would keep" on 5 starters | `flpf-v0.4-arranger` | Profiles and permission enforcement exist as validated data/types; planner not started |
| 5 | Writer + validator: clone `.flp`, playlist ops, `build`, all 7 validator checks | 5 starters produce `_FINISHED.flp` that open in FL and pass validation; **one beat you actually finish** | `flpf-v0.5-finisher` | Not started; blocked on the save round-trip spike |
| 6 | Stems automated, `--stems` default, Stem Mode arrangements | ≥ 90% stem success; Stem Mode passes validation on the 3 broken projects | `flpf-v0.6-stems` | Not started |
| 7 | StyleProfile learned from finished beats | Your #1-ranked variant matches the StyleProfile-influenced variant ≥ 60% of the time | `flpf-v0.7-style` | Not started |
| 8 | Tauri UI over the CLI: drop → genre → Finish Beat | Only after a month of weekly CLI use | `flpf-v0.8-ui` | Not started; gated |
| 9 | Producer Mode (levels 1–2), version families, Beat Vault | Needs its own spec | — | Deferred |

## Where this actually stands

The phase table above was written before the product build. Phases 1-5 are now
largely implemented and phase 8's UI shipped early, at the founder's direction:
the working application is Prosody, a Tauri desktop app over this backend.
**[CURRENT_STATUS.md](CURRENT_STATUS.md) is the authoritative state**; the
table below is kept for the exit criteria, which still have to be met on real
projects.

## Immediate next steps, in order

1. **Attach the corpus and run `flpf scan`.** Every parse-rate number is
   unmeasured until this happens. It is one command and it either validates or
   invalidates the parser choice.
2. **Spike T2: PyFLP save round-trip.** Parse → save → parse → structural diff
   across the corpus. This single result gates the writer (Phase 5) *and* the S1
   stem strategy (Phase 6). It needs no FL Studio — only the corpus.
3. **Spike T3 on the studio PC:** confirm the FL CLI switches, especially the
   MIDI export letter, and whether FL leaves a process running after a render.
4. Then Phase 1 proper: SQLite index and `flpf find`.

Steps 1 and 2 are the highest-value work available and neither needs FL Studio.

## Ordering principle

Do not jump to AI arrangement. The order exists because each phase's output is
the next phase's input, and because a classifier tuned against an unreliable
parser is tuned against noise.

## Deferred until after v0.2

Recorded here from ARCHITECTURE_NOTES.md so they are not forgotten and not
built early. One line each; none is in scope for the FIRST-RUN gate.

- Evidence-graph tables: every analyzed value linked to the events that produced it.
- Content-addressed analysis cache keyed by source hash + analysis version.
- Motif fingerprinting across patterns and projects.
- Multi-evidence section inference (energy, density, repetition, markers together).
- Composition-retention metrics on every derivative.
- User-decision persistence: remembered edits feed the next plan.
- Local producer priors learned from the user's own library.
- Musical reference library for structure comparison.
- 15-category regression corpus of real projects.
- Additional worker isolation beyond the single sidecar.
- JUCE/VST shell for in-DAW use.
- Graph databases.
- Cloud anything.
- Model training.
- Extracting the Tauri + Python sidecar shell into a template repo for Artifact Bench — only once Prosody is FIRST-RUN READY.
