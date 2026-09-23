# ARCHITECTURE_NOTES.md — scoped data-contract hardening (do AFTER TESTING_HANDOFF P0)

Source: architecture lessons from the Artifact Bench project. Only the items
below are in scope for this pass. Everything else from those notes goes into
`docs/ROADMAP.md` as "after v0.2", one line each. Do not touch the working
Drop → Analyze → Arrange → Export flow while doing this.

## Implement now, in order

1. **Evidence and validation status as separate fields.**
   Add two enums to `model/schemas.py` and attach them to every analyzed
   value (tempo, key, roles, sections, plan ops):
   - `evidence_status`: EXTRACTED | MEASURED | INFERRED | GENERATED |
     USER_APPROVED | UNKNOWN
   - `validation_status`: UNVERIFIED | STRUCTURALLY_VALIDATED |
     SEMANTICALLY_VALIDATED | FL_STUDIO_VALIDATED
   Parser output defaults to EXTRACTED/UNVERIFIED; classifier output is
   INFERRED with its existing confidence; anything the user edits becomes
   USER_APPROVED. Never overload one field for both concepts.

2. **Lineage on every derivative.** `parent_project_id`, `parent_hash`,
   `operation_set_id` on every generated .flp, Arrangement Pack, render and
   `job.json`. ORIGINAL is never mutated; PROPOSED_A/B/C → USER_WORKING →
   EXPORTED is the only lineage chain.

3. **Three-layer arrangement model, by naming what exists.**
   Layer A intent (section + goal) → Layer B semantic ops (REMOVE_LAYER,
   PLACE_PATTERN, CREATE_DROPOUT, …) → Layer C FL mutation ops
   (OMIT_PLAYLIST_INSTANCE with pattern_id, track, start_tick, end_tick).
   AI may produce A/B only; deterministic code compiles B → C; only C touches
   a derivative file. Add `reason`, `evidence`, `confidence`,
   `permission_level`, `reversibility`, `result` to each op and write
   `operations.json` beside `arrangement.json`.

4. **Explicit pipeline stages in `job.json`.** Enum: INGESTED,
   PROJECT_PARSED, ASSETS_RESOLVED, MIDI_ANALYZED, AUDIO_ANALYZED,
   MIXER_ANALYZED, STRUCTURE_INFERRED, ARRANGEMENT_READY, OPTIONS_GENERATED,
   USER_REVIEWED, PROJECT_COMPILED, EXPORT_VALIDATED. Each stage records
   state, input_hash, output_hash, analysis_version, configuration_hash,
   started_at, completed_at, error. Resume skips completed stages whose
   input hashes are unchanged.

5. **Ground-truth fixtures.** `tests/fixtures/ground_truth_a.flp` (4-bar
   loop: drums, bass, chords, melody, known routing; `loop_test.flp` once it
   parses) and `ground_truth_b.flp` (finished 64-bar arrangement of the same
   material) plus `ground_truth_b_unfinished.flp` (B with the arrangement
   removed). Tests: analyze the unfinished B and check tempo, roles,
   repetition, and that the planner produces a structure of comparable
   length; the finished B is reference only and is never fed to the planner.

## Explicitly deferred (record in docs/ROADMAP.md, do not build)

Evidence-graph tables, content-addressed analysis cache, motif fingerprinting,
multi-evidence section inference, composition-retention metrics,
user-decision persistence, local producer priors, musical reference library,
15-category regression corpus, additional worker isolation, JUCE/VST shell,
graph databases, cloud, model training.

## Cross-project reuse that IS worth doing (separate task, later)

Prosody and Artifact Bench share the same shell: Tauri + Python sidecar +
stdio IPC + diagnostics + settings + transactional writes + portable mode +
release scripts + clean-account test. Once Prosody's shell passes the
FIRST-RUN gate, extract it into a template repo so Artifact Bench starts from
a proven base. Do not start that extraction before Prosody is FIRST-RUN READY.
