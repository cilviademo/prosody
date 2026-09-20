"""Genre profiles are data, not code.

Each JSON file in this package is loaded into a
:class:`~prosody_core.model.schemas.GenreProfile`. Adding a genre means adding a
file, never editing a function - which is the point of SPEC.md section 6.

No planner consumes these yet; the loader exists so the profiles are validated
against the schema from the moment they are written.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from prosody_core.model.schemas import GenreProfile

PROFILE_DIR = Path(__file__).resolve().parent


#: Presentation order for the genre picker. Genres not listed here follow,
#: alphabetically, so adding a profile file is still all that is required.
DISPLAY_ORDER: tuple[str, ...] = ("hiphop", "rnb", "pop", "trap", "edm", "dnb")


def available() -> list[str]:
    found = {p.stem for p in PROFILE_DIR.glob("*.json")}
    ordered = [name for name in DISPLAY_ORDER if name in found]
    return ordered + sorted(found - set(ordered))


@cache
def load(genre: str) -> GenreProfile:
    """Load and validate one profile by name.

    Raises:
        FileNotFoundError: when no profile exists for ``genre``.
        pydantic.ValidationError: when the file does not match the schema.
    """
    path = PROFILE_DIR / f"{genre}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"no genre profile {genre!r}; available: {', '.join(available())}"
        )
    return GenreProfile.model_validate(json.loads(path.read_text(encoding="utf-8")))
