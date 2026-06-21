"""M0 unit tests — the hard gate. No Docker, no network, no model calls.

These assert the substrate: the Manim version is pinned, the sandbox command is actually
sandboxed (--network=none), quality flags map correctly, the sample scene exercises both
a shape and LaTeX, and the LLM client constructs without reaching out.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.unit
def test_manim_version_pinned():
    from core.config import settings
    assert settings.manim_version == "0.18.1"
    assert "v0.18.1" in settings.manim_base_image


@pytest.mark.unit
def test_render_defaults_to_no_network():
    from core.config import settings
    assert settings.render_network is False


@pytest.mark.unit
def test_quality_flags_map():
    from core.config import settings
    assert settings.quality_flag("preview") == "-ql"
    assert settings.quality_flag("final") == "-qh"
    assert settings.quality_flag("anything-else") == "-ql"  # default is preview


@pytest.mark.unit
def test_sandbox_command_is_sandboxed():
    from render.sandbox import build_command
    cmd = build_command(ROOT / "out", "scene.py", "SampleScene", quality="preview")
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert "--network=none" in cmd          # the sandbox invariant
    assert "manim" in cmd and "-ql" in cmd
    assert "scene.py" in cmd and "SampleScene" in cmd


@pytest.mark.unit
def test_sandbox_final_uses_high_quality():
    from render.sandbox import build_command
    cmd = build_command(ROOT / "out", "scene.py", "SampleScene", quality="final")
    assert "-qh" in cmd


@pytest.mark.unit
def test_sandbox_still_flag_present_for_keyframe():
    from render.sandbox import build_command
    cmd = build_command(ROOT / "out", "scene.py", "SampleScene", still=True)
    assert "-s" in cmd


@pytest.mark.unit
def test_network_can_be_enabled_explicitly():
    from render.sandbox import build_command
    cmd = build_command(ROOT / "out", "scene.py", "SampleScene", network=True)
    assert "--network=none" not in cmd      # opt-in only


@pytest.mark.unit
def test_sample_scene_has_shape_and_mathtex():
    src = (ROOT / "render" / "sample_scene.py").read_text(encoding="utf-8")
    assert "MathTex" in src                  # proves the LaTeX path is exercised
    assert ("Square" in src or "Circle" in src)  # proves a shape animation


@pytest.mark.unit
def test_llm_client_constructs_without_calling():
    from core.llm import LLMClient
    c = LLMClient(model="vendor/model")
    assert c.model == "vendor/model"
    assert c._client is None                 # no client/network created at construct time
