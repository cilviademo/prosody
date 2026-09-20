"""Compatibility shim for PyFLP 2.2.1 on Python >= 3.11.

PyFLP resolves every event id through ``EventEnum(id)``. ``EventEnum`` declares
no members of its own; the correct member lives on a subclass and is found by
``EventEnum._missing_``. CPython 3.11 added a guard to ``Enum.__new__`` that
raises ``TypeError`` on a member-less Enum *before* ``_missing_`` is consulted:

    if not cls._member_map_:
        raise TypeError("%r has no members defined" % cls)

The result is that PyFLP 2.2.1 cannot parse *any* .flp on Python 3.11, 3.12 or
3.13 - the very first event id raises. Measured in Phase 0; see
docs/adr/ADR-0002-pyflp-enum-compat.md.

The fix is to seed ``_member_map_`` with a single sentinel whose value (-1) can
never collide with an event id (ids are 0-255). The guard then passes and
``_missing_`` runs exactly as upstream intends. ``_member_names_`` is left
untouched, so ``list(EventEnum)`` and every other public enum behaviour is
unchanged.

This is deliberately the smallest possible intervention. It touches no parsing
logic and disappears the moment PyFLP ships its own fix.
"""

from __future__ import annotations

SENTINEL_NAME = "_FLPF_COMPAT_SENTINEL"
SENTINEL_VALUE = -1


def enum_guard_blocks_lookup() -> bool:
    """True when this interpreter's Enum guard would break PyFLP unpatched."""
    from pyflp._events import EventEnum

    if EventEnum._member_map_:
        return False
    try:
        EventEnum(199)  # ProjectID.FLVersion - present in every real project
    except TypeError:
        return True
    except Exception:  # noqa: BLE001 - any other failure is not ours to mask
        return False
    return False


def apply() -> bool:
    """Install the shim if this interpreter needs it.

    Returns True when the shim was applied, False when it was unnecessary.
    Safe to call repeatedly.
    """
    from pyflp._events import EventEnum

    if EventEnum._member_map_:
        return False

    sentinel = int.__new__(EventEnum, SENTINEL_VALUE)
    sentinel._name_ = SENTINEL_NAME
    sentinel._value_ = SENTINEL_VALUE
    # Only _member_map_ is seeded. _member_names_ stays empty so iteration,
    # __contains__ over real ids and repr of real members are unaffected.
    EventEnum._member_map_[SENTINEL_NAME] = sentinel
    return True
