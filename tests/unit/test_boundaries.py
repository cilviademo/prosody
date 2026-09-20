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
