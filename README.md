# FLP Finisher

A local-first, Windows-first CLI that turns an unfinished FL Studio loop into an
arranged derivative project, stems and per-role MIDI — without opening the
original in FL by hand.

**Your original `.flp` is never modified.** Every operation works from a
read-only source reference or a versioned derivative copy, and every command
hashes its sources on entry and re-verifies before it returns.

## Status

Phase 1 vertical slice: **drop an `.flp` → normalised analysis JSON + health
report.** Parse, health and CLI work and are covered by 217 passing tests.

Nothing arranges, renders or writes `.flp` files yet. That is deliberate —
SPEC.md requires the FL workflows to be proven reliable before features are
built on them. See [PHASE_REPORT.md](PHASE_REPORT.md) for exactly what has been
measured and what has not, and [ROADMAP.md](ROADMAP.md) for what comes next.

## Install

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
```

Python 3.10–3.13. 3.12 is the supported target. (PyFLP 2.2.1 needs a
compatibility shim on 3.11+; it ships with this package — see
[ADR-0002](docs/adr/ADR-0002-pyflp-enum-compat.md).)

## Use

```bash
flpf doctor                     # what this machine can and cannot do
flpf inspect path/to/beat.flp   # summarise one project
flpf scan corpus/               # parse a whole folder, report the parse rate
```

`inspect` writes, under `out/<slug>/`:

```
DATA/project.json        normalised project (BeatProject)
DATA/analysis.json       state + inferred roles with confidence
REPORTS/health.json      per-check health with explicit unknowns
REPORTS/missing-files.txt
REPORTS/plugins.txt
```

`--no-write` skips all of it; `--json` prints `project.json` to stdout.

### Example

```
$ flpf inspect beat.flp
┌────────────────┬─────────────────────┐
│ FL version     │ 21.2.3.4004         │
│ tempo          │ 92 BPM              │
│ length         │ 4 bars (10.4s)      │
│ state          │ loop                │
│ patterns       │ 2 (28 notes)        │
│ samples        │ 0 found / 1 missing │
│ health         │ REQUIRES_FREEZE     │
└────────────────┴─────────────────────┘
```

Health is one of `READY`, `PARTIAL`, `REQUIRES_FREEZE`, `BLOCKED`, `UNKNOWN`.
`UNKNOWN` is a real answer: it means something material could not be determined
on this machine, and the report says which check and why.

## Tests

```bash
pytest                              # unit tier; corpus and render auto-skip
pytest -m corpus                    # needs corpus/ populated with real .flp
FLPF_RENDER=1 pytest -m render      # studio PC only
```

The unit tier parses **real FLP binaries** synthesised by
`tests/fixtures/flp_builder.py`. It is not a substitute for the real-project
corpus tier — see [ADR-0003](docs/adr/ADR-0003-synthetic-fixtures.md).

## Privacy

Nothing leaves your computer. There is no network code in `flpfinisher/`.
LLM assistance arrives in Phase 10, opt-in, sanitised, and fully logged —
[docs/privacy.md](docs/privacy.md).

## Documents

| File | What it is |
| --- | --- |
| [SPEC.md](SPEC.md) | The contract |
| [BUILD.md](BUILD.md) | Index of the specification set |
| [EXECUTE.md](EXECUTE.md) | Current phase directive |
| [CLAUDE.md](CLAUDE.md) | Repo conventions for agents |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How it is put together and why |
| [ROADMAP.md](ROADMAP.md) | Phases and exit criteria |
| [DECISIONS.md](DECISIONS.md) | Decision log, pointing at ADRs |
| [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) | What does not work, stated plainly |
| [PHASE_REPORT.md](PHASE_REPORT.md) | Measured results, unverified items, blockers |
