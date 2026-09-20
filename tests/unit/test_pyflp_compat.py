"""The shim that makes PyFLP 2.2.1 usable on Python >= 3.11.

See docs/adr/ADR-0002-pyflp-enum-compat.md. If PyFLP ever fixes this upstream,
``test_shim_is_idempotent`` and ``test_known_ids_resolve`` still pass and
``apply()`` becomes a no-op - that is the intended retirement path.
"""

import sys

import pytest

from flpfinisher.parse import _pyflp_compat


@pytest.fixture(autouse=True)
def shim_applied():
    _pyflp_compat.apply()


def test_interpreter_needing_the_shim_is_31_1_or_newer():
    """Documents *why* the shim exists, so the reason survives in CI output."""
    import enum
    import inspect

    guard = "has no members" in inspect.getsource(enum.Enum.__new__)
    assert guard == (sys.version_info >= (3, 11))


def test_known_ids_resolve_to_their_subclass_member():
    from pyflp._events import EventEnum
    from pyflp.project import ProjectID

    assert EventEnum(199) is ProjectID.FLVersion
    assert EventEnum(156) is ProjectID.Tempo


def test_unknown_ids_become_pseudo_members_rather_than_raising():
    """EXECUTE.md T1: unknown events are kept, never dropped."""
    from pyflp._events import EventEnum

    member = EventEnum(253)
    assert int(member) == 253


def test_shim_does_not_change_public_enum_iteration():
    from pyflp._events import EventEnum

    assert list(EventEnum) == []
    assert EventEnum._member_names_ == []


def test_shim_is_idempotent():
    from pyflp._events import EventEnum

    before = len(EventEnum._member_map_)
    assert _pyflp_compat.apply() is False
    assert len(EventEnum._member_map_) == before


def test_sentinel_value_cannot_collide_with_a_real_event_id():
    assert _pyflp_compat.SENTINEL_VALUE not in range(256)
