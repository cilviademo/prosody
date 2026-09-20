"""HARDENING P1.4: the System Check tells the truth, and leaks nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from prosody_core.api import HANDLERS
from prosody_core.health.systemcheck import Verdict, run, sanitized_report
from prosody_core.workspace import Workspace


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace.open(tmp_path / "docs", tmp_path / "state")


def test_every_row_has_a_verdict_and_a_reason(workspace):
    result = run(workspace)
    assert result["rows"], "the check produced no rows"
    for row in result["rows"]:
        assert row["verdict"] in {v.value for v in Verdict}
        assert row["detail"].strip(), f"{row['name']} gives a verdict with no reason"
        assert row["name"].strip()


def test_a_machine_with_no_fl_studio_is_not_a_failure(workspace):
    """"I have not installed FL Studio" must not look like a broken program."""
    result = run(workspace)
    rows = {r["name"]: r for r in result["rows"]}
    assert rows["FL Studio"]["verdict"] in {"PASS", "UNAVAILABLE"}
    if rows["FL Studio"]["verdict"] == "UNAVAILABLE":
        assert rows["Render engine"]["verdict"] == "UNAVAILABLE"
        assert result["ok"] is True, "a missing FL Studio must not fail the check"


def test_ffmpeg_absence_is_explained_not_just_reported(workspace):
    rows = {r["name"]: r for r in run(workspace)["rows"]}
    assert "not required" in rows["ffmpeg"]["detail"]


def test_the_writable_checks_really_write(workspace, monkeypatch):
    """Permission bits lie on Windows; only a write proves a write."""
    real_write = Path.write_bytes

    def deny(self, *args, **kwargs):
        if "Exports" in self.parts:
            raise PermissionError("read-only")
        return real_write(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_bytes", deny)
    result = run(workspace)
    rows = {r["name"]: r for r in result["rows"]}
    assert rows["Exports writable"]["verdict"] == "FAIL"
    assert result["ok"] is False, "an unwritable export folder must fail the check"


def test_a_quarantined_index_is_reported_with_the_way_out(workspace):
    from prosody_core.index import db

    db.migrate(workspace.db_path)
    workspace.db_path.write_bytes(b"not a database")

    rows = {r["name"]: r for r in run(workspace)["rows"]}
    assert rows["Library index"]["verdict"] == "WARNING"
    assert "Rebuild Library" in rows["Library index"]["detail"]


def test_safe_mode_shows_as_unavailable_not_broken(workspace, monkeypatch):
    monkeypatch.setenv("PROSODY_SAFE_MODE", "1")
    result = run(workspace)
    rows = {r["name"]: r for r in result["rows"]}
    assert rows["FL Studio"]["verdict"] == "UNAVAILABLE"
    assert "Safe Mode" in rows["FL Studio"]["detail"]
    assert result["ok"] is True


# --- the sanitized report ---------------------------------------------------- #

def test_the_report_hides_the_user_profile_path(workspace, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: workspace.root.parent))
    report = sanitized_report(workspace)
    assert str(workspace.root.parent) not in report
    assert "~" in report


def test_the_report_never_contains_an_api_key(workspace, monkeypatch):
    secret = "sk-ant-THISMUSTNEVERAPPEAR0123456789"
    workspace.save_settings({"anthropic_api_key": secret})
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)

    report = sanitized_report(workspace)
    assert secret not in report
    assert "sk-ant" not in report

    payload = HANDLERS["system.check"]({}, workspace)
    assert secret not in repr(payload)


def test_the_planner_row_reports_what_will_actually_happen(workspace, monkeypatch):
    """A key present does not mean AI planning runs; it is not wired up yet.

    Reporting "configured" here would be the exact kind of comfortable lie
    System Check exists to prevent.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-anything")
    rows = {r["name"]: r for r in run(workspace)["rows"]}
    assert rows["AI planner"]["verdict"] == "UNAVAILABLE"
    assert "rules-only" in rows["AI planner"]["detail"]
    assert "not wired up" in rows["AI planner"]["detail"]


def test_the_report_is_plain_text_a_user_can_paste(workspace):
    report = sanitized_report(workspace)
    assert report.startswith("PROSODY SYSTEM CHECK")
    assert report.endswith("\n")
    assert "pass" in report and "fail" in report


def test_the_api_exposes_the_check_with_its_report(workspace):
    payload = HANDLERS["system.check"]({}, workspace)
    assert payload["rows"] and payload["report"]
    assert set(payload["counts"]) == {v.value for v in Verdict}
