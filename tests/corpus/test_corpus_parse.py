"""Corpus tier: real .flp files. Skipped automatically when corpus/ is empty.

These encode the Phase 0 / Phase 1 exit criteria from SPEC.md section 9 so that
running them on the studio PC answers the parse-rate question directly.
"""

import pytest

from prosody_core.fs.safety import sha256_file
from prosody_core.parse.adapter import ParseError
from prosody_core.parse.pyflp_backend import PyFLPBackend
from prosody_core.pipeline import scan_directory

pytestmark = pytest.mark.corpus

PARSE_RATE_TARGET = 0.80


def test_parse_rate_meets_the_target(corpus_flps, tmp_path):
    root = corpus_flps[0].parent.parent if corpus_flps else None
    rows = scan_directory(root, out_root=tmp_path / "out")
    parsed = sum(1 for r in rows if r.ok)
    rate = parsed / len(rows)
    failures = "\n".join(f"  {r.path.name}: {r.error}" for r in rows if not r.ok)
    assert rate >= PARSE_RATE_TARGET, (
        f"parse rate {parsed}/{len(rows)} ({rate:.0%}) below "
        f"{PARSE_RATE_TARGET:.0%}\n{failures}"
    )


def test_no_corpus_file_is_modified_by_a_full_scan(corpus_flps, tmp_path):
    before = {p: sha256_file(p) for p in corpus_flps}
    scan_directory(corpus_flps[0].parent, out_root=tmp_path / "out",
                   write_artifacts_per_project=True)
    assert {p: sha256_file(p) for p in before} == before


def test_every_parsed_project_reports_an_fl_version(corpus_flps):
    backend = PyFLPBackend()
    missing = []
    for path in corpus_flps:
        try:
            project = backend.parse(path)
        except ParseError:
            continue
        if not project.fl_version:
            missing.append(path.name)
    assert not missing, f"no FL version recorded for: {missing}"
