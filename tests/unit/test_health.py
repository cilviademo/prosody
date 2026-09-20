"""Health must never hide uncertainty, and must not flip on cosmetic notices."""

import pytest
from fixtures.flp_builder import (
    arranged_project,
    empty_project,
    missing_sample_project,
    multi_pattern_loop,
    one_pattern_loop,
)

from flpfinisher.health.check import check_project, classify_state
from flpfinisher.model.schemas import HealthStatus, ProjectState
from flpfinisher.parse.pyflp_backend import PyFLPBackend


@pytest.fixture
def backend():
    return PyFLPBackend()


def test_empty_project_is_blocked(backend, make_flp):
    report = check_project(backend.parse(make_flp(empty_project())))
    assert report.status is HealthStatus.BLOCKED


def test_missing_samples_route_to_freeze_mode(backend, make_flp):
    report = check_project(backend.parse(make_flp(missing_sample_project())))
    assert report.status is HealthStatus.REQUIRES_FREEZE
    assert report.samples_missing == 1
    assert report.recommended_mode == "stem"
    assert report.missing_assets[0].kind == "sample"


def test_undeterminable_checks_report_none_not_a_pass(backend, make_flp):
    report = check_project(backend.parse(make_flp(one_pattern_loop())),
                           can_check_plugins=False)
    undetermined = {c.name for c in report.checks if c.ok is None}
    assert "plugins_available" in undetermined
    assert "write_compatibility" in undetermined
    assert report.status is HealthStatus.UNKNOWN


def test_render_test_is_reported_as_skipped_never_assumed_passing(backend, make_flp):
    report = check_project(backend.parse(make_flp(one_pattern_loop())))
    assert report.render_test == "skipped"


def test_informational_parse_notes_do_not_fail_parse_clean(backend, make_flp):
    project = backend.parse(make_flp(one_pattern_loop()))
    assert project.parse_warnings  # the mixer-params note
    report = check_project(project)
    parse_clean = next(c for c in report.checks if c.name == "parse_clean")
    assert parse_clean.ok is True


def test_health_report_carries_the_project_id(backend, make_flp):
    project = backend.parse(make_flp(one_pattern_loop()))
    assert check_project(project).project_id == project.id


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        (empty_project, ProjectState.EMPTY),
        (one_pattern_loop, ProjectState.LOOP),
        (multi_pattern_loop, ProjectState.LOOP),
        (arranged_project, ProjectState.PARTIAL),
    ],
)
def test_state_classification(backend, make_flp, build, expected):
    assert classify_state(backend.parse(make_flp(build()))) is expected


def test_every_status_has_human_wording():
    """Raw enum names must never reach a primary surface."""
    from flpfinisher.health.check import human_status

    for status in HealthStatus:
        label = human_status(status)
        assert label and label != status.value
        assert "_" not in label
        assert not label.isupper()
