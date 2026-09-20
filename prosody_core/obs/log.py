"""Console + per-project run log. Nothing in this package calls print().

Every transformation must be explainable (product brief section 15), so the
operation log is structured: an op name plus key/value fields, rendered to the
console for a human and appended verbatim to ``out/<slug>/REPORTS/run.log``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from io import TextIOBase
from pathlib import Path
from typing import Any

from rich.console import Console

_console = Console()
_err_console = Console(stderr=True)


def console() -> Console:
    return _console


def error_console() -> Console:
    return _err_console


class RunLog:
    """Append-only structured log for one command invocation."""

    def __init__(self, handle: TextIOBase | None = None) -> None:
        self._handle = handle

    def op(self, name: str, **fields: Any) -> None:
        """Record one operation, e.g. ``op("PARSE_FLP", path=..., ok=True)``."""
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "op": name,
            **{k: _jsonable(v) for k, v in fields.items()},
        }
        if self._handle is not None:
            self._handle.write(json.dumps(record) + "\n")
            self._handle.flush()

    def info(self, message: str) -> None:
        self.op("INFO", message=message)
        _console.print(message)

    def warn(self, message: str) -> None:
        self.op("WARN", message=message)
        _console.print(f"[yellow]{message}[/yellow]")

    def error(self, message: str) -> None:
        self.op("ERROR", message=message)
        _err_console.print(f"[red]{message}[/red]")


@contextmanager
def run_log(path: Path | None) -> Iterator[RunLog]:
    """Open a RunLog writing to ``path``. ``None`` gives a console-only log."""
    if path is None:
        yield RunLog()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        yield RunLog(handle)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
