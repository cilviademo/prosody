"""Backend protocol: the only seam through which .flp bytes enter the app.

Nothing outside ``flpfinisher/parse`` and (later) ``flpfinisher/write`` may
import a parser library. A second backend - flpdiff is the current candidate -
implements this protocol without any other module changing.
See docs/adr/ADR-0001-parser-backend.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from flpfinisher.model.schemas import BeatProject


class ParseError(RuntimeError):
    """The backend could not produce a BeatProject at all."""

    def __init__(self, path: Path, cause: BaseException | str) -> None:
        self.path = path
        self.cause = cause
        super().__init__(f"{path.name}: {cause}")


@runtime_checkable
class ParserBackend(Protocol):
    """Turns a path into a normalised :class:`BeatProject`."""

    @property
    def name(self) -> str:
        """Backend identifier including version, e.g. ``pyflp-2.2.1``."""
        ...

    def parse(self, path: Path) -> BeatProject:
        """Parse ``path``. Must never write to or move the source file.

        Raises:
            ParseError: when no usable project could be produced.
        """
        ...
