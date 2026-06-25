"""Manim API guardrails (FR-8) — catch CE/GL mixing and deprecated calls BEFORE rendering.

Cheap, deterministic, free: a regex pass over generated code. Violations are fed back to the
generator (see codegen.py) so it self-corrects before we ever pay to render.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Issue:
    rule: str
    message: str


# Patterns that must NOT appear (CE/GL mixing, deprecated API).
_FORBIDDEN: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\b(from|import)\s+manimlib\b"), "no-manimgl",
     "imports manimlib (ManimGL) — use `from manim import *` (Manim CE)"),
    (re.compile(r"--?renderer[=\s]+opengl", re.I), "no-opengl",
     "selects the OpenGL renderer — CE/Cairo only"),
    (re.compile(r"\bOpenGL\b"), "no-opengl",
     "references OpenGL — not allowed (CE/Cairo only)"),
    (re.compile(r"\bShowCreation\b"), "deprecated",
     "ShowCreation is deprecated — use Create"),
    (re.compile(r"\bTextMobject\b"), "deprecated",
     "TextMobject is deprecated — use Text (or Tex)"),
    (re.compile(r"\bTexMobject\b"), "deprecated",
     "TexMobject is deprecated — use MathTex"),
    (re.compile(r"\.get_graph\b"), "deprecated",
     "get_graph is deprecated — use axes.plot"),
]

# Patterns that MUST appear (a renderable CE scene).
_REQUIRED: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\b(from\s+manim\s+import|import\s+manim)\b"), "import-manim",
     "must import Manim CE (`from manim import *`)"),
    (re.compile(r"class\s+GeneratedScene\s*\(\s*\w*Scene\w*\s*\)"), "scene-class",
     "must define `class GeneratedScene(Scene)`"),
    (re.compile(r"def\s+construct\s*\(\s*self"), "construct",
     "Scene must implement `construct(self)`"),
]


# Structural mode (FR-32): the scene MUST use the LatticeScene scaffold, not free-hand Scene.
_STRUCTURAL_BASE = re.compile(r"class\s+GeneratedScene\s*\(\s*LatticeScene\s*\)")
_STRUCTURAL_SETUP = re.compile(r"self\.setup_scene\s*\(")


def check(code: str, *, structural: bool = False) -> list[Issue]:
    issues: list[Issue] = []
    for pat, rule, msg in _FORBIDDEN:
        if pat.search(code):
            issues.append(Issue(rule, msg))
    for pat, rule, msg in _REQUIRED:
        if not pat.search(code):
            issues.append(Issue(rule, msg))
    if structural:
        # ENFORCE the scaffold so the model can't ignore it and free-hand the layout.
        if not _STRUCTURAL_BASE.search(code):
            issues.append(Issue("structural-base",
                "must subclass LatticeScene: `class GeneratedScene(LatticeScene):` (do NOT subclass Scene directly)"))
        if not _STRUCTURAL_SETUP.search(code):
            issues.append(Issue("structural-setup",
                "construct must begin with `self.setup_scene(<title>)` — it renders the mandatory title + builds the grid"))
    return issues
