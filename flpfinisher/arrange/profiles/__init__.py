"""Genre profiles are data, not code.

Each JSON file in this package is loaded into a
:class:`~flpfinisher.model.schemas.GenreProfile`. Adding a genre means adding a
file, never editing a function - which is the point of SPEC.md section 6.

No planner consumes these yet; the loader exists so the profiles are validated
against the schema from the moment they are written.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from flpfinisher.model.schemas import GenreProfile

PROFILE_DIR = Path(__file__).resolve().parent


def available() -> list[str]:
    return sorted(p.stem for p in PROFILE_DIR.glob("*.json"))


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
