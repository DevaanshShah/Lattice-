"""Decoupled narrated-video pipeline — the RELIABLE path.

Instead of asking the LLM to write `add_sound`-synced narrated code (fragile: the cheap model
botches the sync ~half the time), we DECOUPLE:

    silent codegen (reliable) -> render -> gTTS narration -> ffmpeg-mux the audio on top.

No LLM ever touches the audio wiring, so it can't break it. Each scene is independent and retried
on failure (AiCredits 500-streaks can't kill the whole video), then the scenes are stitched.

This is the path that produced 4/4 narrated scenes where the M5 `narrate.build` path got 0-1/4.
ffmpeg/ffprobe run INSIDE the render image (no host ffmpeg), via `composition.stitch._docker_prefix`.
"""
from __future__ import annotations

import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.config import settings
from core.llm import LLMClient, get_client, get_critic_client
from core.schemas.outline import Outline, OutlineItem
from core.schemas.scene_spec import SCENE_CLASS, SceneSpec
from core.textutil import strip_code_fences
from generation import guardrails, lattice_scene
from generation.components import COMPONENTS_PROMPT, COMPONENTS_SRC
from narration import tts
from planner import expand as planner_expand
from planner import outline as planner_outline
from prompts.loader import load
from verification import compile_repair, vision_critic
from verification.vision_critic import CritiqueReport, critique
from composition import stitch
from composition.stitch import _docker_prefix


# --- ffmpeg helpers (run in the render image) -----------------------------------------------
def _probe_duration(work_dir: str | Path, rel: str, *, timeout: int = 120) -> float:
    """Seconds of `rel` (relative to work_dir) via ffprobe in the render image. 0.0 on failure."""
    cmd = _docker_prefix(work_dir, network=False, image=None) + [
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", rel]
    p = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    try:
        return float((p.stdout or "0").strip())
    except ValueError:
        return 0.0


def mux_audio(work_dir: str | Path, video_rel: str, audio_rel: str, out_rel: str) -> bool:
    """Mux an audio track onto a silent video, padding the shorter stream so both reach the same
    length (video freezes its last frame; audio gets trailing silence). Returns True on success.

    Scene-level sync: the narration plays over the whole scene. The complete diagram staying on
    screen while the voice finishes is fine for an explainer — and it never breaks like add_sound.
    """
    vd = _probe_duration(work_dir, video_rel)
    ad = _probe_duration(work_dir, audio_rel)
    target = max(vd, ad) + 0.3
    pad_v = max(0.0, target - vd)
    cmd = _docker_prefix(work_dir, network=False, image=None) + [
        "ffmpeg", "-loglevel", "error", "-y", "-i", video_rel, "-i", audio_rel,
        "-filter_complex", f"[0:v]tpad=stop_mode=clone:stop_duration={pad_v:.2f}[v];[1:a]apad[a]",
        "-map", "[v]", "-map", "[a]", "-t", f"{target:.2f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", out_rel]
    p = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                       timeout=settings.render_timeout_s)
    return p.returncode == 0


# --- codegen / narration ---------------------------------------------------------------------
def _finalize_code(code: str, *, structural: bool, use_components: bool) -> str:
    """Prepend the base source the generated scene relies on: the LatticeScene grid (structural mode)
    or the component helpers (freehand + components). Freehand-without-components returns code as-is."""
    if structural:
        return lattice_scene.LATTICE_SCENE_SRC + "\n\n" + code
    return (COMPONENTS_SRC + "\n\n" + code) if use_components else code


