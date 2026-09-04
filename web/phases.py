"""What a build job is doing RIGHT NOW, named — the missing middle between the cylinder's
"Thinking…" and a 3000-line technical log.

The pipeline already narrates itself into the job log (`composition.decoupled` say-lines,
`verification.compile_repair` / `vision_critic` loop lines, and `web.devtrace`'s per-call
`[llm#n] <kind>` lines). Rather than threading a phase callback through a dozen modules — every
one of which would then have to know about the web layer — this reads that existing narration and
names the step. One module owns the vocabulary, and it is unit-tested against the literal strings
the pipeline emits.

`classify()` returns None for a line that says nothing about the phase; the caller keeps the
phase it had. That matters: most log lines are detail *within* a step.
"""
from __future__ import annotations

import re

# --- the vocabulary ---------------------------------------------------------------------------
QUEUED = "queued"
PLANNING = "planning"        # outline / storyboard
STYLE = "style"              # visual theme (StyleSpec)
SCENE_SPEC = "scene_spec"    # one scene's structured spec
CODEGEN = "codegen"          # writing (or repairing) the Manim file
RENDER = "render"            # sandboxed manim run
LINT = "lint"                # free deterministic geometry checks
VISION = "vision"            # paid visual critic
NARRATION = "narration"      # script + speech synthesis
MUX = "mux"                  # audio onto one scene's video
STITCH = "stitch"            # scenes -> final mp4
RETRYING = "retrying"        # a whole scene is being rebuilt after a failure
COMPLETE = "complete"
FAILED = "failed"
CANCELLED = "cancelled"

# user-facing wording (the technical name stays available for the dev console)
LABELS = {
    QUEUED: "Waiting to start",
    PLANNING: "Planning the storyboard",
    STYLE: "Choosing the visual theme",
    SCENE_SPEC: "Designing the scene",
    CODEGEN: "Writing the animation",
    RENDER: "Rendering",
    LINT: "Checking the layout",
    VISION: "Reviewing the frames",
    NARRATION: "Writing and voicing narration",
    MUX: "Adding the voice-over",
    STITCH: "Merging the scenes",
    RETRYING: "Retrying a scene",
    COMPLETE: "Done",
    FAILED: "Something went wrong",
    CANCELLED: "Stopped",
}

# --- log line -> phase ------------------------------------------------------------------------
# Ordered; first match wins. An `attempt` group of "i/n" is surfaced next to the phase so the UI can
# say "Rendering · attempt 2 of 4" instead of looking frozen while the same step repeats.
_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\[compile\] attempt (?P<attempt>\d+/\d+)"), RENDER),
    (re.compile(r"^\[compile\] deterministic fix"), CODEGEN),
    (re.compile(r"^\[compile\] gave up"), CODEGEN),
    (re.compile(r"^\[critic\] iter (?P<attempt>\d+/\d+): layout-lint"), LINT),
    (re.compile(r"^\[critic\] iter (?P<attempt>\d+/\d+)"), VISION),
    (re.compile(r"^\[critic\] iter (?P<attempt>\d+)"), VISION),
    (re.compile(r"^\[critic\]"), VISION),
    (re.compile(r"^\[walkthrough\]"), RENDER),
    # web.devtrace: "[llm#3] codegen · deepseek-chat · sys 8.1k · user 0.6k"
    (re.compile(r"^\[llm#\d+\] outline\b"), PLANNING),
    (re.compile(r"^\[llm#\d+\] (codegen|compile-fix|critic-fix)\b"), CODEGEN),
    (re.compile(r"^\[llm#\d+\] narration\b"), NARRATION),
    (re.compile(r"^\[llm#\d+\] spec\b"), SCENE_SPEC),
    # pipeline say-lines
    (re.compile(r"^->\s*(planning )?outline\b"), PLANNING),
    (re.compile(r"^->\s*using provided outline\b"), PLANNING),
    (re.compile(r"^->\s*planning code walkthrough\b"), PLANNING),
    (re.compile(r"^->\s*reading image\b"), PLANNING),
    (re.compile(r"^->\s*(theme|style)\b"), STYLE),
    (re.compile(r"^->\s*building \d+ scenes\b"), SCENE_SPEC),
    (re.compile(r"^->\s*narration script\b"), NARRATION),
    (re.compile(r"^->\s*using \d+ supplied narration\b"), NARRATION),
    (re.compile(r"^->\s*synthesi[sz]ing audio\b"), NARRATION),
    (re.compile(r"^->\s*narrated codegen\b"), CODEGEN),
    (re.compile(r"^->\s*rendering\b"), RENDER),
    (re.compile(r"^->\s*stitching\b"), STITCH),
    (re.compile(r"^->\s*muxing\b"), MUX),
]

# a per-scene status line from on_scene(): "retry 2/3: APIConnectionError"
_SCENE_RETRY = re.compile(r"^retry (?P<attempt>\d+/\d+)")


def classify(message: str) -> tuple[str, str | None] | None:
    """(phase, attempt) for a job log line, or None if the line doesn't name a phase."""
    m = (message or "").strip()
    for pattern, phase in _RULES:
        hit = pattern.search(m)
        if hit:
            attempt = hit.groupdict().get("attempt") if hit.groupdict() else None
            return (phase, attempt)
    return None


def classify_scene_status(status: str) -> tuple[str, str | None] | None:
    """Same, for a per-scene status pushed through `on_scene` (retry / cancelled / deadline)."""
    s = (status or "").strip()
    hit = _SCENE_RETRY.match(s)
    if hit:
        return (RETRYING, hit.group("attempt"))
    if s.startswith("cancelled"):
        return (CANCELLED, None)
    if s.startswith("deadline"):
        return (FAILED, None)
    return None


def label(phase: str) -> str:
    return LABELS.get(phase, phase.replace("_", " ").capitalize())
