"""Shared test configuration.

Tiers (CLAUDE.md):
  tests/unit    always runs, no real projects, no FL Studio
  tests/corpus  marked ``corpus``; skipped unless corpus/ holds real .flp files
  tests/render  marked ``render``; skipped unless FLPF_RENDER=1
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fixtures.flp_builder import FIXTURES, FlpSpec, write_flp

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "corpus"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    corpus_files = list(CORPUS_DIR.rglob("*.flp")) if CORPUS_DIR.exists() else []
    skip_corpus = pytest.mark.skip(reason="no .flp files in corpus/ (see docs/testing.md)")
    skip_render = pytest.mark.skip(reason="FLPF_RENDER is not 1")

    for item in items:
        if "corpus" in item.keywords and not corpus_files:
            item.add_marker(skip_corpus)
        if "render" in item.keywords and os.environ.get("FLPF_RENDER") != "1":
            item.add_marker(skip_render)


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path_factory, monkeypatch):
    """Point every workspace at a temporary directory.

    Without this, any code path that opens a default Workspace writes into the
    developer's real ``Documents/Prosody`` and ``%LOCALAPPDATA%/Prosody`` — and
    shares one SQLite file across the whole suite, which makes tests pass or
    fail depending on what ran before them.
    """
    home = tmp_path_factory.mktemp("prosody-home")
    state = tmp_path_factory.mktemp("prosody-state")
    monkeypatch.setenv("PROSODY_HOME", str(home))
    monkeypatch.setenv("PROSODY_STATE", str(state))
    return home, state


@pytest.fixture
def make_flp(tmp_path: Path):
    """Write a synthetic .flp into tmp_path and return its path."""

    def _make(spec: FlpSpec, name: str = "fixture.flp") -> Path:
        return write_flp(spec, tmp_path / name)

    return _make


@pytest.fixture
def all_fixture_flps(tmp_path: Path) -> dict[str, Path]:
    """Every named fixture, written to disk."""
    return {
        name: write_flp(build(), tmp_path / f"{name}.flp")
        for name, build in FIXTURES.items()
    }


@pytest.fixture
def corpus_flps() -> list[Path]:
    return sorted(CORPUS_DIR.rglob("*.flp")) if CORPUS_DIR.exists() else []