def _silent_codegen(spec: SceneSpec, *, client: LLMClient, style=None, use_components: bool = True,
                    structural: bool = False, attempts: int = 3) -> str:
    """Generate a SILENT scene. structural=True targets the LatticeScene grid scaffold (mandates
    Table/built-ins, named-grid placement); otherwise the freehand codegen prompt (+ optional components)."""
    conventions = load("manim-conventions")
    if structural:
        system = conventions + "\n\n---\n\n" + load("lattice-codegen")
    else:
        system = conventions + "\n\n---\n\n" + load("codegen")
        if use_components:
            system += "\n\n---\n\n" + COMPONENTS_PROMPT
    if style is not None:
        system += "\n\n---\n\n" + style.as_prompt()
    user = ("Scene spec (JSON):\n" + spec.model_dump_json(indent=2)
            + f"\n\nGenerate the complete Manim CE file. The Scene subclass MUST be named `{SCENE_CLASS}`.")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    raw = ""
    for _ in range(attempts):
        raw = client.chat(messages)
        code = strip_code_fences(raw)
        if not guardrails.check(code, structural=structural):
            return _finalize_code(code, structural=structural, use_components=use_components)
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "Fix these and resend the FULL file (code only)."}]
    code = strip_code_fences(raw)
    return _finalize_code(code, structural=structural, use_components=use_components)


_BG_COLOR = "#101015"


def _enforce_background(code: str, color: str = _BG_COLOR) -> str:
    """Deterministically pin a consistent background: strip any model-set background_color line and
    inject ours as the first statement of construct(). Kills the navy/black inconsistency for free,
    without relying on the model to set it the same way every scene."""
    code = re.sub(r"\n[ \t]*self\.camera\.background_color[ \t]*=.*", "", code)
    return re.sub(r"(\n[ \t]*def construct\(self\):\n)",
                  rf'\1        self.camera.background_color = "{color}"\n', code, count=1)


def _make_issue_fixer(spec, style, use_components, client, *, structural: bool = False):
    """Custom critic fixer: rewrites the scene to fix the vision critic's issues, then RE-APPLIES the
    base source the scene depends on (LatticeScene grid in structural mode, else component helpers) so a
    critic regen doesn't drop it. Freehand also re-pins the background; structural leaves it to setup_scene."""
    conventions = load("manim-conventions")
    if structural:
        system = conventions + "\n\n---\n\n" + load("lattice-codegen")
        base_src = lattice_scene.LATTICE_SCENE_SRC
    else:
        system = conventions + "\n\n---\n\n" + load("codegen")
        if use_components:
            system += "\n\n---\n\n" + COMPONENTS_PROMPT
        base_src = COMPONENTS_SRC if use_components else None
    if style is not None:
        system += "\n\n---\n\n" + style.as_prompt()
    intent = f"\n\nScene spec (keep the intent):\n{spec.model_dump_json(indent=2)}" if spec else ""

    def fix(code: str, report: CritiqueReport) -> str:
        scene = code.split(base_src, 1)[-1] if base_src else code  # show just the scene
        issues = "\n".join(f"- [{i.type}] {i.location}: {i.description} -> FIX: {i.suggested_fix}"
                           for i in report.issues) or "- (no specific issues listed)"
        user = (f"The rendered scene has these visual defects found by a vision critic:\n{issues}\n\n"
                f"CURRENT CODE:\n{scene}{intent}\n\n"
                "Apply the fixes (adjust positions/sizes so nothing overlaps or runs off-frame) and "
                "resend the full corrected file (code only).")
        fixed = strip_code_fences(client.chat([{"role": "system", "content": system},
                                               {"role": "user", "content": user}]))
        out = (base_src + "\n\n" + fixed) if base_src else fixed
        return out if structural else _enforce_background(out)

    return fix


def _make_compile_fixer(spec, style, use_components, client, *, structural: bool = False):
    """Custom compile-repair fixer: on a COMPILE FAILURE, regenerate using the SAME structural/freehand
    system prompt as the original codegen, then RE-APPLY the base source (LatticeScene / components).

    Without this, `compile_repair`'s default fixer uses a generic prompt with no scaffold awareness and
    never re-prepends the base source -- so a compile failure mid-run SILENTLY DROPS structural mode for
    the rest of that scene (confirmed: a scene reverted to a plain freehand `Scene` subclass, losing
    every geometry primitive, after hitting exactly one compile error). Mirrors `_make_issue_fixer`,
    just matching compile_repair.RegenFn's (code, error) -> str shape instead of (code, report) -> str.
    """
    conventions = load("manim-conventions")
    if structural:
        system = conventions + "\n\n---\n\n" + load("lattice-codegen")
        base_src = lattice_scene.LATTICE_SCENE_SRC
    else:
        system = conventions + "\n\n---\n\n" + load("codegen")
        if use_components:
            system += "\n\n---\n\n" + COMPONENTS_PROMPT
        base_src = COMPONENTS_SRC if use_components else None
    if style is not None:
        system += "\n\n---\n\n" + style.as_prompt()
    intent = f"\n\nScene intent (keep it, do not change it):\n{spec.model_dump_json(indent=2)}" if spec else ""

    def fix(code: str, error: str) -> str:
        scene = code.split(base_src, 1)[-1] if base_src else code  # show just the scene, not the base
        user = (f"TRIMMED TRACEBACK:\n{error}\n\nCURRENT CODE:\n{scene}{intent}\n\n"
                "Resend the full corrected file (code only).")
        fixed = strip_code_fences(client.chat([{"role": "system", "content": system},
                                               {"role": "user", "content": user}]))
        out = (base_src + "\n\n" + fixed) if base_src else fixed
        return out if structural else _enforce_background(out)

    return fix


