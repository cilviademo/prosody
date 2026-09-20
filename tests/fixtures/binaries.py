"""Stand-ins for Windows executables.

A test that needs "a configured FL Studio" used to write an empty file named
FL64.exe. That stopped being good enough once Prosody started reading the PE
header before it spawns anything (HARDENING P0.1): an empty file is correctly
judged not to be a program, so the fixture has to be one.
"""

from __future__ import annotations

import struct
from pathlib import Path

MACHINE_AMD64 = 0x8664
MACHINE_I386 = 0x014C


def pe_bytes(machine: int = MACHINE_AMD64, lfanew: int = 0x100) -> bytes:
    """The smallest byte sequence Prosody's PE reader accepts.

    Not a runnable program — nothing here executes it — but a real DOS header,
    a real e_lfanew pointer and a real COFF machine field, placed the way a
    linker places them.
    """
    data = bytearray(lfanew + 64)
    data[0:2] = b"MZ"
    data[0x3C:0x40] = struct.pack("<I", lfanew)
    data[lfanew:lfanew + 4] = b"PE\0\0"
    data[lfanew + 4:lfanew + 6] = struct.pack("<H", machine)
    return bytes(data)


def fake_fl(directory: Path, name: str = "FL64.exe", machine: int = MACHINE_AMD64) -> Path:
    """Write a stand-in FL Studio executable and return its path."""
    path = Path(directory) / name
    path.write_bytes(pe_bytes(machine))
    return path
