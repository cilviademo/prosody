# CLAUDE.md — FLP Finisher

## What this is
Local Python CLI (`flpf`) that parses FL Studio .flp projects, extracts MIDI and
audio, classifies pattern roles, plans arrangements, and writes derivative .flp
files. SPEC.md is the contract; EXECUTE.md is the current phase's directive.

## Read first
SPEC.md sections 2 (principles), 7 (schemas), and the current EXECUTE.md.

## Non-negotiables
- corpus/ is read-only; hash-verify on every run
- outputs only under out/<slug>/
- FL Studio renders; code never synthesizes audio
- LLM plans and labels; deterministic code executes; permissions enforced in
  flpfinisher/arrange/permissions.py, not in prompts
- every LLM call logged to DATA/llm_log.jsonl (model, prompt, response, cost)
- no UI code before Phase 8

## Environment flags
FLPF_RENDER=1  enables FL command-line rendering (studio PC only)
FLPF_GUI=1     enables pywinauto stem export (interactive session only)
FLPF_LLM=off   disables LLM fallbacks (default in tests)

## Conventions
- Python 3.12, pydantic v2 models in flpfinisher/model/schemas.py are the only
  data contract; changing one requires docs/adr/ADR-NNNN
- Typer commands are thin: parse args → call one function in the stage module
- Stage functions are pure: (paths/models in) → (paths/models out); no globals
- Backend protocol in flpfinisher/parse/adapter.py; never import pyflp outside
  parse/ and write/
- Ticks everywhere internally; bars only at the CLI and plan boundary
- Role vocabulary is closed: chords, melody, counter, bass, kick, snare, hats,
  perc, fx, vocal, unknown
- Logging: rich console + out/<slug>/REPORTS/run.log; no print()
- Tests: tests/unit (always), tests/corpus (needs corpus/), tests/render
  (FLPF_RENDER=1); pytest markers `corpus` and `render`
- One branch per phase (phase-N), one PR, one tag flpf-v0.N-<name>
- Commit messages: "T<n>: <what changed>, <measured result>"

## Commands
uv sync                      install
flpf doctor                  environment check
pytest -m "not corpus and not render"   unit tier
pytest -m corpus             corpus tier
FLPF_RENDER=1 pytest -m render          render tier (studio PC)

## When unsure
Pick the reversible default, record it under FOUNDER DECISION REQUIRED in
PHASE_REPORT.md, keep going. Never modify corpus/ to make a test pass.