def _critic_intent(spec: SceneSpec | None) -> str:
    if spec is None:
        return ""
    return f"Prompt: {spec.prompt}\nTitle: {spec.title}\nNarration: {spec.narration}"


# Measured gTTS pace ~2.2 words/sec. We turn the animation's real duration into a firm word CEILING so
# narration doesn't outrun the visuals and play over a frozen final frame (measured: an unguided script
# ran 25.5s over an 11.9s animation; a first soft-budget attempt still overshot 2x because a competing
# "2-4 sentences" rule won -- so the budget is now the single authoritative length instruction).
_WORDS_PER_SECOND = 2.3
_MIN_NARRATION_WORDS = 20  # floor: even a very short scene gets a coherent sentence, not a fragment


def _scene_narration(item: OutlineItem, outline: Outline, index: int, code: str, *,
                     client: LLMClient, target_seconds: float | None = None) -> str:
    """Spoken narration grounded in the ACTUAL generated code — no hallucination of things not on screen.
    target_seconds (the MEASURED silent-animation duration, if known) becomes a soft word-count budget
    so narration doesn't run 2x+ longer than the visuals and sit over a static frozen frame."""
    total = len(outline.items)
    is_first = index == 0
    is_last = index == total - 1
    prev_scene = outline.items[index - 1] if not is_first else None
    next_scene = outline.items[index + 1] if not is_last else None

    position = "opening scene" if is_first else ("closing scene" if is_last else f"scene {index + 1} of {total}")
    arc_lines = []
    if prev_scene:
        arc_lines.append(f"Previous scene covered: {prev_scene.title}")
    if next_scene:
        arc_lines.append(f"Next scene will cover: {next_scene.title}")
    arc_block = ("\n" + "\n".join(arc_lines)) if arc_lines else ""

    # Show the model the ACTUAL scene, not the LatticeScene scaffold boilerplate that (in structural
    # mode) precedes GeneratedScene — else it narrates the grid ("coordinates A-E, columns 1-8")
    # instead of the real content. Start at GeneratedScene; freehand has no base so this is a no-op.
    body = code[code.index("class GeneratedScene"):] if "class GeneratedScene" in code else code
    code_preview = "\n".join(body.splitlines()[:80])

    if target_seconds and target_seconds > 0:
        target_words = max(_MIN_NARRATION_WORDS, round(target_seconds * _WORDS_PER_SECOND))
        length_rule = (
            f"- LENGTH / PACING (this governs the whole reply): the animation is only about "
            f"{target_seconds:.0f}s long, so write AT MOST about {target_words} words. This is a firm "
            f"CEILING, not a target to fill — going over means the voice keeps talking over a frozen "
            f"final frame, which looks dead. Cut every filler phrase ('one of the most famous', "
            f"'timeless', \"let's explore\", 'in this scene'); say only the single most important idea "
            f"about what is on screen. Fewer words is better than more."
        )
    else:
        length_rule = "- LENGTH: 2-3 tight sentences; cut filler, say only what matters."

    system = (
        "You write spoken narration for an educational animation — like a confident, engaging teacher "
        "talking over a visual that the viewer is watching RIGHT NOW.\n\n"
        "CRITICAL RULE: Only describe what the viewer will SEE — the specific shapes, labels, words, "
        "and numbers that appear as objects in the code below. Do NOT invent examples, numbers, or "
        "visuals that are not in the code. Do NOT narrate a step or count unless it is drawn on screen. "
        "If the code shows 'pizza', you may mention pizza; if it does not, you may not.\n\n"
        "Style rules:\n"
        "- Speak directly to the viewer ('you', 'we') as if live over the animation.\n"
        "- Teach the concept — don't just read out object names.\n"
        "- Build a natural bridge from the previous scene (if any) in one sentence — no 'Previously...' clichés.\n"
        "- End with a forward pull toward the next scene (if any).\n"
        "- Plain text only — no bullets, no markdown.\n"
        f"{length_rule}"
    )
    user = (
        f"Video topic: {outline.topic}\n"
        f"This is the {position} (total: {total} scenes).{arc_block}\n\n"
        f"Scene title: {item.title}\n\n"
        f"Animation code (what is actually on screen):\n```python\n{code_preview}\n```\n\n"
        "Write the spoken narration for this scene. Only reference visuals that exist in the code above."
    )
    return client.chat([{"role": "system", "content": system},
                        {"role": "user", "content": user}], max_tokens=400).strip()


