"""Narrated browser visual-plan clips, using the existing Chrome/TTS/FFmpeg primitives."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from composition.slides import _BEAT_PAD, _concat_clips, _norm_clip, _xfade_chain
from core.schemas.browser_visual_plan import BrowserVisualPlan
from core.schemas.lesson_plan import LessonPlan
from generation.browser_scene import render_scene
from narration.tts import synthesize
from planner.product_recipe import Recipe
from planner import browser_visual_plan, lesson_plan, product_recipe
from verification.visual_plan_validation import validate


@dataclass(frozen=True)
class BrowserVideoResult:
    mp4: Path
    scene_mp4s: list[Path]
    frames: list[Path]


@dataclass(frozen=True)
class BrowserGenerationResult:
    skill: Recipe
    lesson: LessonPlan
    visual_plan: BrowserVisualPlan
    render: BrowserVideoResult


def build(lesson: LessonPlan, plan: BrowserVisualPlan, skill: Recipe, *, out_dir: str | Path,
          tts_engine: str | None = None, fps: int = 30, transition: float = 0.45,
          beat_transition: float = 0.22, scene_hold_s: float = 1.0) -> BrowserVideoResult:
    validate(lesson, plan, skill)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    scenes = {scene.lesson_scene_id: scene for scene in plan.scenes}
    frames: list[Path] = []
    scene_mp4s: list[Path] = []
    audio_dir = out / "audio"
    for scene_index, lesson_scene in enumerate(lesson.scenes):
        visual_scene = scenes[lesson_scene.id]
        parts: list[Path] = []
        for beat_index, lesson_beat in enumerate(lesson_scene.beats):
            audio = synthesize(lesson_beat.spoken_text, out_dir=audio_dir, engine=tts_engine)
            frame = render_scene(visual_scene, out / "frames" / f"scene_{scene_index:02d}_{beat_index:02d}.png",
                                 title=lesson_scene.title, active_beat_id=lesson_beat.id)
            frames.append(frame)
            hold = scene_hold_s if beat_index == len(lesson_scene.beats) - 1 else _BEAT_PAD
            parts.append(_norm_clip(frame, out / "beats" / f"scene_{scene_index:02d}_{beat_index:02d}.mp4",
                                    seconds=audio.duration + hold, fps=fps, audio=audio.path))
        scene_path = out / f"scene_{scene_index:02d}.mp4"
        if beat_transition > 0 and len(parts) > 1:
            _xfade_chain(parts, scene_path, dur=beat_transition)
        else:
            _concat_clips(parts, scene_path)
        scene_mp4s.append(scene_path)
    final = out / "browser-video.mp4"
    if transition > 0 and len(scene_mp4s) > 1:
        _xfade_chain(scene_mp4s, final, dur=transition)
    else:
        _concat_clips(scene_mp4s, final)
    return BrowserVideoResult(mp4=final, scene_mp4s=scene_mp4s, frames=frames)


def generate(topic: str, *, recipe: str = "auto", approve_fn=None, out_dir: str | Path,
             client=None, tts_engine: str | None = None, fps: int = 30,
             transition: float = 0.45) -> BrowserGenerationResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    skill = product_recipe.pick_recipe(topic, recipe)
    lesson = lesson_plan.generate(topic, skill, client=client)
    if approve_fn is not None:
        lesson = approve_fn(lesson)
        if not isinstance(lesson, LessonPlan):
            raise TypeError("browser-video approval must return a LessonPlan")
    lesson_path = out / "lesson_plan.json"
    lesson_path.write_text(lesson.model_dump_json(indent=2), encoding="utf-8")
    plan = browser_visual_plan.generate(lesson, skill, client=client)
    visual_path = out / "browser_visual_plan.json"
    visual_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    render = build(lesson, plan, skill, out_dir=out, tts_engine=tts_engine, fps=fps,
                   transition=transition)
    return BrowserGenerationResult(skill=skill, lesson=lesson, visual_plan=plan, render=render)
