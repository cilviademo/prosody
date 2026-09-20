"""Architectural boundaries, asserted rather than documented.

ARCHITECTURE.md states import rules and docs/privacy.md states that nothing
leaves the machine. Both are checkable, so they are checked.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent.parent / "flpfinisher"

#: Modules that may import a parser library (ADR-0001). `write/` joins this list
#: when it exists.
PARSER_ALLOWED = {"parse"}

NETWORK_MODULES = {
    "requests", "httpx", "urllib", "urllib3", "http", "socket", "ftplib",
    "smtplib", "telnetlib", "aiohttp", "anthropic", "openai",
}


def python_files() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_there_are_python_files_to_check():
    assert python_files()


@pytest.mark.parametrize("path", python_files(), ids=lambda p: p.name)
def test_pyflp_is_imported_only_inside_the_parse_package(path: Path):
    """ADR-0001: no other layer may see PyFLP."""
    if "pyflp" not in imported_roots(path):
        return
    package = path.relative_to(PACKAGE).parts[0]
    assert package in PARSER_ALLOWED, (
        f"{path.relative_to(PACKAGE)} imports pyflp; only {PARSER_ALLOWED} may"
    )


@pytest.mark.parametrize("path", python_files(), ids=lambda p: p.name)
def test_no_network_capability_anywhere_in_the_package(path: Path):
    """docs/privacy.md: nothing leaves this computer. Verified, not promised."""
    offending = imported_roots(path) & NETWORK_MODULES
    assert not offending, f"{path.relative_to(PACKAGE)} imports {offending}"


@pytest.mark.parametrize("path", python_files(), ids=lambda p: p.name)
def test_the_package_never_calls_print(path: Path):
    """CLAUDE.md: rich console + run.log, no print()."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]
    assert not calls, f"{path.relative_to(PACKAGE)} calls print()"


def test_the_domain_model_depends_on_nothing_but_pydantic_and_the_stdlib():
    """ARCHITECTURE.md: no third-party object may appear in a field type."""
    allowed = {"pydantic", "flpfinisher", "__future__", "typing", "enum",
               "datetime", "collections", "abc", "re", "functools", "pathlib"}
    for path in (PACKAGE / "model").rglob("*.py"):
        extra = imported_roots(path) - allowed
        assert not extra, f"model/{path.name} imports {extra}"


def test_genre_behaviour_lives_in_json_not_in_code():
    """SPEC.md section 6: genre is data. The loader must stay trivial."""
    loader = (PACKAGE / "arrange" / "profiles" / "__init__.py").read_text()
    assert len(loader.splitlines()) < 60
    assert list((PACKAGE / "arrange" / "profiles").glob("*.json"))


def test_no_secret_looking_literals_are_committed():
    pattern = re.compile(r"(sk-ant-|sk-proj-|AKIA[0-9A-Z]{16})")
    for path in python_files():
        assert not pattern.search(path.read_text(encoding="utf-8")), path


# -- product naming --------------------------------------------------------- #

REPO = PACKAGE.parent


def test_the_package_never_says_asterism():
    """The product is Prosody. A stray old name in a path or a filename would
    reach the user's disk, not just the screen."""
    for path in python_files():
        assert "asterism" not in path.read_text(encoding="utf-8").lower(), path


def test_the_desktop_app_never_says_asterism():
    ui = REPO / "apps" / "desktop" / "src"
    if not ui.is_dir():
        return
    for path in [*ui.rglob("*.tsx"), *ui.rglob("*.ts"), *ui.rglob("*.css")]:
        assert "asterism" not in path.read_text(encoding="utf-8").lower(), path


def test_generated_names_carry_the_product_tag():
    from flpfinisher.build import APP_TAG, output_stem

    assert APP_TAG == "PROSODY"
    assert output_stem(Path("Starfall.flp"), "rnb", 1) == "Starfall__PROSODY_RNB_V001"


def test_the_workspace_is_named_for_the_product():
    from flpfinisher.workspace import APP_NAME, default_root

    assert APP_NAME == "Prosody"
    assert default_root().name == "Prosody"


def test_the_interface_is_literally_monochrome():
    """Every colour in the UI must be a true neutral (R == G == B).

    A few points of blue in the channel is imperceptible as colour but it is
    what makes a dark interface read as "dark blue" rather than black, which
    is the thing this design system exists to avoid. Enforcing R==G==B means
    no screen can reintroduce a cast by eye.
    """
    ui = REPO / "apps" / "desktop" / "src"
    if not ui.is_dir():
        return

    offenders: list[str] = []
    for path in [*ui.rglob("*.css"), *ui.rglob("*.tsx")]:
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"#([0-9A-Fa-f]{6})\b", text):
            r, g, b = (int(match.group(1)[i:i + 2], 16) for i in (0, 2, 4))
            if not r == g == b:
                offenders.append(f"{path.name}: #{match.group(1)}")
        for match in re.finditer(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", text):
            r, g, b = (int(match.group(i)) for i in (1, 2, 3))
            if not r == g == b:
                offenders.append(f"{path.name}: rgb({r},{g},{b})")

    assert not offenders, f"non-neutral colours: {sorted(set(offenders))}"