# --- one scene, end to end -------------------------------------------------------------------
def build_scene(item: OutlineItem, outline: Outline, index: int, *, work_dir: str | Path,
                client: LLMClient, style=None, use_components: bool = True,
                use_critic: bool = True, structural: bool = False, quality: str = "preview",
                spec: SceneSpec | None = None, base_code: str | None = None,
                narration_override: list[str] | None = None) -> Path:
    """expand -> silent codegen -> render (+optional vision critic) -> gTTS -> mux. Returns the
    narrated scene mp4. Raises on any failure so the caller's retry can re-attempt the whole scene.

    structural: generate against the LatticeScene grid scaffold (named-grid placement + Table/built-in
    mandates) instead of freehand coordinates — the industry-proven fix for blind spatial placement.
    use_critic: run the gpt-mini vision critic (sees the frames, fixes garbled labels / off-screen /
    overlap that components + bg-injection can't catch). Adds a re-render or two; off = faster.
    base_code: render THIS exact code instead of generating fresh (used by narration edits to re-render
    identical visuals with new words — pass with use_critic=False so the critic can't alter the visuals).
    narration_override: use these lines verbatim as the narration instead of generating it (narration edit).
    """
    wd = Path(work_dir)
    wd.mkdir(parents=True, exist_ok=True)
    if spec is None:
        spec = planner_expand.expand(item, outline, index, client=client)
    (wd / "spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")  # for edit ops later
    if base_code is not None:
        code = base_code  # re-render the exact existing visuals (narration edit) — no fresh codegen
    else:
        code = _silent_codegen(spec, client=client, style=style, use_components=use_components,
                               structural=structural)
    if not structural:
        code = _enforce_background(code)  # freehand: pin a consistent bg (structural sets it in setup_scene)
    compile_fixer = _make_compile_fixer(spec, style, use_components, client, structural=structural)
    if use_critic:
        cr = vision_critic.run(
            code, wd, spec, quality=quality, client=client, vision_confirm=True,
            compile_regen_fn=compile_fixer,
            issue_regen_fn=_make_issue_fixer(spec, style, use_components, client, structural=structural),
            critic_fn=lambda fr: critique(fr, intent=_critic_intent(spec), client=get_critic_client()),
            log=lambda _m: None)
        ok, mp4 = cr.compiled, cr.mp4
    else:
        rep = compile_repair.repair(code, wd, quality=quality, spec=spec, client=client,
                                    regen_fn=compile_fixer, log=lambda _m: None)
        ok, mp4 = rep.ok, rep.mp4
    if not ok or not mp4:
        raise RuntimeError(f"render failed for scene {index}")
    video_rel = Path(mp4).resolve().relative_to(wd.resolve()).as_posix()
    if narration_override is not None:
        narration_text = "\n".join(s for s in narration_override if s and s.strip()).strip()
    else:
        video_duration = _probe_duration(wd, video_rel)  # measured, real -- used to pace narration length
        narration_text = _scene_narration(item, outline, index, code, client=client,
                                          target_seconds=video_duration)
    (wd / "narration.txt").write_text(narration_text, encoding="utf-8")
    clip = tts.synthesize(narration_text, out_dir=wd)
    audio_rel = Path(clip.path).resolve().relative_to(wd.resolve()).as_posix()
    if not mux_audio(wd, video_rel, audio_rel, "narrated.mp4"):
        raise RuntimeError(f"audio mux failed for scene {index}")
    return wd / "narrated.mp4"


