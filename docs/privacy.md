# Privacy

## What leaves this computer today

**Nothing.** There is no network code in `flpfinisher/`. No HTTP client is
imported, no API key is read, no telemetry is collected. This is verifiable:

```bash
grep -rE "requests|httpx|urllib|socket|anthropic|openai" flpfinisher/
```

returns nothing.

## What will leave it later, and under what rules

LLM assistance arrives in Phase 10 (classification fallback for low-confidence
patterns, and ranking generated arrangement variants). The rules are fixed now,
before any such code exists:

1. **Opt-in, per run.** No LLM call happens without an explicit flag
   (`--llm`). `FLPF_LLM=off` is the default in tests.
2. **Never uploaded:** `.flp` files, WAVs, stems, samples, MIDI, plugin binaries,
   file paths, folder names, or project names.
3. **What may be sent:** sanitised structured musical metadata only — pattern
   lengths in ticks, note counts, pitch ranges, polyphony, note density, channel
   *kind*, and the closed role vocabulary. Numbers and enum values, not content.
4. **Channel and pattern names are the hard case.** They are the strongest
   classification signal *and* they can contain personal information ("beat for
   Sarah birthday"). They are not sent unless the user opts in separately.
5. **Every call is logged** to `DATA/llm_log.jsonl` in the project's own output
   folder: model, full prompt, full response, cost. The user can read exactly
   what was sent, after the fact, without trusting this document.
6. **The application works without an LLM.** Rule-based classification and
   deterministic arrangement are always available. LLM support augments; it is
   never a runtime dependency.

## Secrets

Keys come from the environment or a gitignored `.env`; see `.env.example`.
`.gitignore` excludes `.env*` (except the example). No key is ever written into
`out/`, a log line, or a report.

## Local data

Everything the application writes stays under `out/<slug>/`. The SQLite index
(Phase 2+) stores metadata and paths, not audio or project contents. Nothing is
written outside `out/`, and the source corpus is hash-verified as unmodified
after every run.
