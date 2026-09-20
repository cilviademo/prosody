# corpus/

**Read-only. Nothing in this repository may write, move, rename or "fix" a file
here.** `ReadOnlyCorpus` hashes every source at the start of a run and
re-verifies at the end; a changed hash fails the command.

This directory is gitignored except for this file. Real FL Studio projects are
personal and often contain copyrighted samples, so they never enter git.

## Populating it

Point it at your real projects with a junction (Windows) or symlink:

```
:: Windows
mklink /J corpus\2023 "D:\FL Projects\2023"
```

```bash
# macOS / Linux
ln -s "/path/to/FL Projects/2023" corpus/2023
```

## What the corpus needs to contain

SPEC.md section 8 fixes the composition at 25 files:

| Slice | Count | Purpose |
| --- | --- | --- |
| 4-bar starters, spread across every FL version you have saved with | 12 | the core use case |
| 8-16 bar loops with a partial playlist | 5 | `state` detection, "arranged vs loop" |
| Finished beats | 5 | golden arrangements for the validator, later StyleProfile |
| Known-broken (missing samples, dead plugins) | 3 | health check and Stem Mode routing |

Until it is populated, `pytest -m corpus` skips automatically and every
corpus-derived number in PHASE_REPORT.md stays marked UNVERIFIED.

Synthetic stand-ins used by the unit tier live in `tests/fixtures/flp_builder.py`
and are **not** a substitute for this corpus - see docs/testing.md.
