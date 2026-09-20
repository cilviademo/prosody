"""Golden tests: a known project must always normalise to the same JSON.

SPEC.md section 8 reserves ``golden/<slug>.json`` for five hand-checked real
projects. Those cannot live in git, so the same mechanism is applied here to the
synthetic fixtures: any change in parser output that is not deliberate shows up
as a diff. Regenerate intentionally with ``FLPF_UPDATE_GOLDEN=1 pytest``.
"""

import json
import os
from pathlib import Path

import pytest
from fixtures.flp_builder import FIXTURES, write_flp

from flpfinisher.pipeline import inspect_project

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "golden"

#: Fields that legitimately differ between runs and machines.
_VOLATILE = {"parsed_at", "source_path", "backend", "id", "source_bytes"}


def _normalise(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k not in _VOLATILE}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_fixture_normalises_to_its_golden_json(name, tmp_path):
    path = write_flp(FIXTURES[name](), tmp_path / f"{name}.flp")
    result = inspect_project(path)
    actual = _normalise(result.project.model_dump(mode="json"))
    actual["_health_status"] = result.health.status.value
    actual["_state"] = result.analysis.state.value

    golden = GOLDEN_DIR / f"{name}.json"
    if os.environ.get("FLPF_UPDATE_GOLDEN") == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
        pytest.skip(f"regenerated {golden.name}")

    assert golden.is_file(), (
        f"missing {golden}; regenerate with FLPF_UPDATE_GOLDEN=1 pytest"
    )
    assert actual == json.loads(golden.read_text())
