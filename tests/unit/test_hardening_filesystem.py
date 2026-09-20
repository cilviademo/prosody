"""HARDENING P2.4: the paths real projects actually have.

Every name here is one a producer would plausibly use. They are tested rather
than hoped about, because each one has a specific way of breaking: a space
breaks a command line that was joined into a string, an apostrophe breaks
quoting, an emoji breaks a non-UTF-8 code page, and a 250-character path breaks
MAX_PATH.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from prosody_core.api import HANDLERS, validate_source_path
from prosody_core.fs.safety import slugify
from prosody_core.fs.source import LONG_PATH_THRESHOLD, atomic_write, long_path
from prosody_core.workspace import Workspace
from tests.fixtures.projects import full_kit

AWKWARD_NAMES = [
    "My Beat.flp",
    "Beat (final) (2).flp",
    "Don't Stop.flp",
    "100% Done.flp",
    "Drum & Bass #3.flp",
    "Café Sessions.flp",
    "지금.flp",
    "beat 🔥 fire.flp",
    "  leading and trailing  .flp",
    "UPPERCASE.FLP",
]


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace.open(tmp_path / "docs", tmp_path / "state")


@pytest.mark.parametrize("name", AWKWARD_NAMES)
def test_an_awkwardly_named_project_builds(workspace, make_flp, tmp_path, name):
    from tests.fixtures.flp_builder import build_flp

    source = tmp_path / name
    try:
        source.write_bytes(build_flp(full_kit()))
    except (OSError, UnicodeEncodeError) as exc:
        pytest.skip(f"this filesystem cannot hold {name!r}: {exc}")

    result = HANDLERS["build.run"]({"path": str(source), "genre": "rnb"}, workspace)
    out_dir = Path(result["outDir"])
    assert out_dir.is_dir(), f"no output for {name!r}"
    assert (out_dir / "data" / "project.json").is_file()

    # The folder name is derived, so it must be safe whatever the input was.
    for char in '<>:"/\\|?*':
        assert char not in out_dir.name, f"{char!r} survived into {out_dir.name!r}"


@pytest.mark.parametrize("name", AWKWARD_NAMES)
def test_slugify_never_produces_a_path_separator(name):
    slug = slugify(Path(name).stem)
    assert slug, f"{name!r} slugified to nothing"
    assert "/" not in slug and "\\" not in slug
    assert not slug.startswith("-") and not slug.endswith("-")


def test_a_deeply_nested_source_is_accepted(workspace, tmp_path):
    from tests.fixtures.flp_builder import build_flp

    deep = tmp_path
    for level in range(12):
        deep = deep / f"level-{level}-a-reasonably-long-folder-name"
    try:
        deep.mkdir(parents=True)
    except OSError as exc:
        pytest.skip(f"cannot create a deep tree here: {exc}")

    source = deep / "Nested.flp"
    source.write_bytes(build_flp(full_kit()))
    assert len(str(source)) > 250 or os.name != "nt"

    assert validate_source_path(source) == source
    result = HANDLERS["build.run"]({"path": str(source), "genre": "rnb"}, workspace)
    assert Path(result["outDir"]).is_dir()


def test_a_read_only_source_folder_does_not_stop_a_build(workspace, tmp_path):
    """A project on a locked-down share must still be readable."""
    from tests.fixtures.flp_builder import build_flp

    folder = tmp_path / "locked"
    folder.mkdir()
    source = folder / "ReadOnly.flp"
    source.write_bytes(build_flp(full_kit()))
    folder.chmod(0o500)  # read + execute, no write
    try:
        result = HANDLERS["build.run"]({"path": str(source), "genre": "rnb"}, workspace)
        assert Path(result["outDir"]).is_dir()
        # And nothing was written into the read-only folder.
        assert sorted(p.name for p in folder.iterdir()) == ["ReadOnly.flp"]
    finally:
        folder.chmod(0o700)


def test_a_source_on_another_volume_than_the_export_root(workspace, tmp_path, make_flp):
    """Exports may be on D: while the project is on C:.

    os.replace is only atomic within a volume, which is why the temporary file
    is written beside the destination rather than in the cache.
    """
    source = make_flp(full_kit())
    result = HANDLERS["build.run"](
        {"path": str(source), "genre": "rnb", "exportRoot": str(tmp_path / "elsewhere")},
        workspace,
    )
    out_dir = Path(result["outDir"])
    assert out_dir.is_dir()
    assert "elsewhere" in out_dir.parts


def test_the_write_temporary_is_created_beside_its_destination(tmp_path):
    """Cross-volume renames are copies, and a copy can be interrupted."""
    seen: list[Path] = []
    real_replace = os.replace

    def watch(src, dst, *args, **kwargs):
        seen.append(Path(src))
        return real_replace(src, dst, *args, **kwargs)

    target = tmp_path / "deep" / "out.flp"
    import unittest.mock

    with unittest.mock.patch.object(os, "replace", watch):
        atomic_write(target, b"data")

    assert seen, "nothing was renamed"
    assert seen[0].parent == target.parent, "the temporary file was not beside the destination"


def test_long_path_declines_to_mangle_a_short_path(tmp_path):
    short = tmp_path / "a.flp"
    short.write_bytes(b"x")
    assert "?" not in str(long_path(short))


@pytest.mark.skipif(os.name != "nt", reason="MAX_PATH is a Windows limit")
def test_long_path_prefixes_a_path_over_the_threshold(tmp_path):
    deep = tmp_path / ("x" * 100) / ("y" * 100) / ("z" * 100)
    prefixed = str(long_path(deep))
    assert len(str(deep)) > LONG_PATH_THRESHOLD
    assert prefixed.startswith("\\\\?\\")


def test_a_unicode_name_survives_a_round_trip_through_the_library(workspace, tmp_path):
    from tests.fixtures.flp_builder import build_flp

    name = "Café 지금 🔥.flp"
    source = tmp_path / name
    try:
        source.write_bytes(build_flp(full_kit()))
    except (OSError, UnicodeEncodeError) as exc:
        pytest.skip(f"this filesystem cannot hold {name!r}: {exc}")

    HANDLERS["build.run"]({"path": str(source), "genre": "rnb"}, workspace)
    listed = HANDLERS["library.list"]({}, workspace)["projects"]
    assert [p["name"] for p in listed] == [source.stem]
    assert all(p["exists"] for p in listed)
