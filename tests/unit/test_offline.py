"""Prosody makes no network calls.

`test_boundaries` proves nothing network-capable is *imported*. This proves
nothing is *called*: every socket entry point is replaced with a landmine and a
full build is run over it. A release is expected to work on a machine with the
adapter disabled, and that claim should fail loudly here rather than quietly on
a user's machine.
"""

import socket

import pytest

from prosody_core.api import dispatch
from prosody_core.build import BuildOptions, build
from prosody_core.workspace import Workspace
from tests.fixtures.projects import full_kit


class NetworkUsed(AssertionError):
    """Raised by the landmine when anything reaches for the network."""


@pytest.fixture
def no_network(monkeypatch):
    """Make every outbound path fail loudly."""

    def landmine(*args, **kwargs):
        raise NetworkUsed("Prosody attempted a network call")

    monkeypatch.setattr(socket, "socket", landmine)
    monkeypatch.setattr(socket, "create_connection", landmine)
    monkeypatch.setattr(socket, "getaddrinfo", landmine)
    monkeypatch.setattr(socket, "gethostbyname", landmine)
    return landmine


@pytest.fixture
def workspace(tmp_path):
    return Workspace.open(tmp_path / "Prosody")


def test_the_landmine_actually_fires(no_network):
    """Guard the guard: a test that cannot fail proves nothing."""
    with pytest.raises(NetworkUsed):
        socket.socket()


def test_a_full_build_runs_with_the_network_unplugged(
    no_network, make_flp, tmp_path
):
    source = make_flp(full_kit(), "Starfall.flp")
    result = build(
        source,
        export_root=tmp_path / "Exports",
        options=BuildOptions(genre="rnb", want_wav=False, want_mp3=False),
    )
    assert result.tier.value == "native"
    assert result.ok


def test_inspection_runs_offline(no_network, workspace, make_flp):
    captured: list[dict] = []
    import prosody_core.api as api_module

    source = make_flp(full_kit(), "Starfall.flp")
    original = api_module.emit
    api_module.emit = captured.append
    try:
        dispatch("project.inspect", {"path": str(source)}, workspace)
    finally:
        api_module.emit = original
    assert captured[-1]["ok"] is True


def test_planning_runs_offline(no_network, workspace, make_flp):
    import prosody_core.api as api_module

    captured: list[dict] = []
    source = make_flp(full_kit(), "Starfall.flp")
    original = api_module.emit
    api_module.emit = captured.append
    try:
        dispatch("arrange.plan", {"path": str(source), "genre": "hiphop"},
                 workspace)
    finally:
        api_module.emit = original
    assert captured[-1]["ok"] is True
    assert captured[-1]["data"]["totalBars"] == 80


def test_the_default_planner_is_rules_only(workspace):
    """Nothing reaches for a provider unless the user opts in."""
    assert workspace.load_settings()["ai_provider"] == "rules"


def test_no_api_key_is_read_at_import_time(monkeypatch):
    """Importing the package must not touch provider credentials."""
    import importlib

    seen: list[str] = []
    real_get = __import__("os").environ.get

    def watched(key, default=None):
        if "API_KEY" in key:
            seen.append(key)
        return real_get(key, default)

    monkeypatch.setattr("os.environ.get", watched)
    for module in ("prosody_core.build", "prosody_core.api", "prosody_core.server"):
        importlib.reload(importlib.import_module(module))
    assert seen == []