def _build_with_retry(item, outline, index, *, scenes_dir, client, style, use_components,
                      use_critic, structural, quality, retries, on_scene) -> tuple[int, Path | None]:
    for attempt in range(retries):
        try:
            mp4 = build_scene(item, outline, index, work_dir=Path(scenes_dir) / f"scene_{index}",
                              client=client, style=style, use_components=use_components,
                              use_critic=use_critic, structural=structural, quality=quality)
            if on_scene:
                on_scene(index, "done")
            return (index, mp4)
        except Exception as e:  # noqa: BLE001 — retry the whole scene (covers 500-streaks)
            if on_scene:
                on_scene(index, f"retry {attempt + 1}/{retries}: {type(e).__name__}")
            time.sleep(10)
    if on_scene:
        on_scene(index, "failed")
    return (index, None)


# --- whole video -----------------------------------------------------------------------------
def build_video(prompt: str, *, client: LLMClient | None = None, max_scenes: int = 8,
                workers: int = 3, retries: int = 3, use_components: bool = True,
                use_critic: bool = True, structural: bool | None = None, quality: str = "preview",
                outline: Outline | None = None,
                out_dir: str | Path | None = None, out_name: str = "final.mp4",
                approve_fn=None, on_scene=None, log=print) -> Path | None:
    """Prompt -> outline -> parallel decoupled scenes (with per-scene retry) -> stitch.
    Returns the final stitched mp4 (or None if no scene survived). `on_scene(index, status)` fires
    per scene; `approve_fn(outline)->outline` is the optional approval gate before any render.
    structural: use the LatticeScene grid scaffold. FINALIZED default for the video path = True
    (renders cleaner than freehand); pass structural=False to A/B the old freehand path.
    outline: pass an ALREADY-APPROVED outline (e.g. from the web outline-gate) to skip generation +
    the approve_fn; the scenes are built in the outline's order (scene_i == outline.items[i])."""
    client = client or get_client()
    structural = True if structural is None else structural
    out = Path(out_dir) if out_dir else settings.out_dir / "decoupled"
    out.mkdir(parents=True, exist_ok=True)
    say = log or (lambda _m: None)

    if outline is None:
        say(f"-> outline for: {prompt!r}")
        outline = planner_outline.generate(prompt, client=client, max_scenes=max_scenes)
        if approve_fn is not None:
            outline = approve_fn(outline)
    else:
        say(f"-> using provided outline ({len(outline.items)} scenes)")
    say(f"   {len(outline.items)} scenes")
    style = style_gen_safe(prompt, outline, client)

    mode = "structural(grid)" if structural else "freehand"
    say(f"-> building {len(outline.items)} scenes (workers={workers}, retries={retries}, layout={mode})")
    scenes_dir = out / "scenes"
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(
            lambda iv: _build_with_retry(iv[1], outline, iv[0], scenes_dir=scenes_dir, client=client,
                                         style=style, use_components=use_components, use_critic=use_critic,
                                         structural=structural, quality=quality, retries=retries,
                                         on_scene=on_scene),
            list(enumerate(outline.items))))

    clips = [mp4 for _, mp4 in sorted(results, key=lambda r: r[0]) if mp4]
    say(f"   {len(clips)}/{len(outline.items)} scenes built")
    if not clips:
        return None
    say("-> stitching")
    return stitch.stitch(clips, work_dir=out / "final", out_name=out_name)


def style_gen_safe(prompt, outline, client):
    """Style is nice-to-have, not load-bearing — if it errors, proceed without it."""
    try:
        from generation import style as style_gen
        return style_gen.generate(prompt, outline, client=client)
    except Exception:
        return None
