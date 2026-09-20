"""Reading the machine type out of a Windows PE header.

The shell does this before spawning its own core; this is the same check for
the executable the *user* chooses in Settings. A 32-bit FL, or a path that
points at something that is not a program at all, otherwise fails deep inside
a render with an error that names neither (HARDENING P0.1).
"""

from __future__ import annotations

import struct
from pathlib import Path

MACHINE_AMD64 = 0x8664
MACHINE_ARM64 = 0xAA64
MACHINE_I386 = 0x014C

_LABELS = {
    MACHINE_AMD64: "64-bit (x64)",
    MACHINE_ARM64: "64-bit (ARM64)",
    MACHINE_I386: "32-bit (x86)",
}


def machine_type(path: Path) -> int | None:
    """The COFF machine type, or None when the file is not a PE at all."""
    try:
        with path.open("rb") as handle:
            if handle.read(2) != b"MZ":
                return None
            handle.seek(0x3C)
            raw = handle.read(4)
            if len(raw) != 4:
                return None
            handle.seek(struct.unpack("<I", raw)[0])
            if handle.read(4) != b"PE\0\0":
                return None
            raw = handle.read(2)
            if len(raw) != 2:
                return None
            return int(struct.unpack("<H", raw)[0])
    except OSError:
        return None


def label(machine: int | None) -> str:
    if machine is None:
        return "not a Windows program"
    return _LABELS.get(machine, f"unrecognised machine type 0x{machine:04X}")


def describe(path: Path) -> tuple[bool, str]:
    """``(ok, description)`` for a binary Prosody is about to run.

    ``ok`` is True only for a 64-bit PE. A non-PE file is reported as a
    problem with the *path*, because on Windows that is what it is: the user
    pointed Settings at something that is not FL Studio.
    """
    machine = machine_type(path)
    if machine in (MACHINE_AMD64, MACHINE_ARM64):
        return True, label(machine)
    return False, label(machine)
