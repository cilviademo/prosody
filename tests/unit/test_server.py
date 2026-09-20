"""The stdio JSON-lines protocol the desktop shell speaks to the core.

The startup contract in RELEASE.md is explicit: the shell spawns the core,
sends ``ping``, and expects a reply within 10 seconds. Everything here protects
that contract and the "the loop never dies" property — a backend that stops
answering is indistinguishable from a hung one in the UI.
"""

import io
import json

import pytest

from prosody_core import __version__
from prosody_core.server import Session, main, serve
from prosody_core.workspace import Workspace
from tests.fixtures.projects import full_kit


def run(lines: list[str], workspace: Workspace) -> list[dict]:
    """Feed request lines through a session and collect the envelopes."""
    stdin = io.StringIO("".join(line + "\n" for line in lines))
    stdout = io.StringIO()
    serve(stdin, stdout, workspace)
    return [json.loads(raw) for raw in stdout.getvalue().splitlines() if raw.strip()]


@pytest.fixture
def workspace(tmp_path):
    return Workspace.open(tmp_path / "Prosody")


# -- the startup contract --------------------------------------------------- #

def test_ping_answers_with_the_version(workspace):
    [reply] = run(['{"id": 1, "method": "ping"}'], workspace)
    assert reply == {"id": 1, "ok": True, "version": __version__}


def test_ping_is_answered_before_any_project_work(workspace):
    """Ping must not depend on a project, a database or FL Studio."""
    replies = run(['{"id": 1, "method": "ping"}'], workspace)
    assert replies[0]["ok"] is True


def test_shutdown_acknowledges_then_stops_the_loop(workspace):
    replies = run([
        '{"id": 1, "method": "shutdown"}',
        '{"id": 2, "method": "ping"}',
    ], workspace)
    assert replies == [{"id": 1, "ok": True}]


# -- correlation ------------------------------------------------------------ #

def test_every_envelope_carries_its_request_id(workspace):
    replies = run(['{"id": 42, "method": "genres"}'], workspace)
    assert replies
    assert all(r["id"] == 42 for r in replies)


def test_requests_are_answered_in_order(workspace):
    replies = run([
        '{"id": 1, "method": "ping"}',
        '{"id": 2, "method": "genres"}',
        '{"id": 3, "method": "ping"}',
    ], workspace)
    assert [r["id"] for r in replies] == [1, 2, 3]


def test_a_string_id_is_preserved(workspace):
    [reply] = run(['{"id": "abc", "method": "ping"}'], workspace)
    assert reply["id"] == "abc"


def test_a_request_without_an_id_still_gets_a_reply(workspace):
    [reply] = run(['{"method": "ping"}'], workspace)
    assert reply["ok"] is True
    assert "id" not in reply


# -- the loop never dies ---------------------------------------------------- #

def test_malformed_json_is_answered_not_fatal(workspace):
    replies = run(['not json at all', '{"id": 2, "method": "ping"}'], workspace)
    assert replies[0]["ok"] is False
    assert replies[0]["error"] == "bad_request"
    assert replies[1]["ok"] is True


def test_a_json_array_is_rejected_cleanly(workspace):
    [reply] = run(['[1, 2, 3]'], workspace)
    assert reply["ok"] is False and reply["error"] == "bad_request"


def test_an_unknown_method_is_answered(workspace):
    [reply] = run(['{"id": 1, "method": "nope"}'], workspace)
    assert reply["ok"] is False
    assert reply["error"] == "unknown_method"


def test_a_missing_method_is_answered(workspace):
    [reply] = run(['{"id": 1}'], workspace)
    assert reply["ok"] is False and reply["error"] == "bad_request"


def test_blank_lines_are_ignored(workspace):
    replies = run(['', '   ', '{"id": 1, "method": "ping"}'], workspace)
    assert len(replies) == 1


def test_a_failing_handler_does_not_stop_the_loop(workspace):
    replies = run([
        '{"id": 1, "method": "project.inspect", "params": {"path": "/nope.flp"}}',
        '{"id": 2, "method": "ping"}',
    ], workspace)
    assert replies[0]["ok"] is False
    assert replies[1]["ok"] is True


def test_bad_params_type_is_tolerated(workspace):
    [reply] = run(['{"id": 1, "method": "genres", "params": 5}'], workspace)
    assert reply["ok"] is True


# -- real work over the protocol -------------------------------------------- #

def test_inspect_round_trips_over_stdio(workspace, make_flp):
    source = make_flp(full_kit(), "Starfall.flp")
    request = json.dumps({"id": 9, "method": "project.inspect",
                          "params": {"path": str(source)}})
    [reply] = run([request], workspace)
    assert reply["ok"] is True
    assert reply["data"]["tempo"] == 142.0


def test_build_streams_progress_then_a_result_on_one_id(workspace, make_flp, tmp_path):
    source = make_flp(full_kit(), "Starfall.flp")
    request = json.dumps({
        "id": 5, "method": "build.run",
        "params": {"path": str(source), "genre": "rnb", "wav": False,
                   "mp3": False, "exportRoot": str(tmp_path / "Exports")},
    })
    replies = run([request], workspace)
    assert all(r["id"] == 5 for r in replies)
    progress = [r for r in replies if r.get("event") == "progress"]
    assert progress, "the shell needs stage progress to show anything"
    assert replies[-1]["ok"] is True
    assert replies[-1]["data"]["tier"] == "native"


def test_one_session_serves_many_requests(workspace, make_flp):
    """The core is long-lived: no per-call process spawn in the release build."""
    source = make_flp(full_kit(), "Starfall.flp")
    replies = run([
        '{"id": 1, "method": "ping"}',
        json.dumps({"id": 2, "method": "project.inspect",
                    "params": {"path": str(source)}}),
        json.dumps({"id": 3, "method": "arrange.plan",
                    "params": {"path": str(source), "genre": "hiphop"}}),
        '{"id": 4, "method": "ping"}',
    ], workspace)
    assert [r["id"] for r in replies if "ok" in r] == [1, 2, 3, 4]
    assert all(r["ok"] for r in replies if "ok" in r)


def test_the_workspace_is_reused_across_requests(tmp_path, make_flp):
    """A single SQLite file, not one per call."""
    source = make_flp(full_kit(), "Starfall.flp")
    workspace = Workspace.open(tmp_path / "Prosody")
    session = Session(io.StringIO(), io.StringIO(), workspace)
    first = session.workspace({})
    second = session.workspace({})
    assert first.root == second.root == workspace.root
    del source


def test_a_request_may_override_the_workspace(tmp_path):
    session = Session(io.StringIO(), io.StringIO())
    other = tmp_path / "Elsewhere"
    assert session.workspace({"workspace": str(other)}).root == other


# -- entry point ------------------------------------------------------------ #

def test_version_flag(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_one_shot_mode_still_works(capsys, make_flp):
    """The diagnostic path: one method, one answer, exit."""
    source = make_flp(full_kit(), "Starfall.flp")
    assert main(["project.inspect", json.dumps({"path": str(source)})]) == 0
    payload = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert payload["ok"] is True
