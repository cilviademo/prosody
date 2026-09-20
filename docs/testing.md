# Testing

```bash
pytest                                    # unit tier; corpus and render auto-skip
pytest -m corpus                          # needs corpus/ populated
FLPF_RENDER=1 pytest -m render            # studio PC only
FLPF_UPDATE_GOLDEN=1 pytest tests/unit/test_golden.py   # regenerate goldens
```

## Tiers

| Tier | Location | Needs | Runs |
| --- | --- | --- | --- |
| unit | `tests/unit/` | nothing | always, including CI |
| corpus | `tests/corpus/` | real `.flp` files in `corpus/` | locally |
| render | `tests/render/` | FL Studio + `FLPF_RENDER=1` | studio PC only, never CI |

Gating is automatic in `tests/conftest.py`: the corpus tier skips when `corpus/`
holds no `.flp`, the render tier skips unless `FLPF_RENDER=1`. Markers are
`--strict-markers`, so a typo in a marker name fails collection.

Current state: **217 unit tests pass; 3 corpus and 2 render tests skip**, in
under a second.

## What the unit tier proves

It parses **real FLP binaries** built by `tests/fixtures/flp_builder.py`
(ADR-0003), not mocks. Coverage by area:

| Area | File | Tests |
| --- | --- | --- |
| Architectural boundaries (parametrised per module) | `test_boundaries.py` | 67 |
| Name-based role hinting | `test_classify_rules.py` | 26 |
| Parser: headers, notes, playlist, mixer, degradation, corrupt input | `test_parse_pyflp.py` | 20 |
| Schemas, permission enforcement, section contiguity | `test_schemas.py` | 18 |
| Role vocabulary and aliases | `test_roles.py` | 15 |
| Pipeline end to end | `test_pipeline.py` | 13 |
| Genre profile data | `test_genre_profiles.py` | 12 |
| Filesystem safety and corpus immutability | `test_fs_safety.py` | 12 |
| CLI | `test_cli.py` | 12 |
| Health status and state classification | `test_health.py` | 10 |
| PyFLP compatibility shim | `test_pyflp_compat.py` | 6 |
| Golden output | `test_golden.py` | 6 |

## What the unit tier does **not** prove

Synthetic fixtures are written to the format as PyFLP reads it. If PyFLP
misreads something, a fixture can encode the same misunderstanding and the test
still passes. Only the corpus tier catches that. A green unit tier is **not**
evidence that real FL projects parse.

## Golden tests

`tests/golden/*.json` pin the normalised output of each fixture, with volatile
fields (`parsed_at`, `source_path`, `backend`, `id`, `source_bytes`) stripped.
An unintended change in parser output shows up as a diff. Regenerate only
deliberately, and read the diff before committing it.

Per SPEC.md section 8, five *real* projects should also get hand-written
goldens (tempo, bar count, pattern count, role per pattern). Those live outside
git alongside the corpus.

## Boundary tests

`tests/unit/test_boundaries.py` turns claims in ARCHITECTURE.md and
docs/privacy.md into assertions by walking every module's AST:

- PyFLP is imported only inside `parse/` (ADR-0001)
- no module imports anything network-capable — the privacy claim is verified,
  not promised
- nothing calls `print()`
- `model/` imports only pydantic and the stdlib
- the genre loader stays trivial, so genre behaviour stays in JSON
- no secret-shaped literals are committed

## Regression policy

SPEC.md section 17: every FLP bug found gets a fixture or a minimised
reproduction. For a crash in a real project, add the smallest fixture in
`flp_builder.py` that reproduces it — do not copy the project into the repo.
