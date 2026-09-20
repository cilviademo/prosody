"""Line-delimited JSON server over stdio.

One request per line in, one or more lines out, correlated by ``id``:

    -> {"id": 1, "method": "ping"}
    <- {"id": 1, "ok": true, "version": "0.1.0"}

    -> {"id": 7, "method": "build.run", "params": {...}}
    <- {"id": 7, "event": "progress", "stage": "...", "status": "running"}
    <- {"id": 7, "event": "progress", "stage": "...", "status": "ok"}
    <- {"id": 7, "ok": true, "data": {...}}

Why stdio and not a localhost HTTP server: no port to collide, no firewall
prompt on first launch, and the process dies with its parent. The executable is
built as a console binary so stdin/stdout exist at all, and the desktop shell
spawns it with CREATE_NO_WINDOW so no console ever appears.

The loop never raises. A malformed line, an unknown method or a handler
exception all produce a response envelope, because a silent backend looks
identical to a hung one from the UI.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from prosody_core import __version__, api
from prosody_core.workspace import Workspace

#: Methods handled by the server itself rather than the API table.
PING = "ping"
SHUTDOWN = "shutdown"


class Session:
    """Reads requests from one stream and writes envelopes to another."""

    def __init__(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        workspace: Workspace | None = None,
    ) -> None:
        self._in = stdin if stdin is not None else sys.stdin
        self._out = stdout if stdout is not None else sys.stdout
        self._workspace = workspace
        self._current_id: Any = None

    # -- output ------------------------------------------------------------ #

    def write(self, payload: dict[str, Any]) -> None:
        line = dict(payload)
        if self._current_id is not None and "id" not in line:
            line["id"] = self._current_id
        self._out.write(json.dumps(line) + "\n")
        self._out.flush()

    # -- workspace --------------------------------------------------------- #

    def workspace(self, params: dict[str, Any]) -> Workspace:
        """Resolve the workspace once and reuse it across requests.

        A request may override it (tests, portable mode); otherwise the first
        resolution is cached so every request shares one SQLite file.
        """
        override = params.get("workspace")
        if override:
            return Workspace.open(Path(str(override)))
        if self._workspace is None:
            self._workspace = Workspace.open()
        return self._workspace

    # -- request handling -------------------------------------------------- #

    def handle(self, line: str) -> bool:
        """Process one request line. Returns False when the peer asked to stop."""
        text = line.strip()
        if not text:
            return True

        try:
            request = json.loads(text)
        except json.JSONDecodeError as exc:
            self.write({"ok": False, "error": "bad_request", "detail": str(exc)})
            return True

        if not isinstance(request, dict):
            self.write({"ok": False, "error": "bad_request",
                        "detail": "a request must be a JSON object"})
            return True

        self._current_id = request.get("id")
        method = str(request.get("method", ""))
        params = request.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        try:
            if method == PING:
                self.write({"ok": True, "version": __version__})
                return True
            if method == SHUTDOWN:
                self.write({"ok": True})
                return False
            if not method:
                self.write({"ok": False, "error": "bad_request",
                            "detail": "no method given"})
                return True

            with api.sink(self.write):
                api.dispatch(method, params, self.workspace(params))
        except Exception as exc:  # noqa: BLE001 - the loop must never die
            self.write({"ok": False, "error": "internal",
                        "detail": f"{type(exc).__name__}: {exc}"})
        finally:
            self._current_id = None
        return True

    def serve(self) -> int:
        for line in self._in:
            if not self.handle(line):
                break
        return 0


def serve(
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    workspace: Workspace | None = None,
) -> int:
    return Session(stdin, stdout, workspace).serve()


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])

    if argv and argv[0] in ("--version", "-V"):
        sys.stdout.write(__version__ + "\n")
        return 0

    # One-shot mode keeps the diagnostic path working:
    #   prosody-core.exe project.inspect '{"path": "..."}'
    if argv and not argv[0].startswith("-"):
        return api.main(argv)

    return serve()


#: Exported so __main__ and the console-script entry point share one function.
entry: Callable[[], int] = main
