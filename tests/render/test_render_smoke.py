"""Render tier: needs FL Studio and FLPF_RENDER=1. Never runs in CI.

The render pipeline itself is Phase 2 work. This file exists now so the tier is
wired up and its gating is proven, rather than being invented later.
"""

import pytest

from prosody_core import env as environment

pytestmark = pytest.mark.render


def test_fl_studio_is_discoverable_when_rendering_is_enabled():
    info = environment.describe()
    assert info.fl_executable is not None, (
        f"FLPF_RENDER=1 but FL Studio was not found: {info.fl_discovery}"
    )
    assert info.fl_executable.is_file()


def test_midi_export_switch_has_been_confirmed():
    """Fails until someone records the real switch letter from the FL manual.

    EXECUTE.md T3 requires this. Leaving it as a failing render-tier test is
    honest; hardcoding a guessed switch would not be.
    """
    assert environment.FL_SWITCHES["midi_export"] is not None, (
        "the FL MIDI-export switch is still unconfirmed; see docs/render-pipeline.md"
    )
