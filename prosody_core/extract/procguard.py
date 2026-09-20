"""Owning the processes we start, so a crash cannot leave renders running.

HARDENING P0.5. A command-line FL Studio render can run for minutes. If
Prosody dies while one is in flight — a crash, the user ending the task, a
forced sign-out — the FL process it started keeps going, holding a CPU and an
output file, with no window the user can find to stop it.

Windows solves this with a Job Object: a kernel container for processes with
``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` set. When the last handle to the job
closes — including because the owning process died — the kernel terminates
everything in it. That is the guarantee, and it does not depend on Prosody
getting a chance to clean up.

Two things this deliberately does not do:

* It never touches an FL Studio that Prosody did not start. A producer with a
  session open must not lose it because Prosody tidied up.
* It is not a sandbox. The job limits lifetime, nothing else.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes
from typing import Any

#: ``JobObjectExtendedLimitInformation``
_EXTENDED_LIMIT_INFORMATION = 9
#: ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``
_KILL_ON_JOB_CLOSE = 0x00002000

_JOB_ALL_ACCESS = 0x1F001F
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def supported() -> bool:
    return os.name == "nt"


class ProcessGuard:
    """A job object that kills whatever was assigned to it when it closes.

    Used as a context manager around a render. Everything about it is
    best-effort: a machine or policy that refuses job objects must still be
    able to render, so a failure here is recorded and ignored rather than
    raised. That is the right trade — the guard prevents an orphan, it is not
    what makes a render correct.
    """

    def __init__(self) -> None:
        self.handle: int | None = None
        self.reason: str = "not supported on this platform"
        if not supported():
            return
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            handle = kernel32.CreateJobObjectW(None, None)
            if not handle:
                self.reason = f"CreateJobObject failed ({ctypes.get_last_error()})"
                return

            info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(
                handle, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)
            ):
                self.reason = f"SetInformationJobObject failed ({ctypes.get_last_error()})"
                kernel32.CloseHandle(handle)
                return

            self._kernel32: Any = kernel32
            self.handle = int(handle)
            self.reason = "active"
        except (OSError, AttributeError) as exc:
            self.reason = f"unavailable: {exc}"

    @property
    def active(self) -> bool:
        return self.handle is not None

    def adopt(self, process: subprocess.Popen[Any]) -> bool:
        """Put an already-started process under this job.

        There is an unavoidable window between spawn and assignment. It is
        microseconds, and the alternative — CREATE_SUSPENDED and a manual
        resume — needs far more Windows plumbing for a smaller gap.
        """
        if self.handle is None:
            return False
        try:
            kernel32 = self._kernel32
            kernel32.OpenProcess.restype = wintypes.HANDLE
            target = kernel32.OpenProcess(
                _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, int(process.pid)
            )
            if not target:
                return False
            try:
                return bool(
                    kernel32.AssignProcessToJobObject(wintypes.HANDLE(self.handle), target)
                )
            finally:
                kernel32.CloseHandle(target)
        except (OSError, AttributeError):
            return False

    def close(self) -> None:
        """Close the job, which terminates anything still in it."""
        if self.handle is None:
            return
        try:
            self._kernel32.CloseHandle(wintypes.HANDLE(self.handle))
        except (OSError, AttributeError):
            pass
        finally:
            self.handle = None

    def __enter__(self) -> ProcessGuard:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
