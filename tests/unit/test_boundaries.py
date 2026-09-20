"""Architectural boundaries, asserted rather than documented.

ARCHITECTURE.md states import rules and docs/privacy.md states that nothing
leaves the machine. Both are checkable, so they are checked.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent.parent / "prosody_core"

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
    allowed = {"pydantic", "prosody_core", "__future__", "typing", "enum",
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
    from prosody_core.build import APP_TAG, output_stem

    assert APP_TAG == "PROSODY"
    assert output_stem(Path("Starfall.flp"), "rnb", 1) == "Starfall__PROSODY_RNB_V001"


def test_the_workspace_is_named_for_the_product(monkeypatch):
    from prosody_core.workspace import (
        APP_NAME,
        DB_FILE,
        default_root,
        default_state,
    )

    # The autouse isolation fixture overrides both roots; unset to see defaults.
    monkeypatch.delenv("PROSODY_HOME", raising=False)
    monkeypatch.delenv("PROSODY_STATE", raising=False)

    assert APP_NAME == "Prosody"
    assert DB_FILE == "prosody.db"
    assert default_root().name == "Prosody"
    assert default_state().name == "Prosody"
    # User output and machine-local state must not share a folder.
    assert default_root() != default_state()


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


# -- packaging -------------------------------------------------------------- #

#: Modules that ship with CPython, so they need no declaration.
_STDLIB = set(sys.stdlib_module_names) | {"prosody_core", "tests"}


def _declared_dependencies() -> set[str]:
    """Distribution names in pyproject's required dependencies."""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    block = text.split("dependencies = [", 1)[1].split("]", 1)[0]
    names = set()
    for line in block.splitlines():
        entry = line.strip().strip('",').split("#", 1)[0].strip().strip('"')
        if entry:
            names.add(re.split(r"[<>=!~\[]", entry)[0].strip().lower())
    return names


def test_every_imported_package_is_a_required_dependency():
    """A module imported at runtime but declared as an optional extra is a
    broken install: it works in the developer's venv and fails on a clean one.

    Caught exactly once already — `mido` is imported by every build and was
    sitting in an optional extra, so CI's fresh environment had no MIDI export.
    """
    declared = _declared_dependencies()
    #: import name -> distribution name, where they differ.
    aliases = {"pydantic_core": "pydantic"}

    missing: set[str] = set()
    for path in python_files():
        for root in imported_roots(path):
            if root in _STDLIB or root.startswith("_"):
                continue
            name = aliases.get(root, root).replace("_", "-").lower()
            if name not in declared:
                missing.add(f"{root} (imported by {path.name})")

    assert not missing, (
        f"imported but not a required dependency: {sorted(missing)}. "
        "Move it into [project] dependencies, or stop importing it."
    )


def test_pinned_requirements_cover_the_required_dependencies():
    """requirements.txt is what CI and the PyInstaller build install."""
    pinned = {
        re.split(r"[<>=!~]", line.split("#")[0].strip())[0].strip().lower()
        for line in (REPO / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    missing = _declared_dependencies() - pinned
    assert not missing, f"not pinned in requirements.txt: {sorted(missing)}"


# --- the documented install path ------------------------------------------
# README.md tells a user to pipe a URL into PowerShell. If that URL is wrong
# the first thing anyone does with this project fails, and nothing else in the
# suite would notice.

INSTALL_URL = re.compile(
    r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(\S+?\.ps1)"
)


def test_the_one_line_installer_points_at_a_script_that_exists():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    matches = INSTALL_URL.findall(readme)
    assert matches, "README.md no longer documents a one-line installer"
    for _owner, _repo, ref, path in matches:
        assert (REPO / path).is_file(), f"{path} is advertised in README.md but not in the tree"
        # The URL is only fetchable if that branch is one we actually publish.
        assert ref == "main", f"the installer URL points at '{ref}', which is not the published branch"


def test_the_installer_downloads_from_the_repository_it_ships_in():
    """A forked or renamed repo with a stale URL would install someone else's build."""
    script = (REPO / "scripts" / "install.ps1").read_text(encoding="utf-8")
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    declared = re.search(r'^\$Repo\s*=\s*"([^"]+)"', script, re.MULTILINE)
    assert declared, "install.ps1 no longer declares which repository it installs from"
    owner, repo, _ref, _path = INSTALL_URL.findall(readme)[0]
    assert declared.group(1) == f"{owner}/{repo}"


def test_the_installer_never_weakens_tls_or_certificate_checking():
    """It runs as a pipe into iex on someone else's machine; it must not opt out."""
    script = (REPO / "scripts" / "install.ps1").read_text(encoding="utf-8")
    for forbidden in (
        "ServerCertificateValidationCallback",
        "-SkipCertificateCheck",
        "Ssl3",
        "Tls11",
    ):
        assert forbidden not in script, f"install.ps1 weakens transport security: {forbidden}"
    assert "Tls12" in script, "install.ps1 must force TLS 1.2 for Windows PowerShell 5.1"


def test_the_release_workflow_builds_from_the_published_branch():
    """README promises main always has a download; the trigger must back that up."""
    workflow = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert re.search(r'branches:\s*\["?main"?\]', workflow), (
        "release.yml does not build on a push to main, so the one-line "
        "installer can point at a branch with no release behind it"
    )
