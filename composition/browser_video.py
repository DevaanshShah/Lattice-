"""Narrated browser visual-plan clips, using the existing Chrome/TTS/FFmpeg primitives."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from composition.slides import _BEAT_PAD, _concat_clips, _norm_clip, _xfade_chain
from core.run_report import RunReport
from core.schemas.browser_visual_plan import BrowserVisualPlan
from core.schemas.lesson_plan import LessonPlan
from core.visual_state import VisualState, apply_action, closing_state, opening_state
from generation.manim_visual_scene import compile_scene
from generation.browser_scene import ball_after, render_scene, render_animated_beat
from narration.tts import synthesize
from planner.product_recipe import Recipe
from planner import browser_visual_plan, lesson_plan, product_recipe
from render.sandbox import render as render_manim
from verification.browser_layout import BrowserLayoutError
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


@dataclass(frozen=True)
class BrowserPlanResult:
    skill: Recipe
    lesson: LessonPlan
    visual_plan: BrowserVisualPlan


def build(lesson: LessonPlan, plan: BrowserVisualPlan, skill: Recipe, *, out_dir: str | Path,
          tts_engine: str | None = None, fps: int = 30, transition: float = 0.45,
          beat_transition: float = 0.22, scene_hold_s: float = 1.0,
          report: RunReport | None = None, log=None, on_scene=None) -> BrowserVideoResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    owns_report = report is None
    report = report or RunReport(out, topic=lesson.topic, recipe=skill.id, log=log)
    stage, scene_id, beat_id, scene_index = "validation", None, None, None
    try:
        report.event(stage, "start")
        validate(lesson, plan, skill)
        report.event(stage, "passed")
        scenes = {scene.lesson_scene_id: scene for scene in plan.scenes}
        frames: list[Path] = []
        scene_mp4s: list[Path] = []
        audio_dir = out / "audio"
        previous_state: VisualState | None = None
        ball: list[str] | None = None    # the arrow the travelling ball last moved along
        for scene_index, lesson_scene in enumerate(lesson.scenes):
            scene_id = lesson_scene.id
            if on_scene:
                on_scene(scene_index, "rendering")
            visual_scene = scenes[scene_id]
            state = opening_state(visual_scene, previous_state) if plan.schema_version == 2 else None
            if state is not None and visual_scene.render_mode == "manim":
                stage = "narration"
                audio_clips = []
                work = out / "manim" / f"scene_{scene_index:02d}"
                (work / "audio").mkdir(parents=True, exist_ok=True)
                for beat_index, beat in enumerate(lesson_scene.beats):
                    beat_id = beat.id
                    report.event(stage, "start", scene=scene_id, beat=beat_id)
                    clip = synthesize(beat.spoken_text, out_dir=audio_dir, engine=tts_engine)
                    rel = f"audio/beat_{beat_index:02d}{clip.path.suffix}"
                    shutil.copyfile(clip.path, work / rel)
                    audio_clips.append((rel, clip.duration))
                    report.event("timing", "passed", scene=scene_id, beat=beat_id,
                                 evidence={"audio_duration": clip.duration,
                                           "windows": visual_scene.beats[beat_index].timeline(clip.duration)})
                    report.event(stage, "passed", scene=scene_id, beat=beat_id,
                                 detail=f"{clip.duration:.3f}s")
                beat_id = None
                stage = "manim"
                report.event(stage, "start", scene=scene_id)
                source = compile_scene(visual_scene, title=lesson_scene.title,
                                       opening=state, audio=audio_clips)
                (work / "scene.py").write_text(source, encoding="utf-8")
                rendered = render_manim(work, "scene.py", "GeneratedScene", quality="preview")
                if not rendered.ok or not rendered.outputs:
                    raise RuntimeError(f"Manim scene {scene_id} failed: {rendered.stderr[-500:]}")
                scene_path = out / f"scene_{scene_index:02d}.mp4"
                scene_mp4s.append(_norm_clip(rendered.outputs[-1], scene_path, fps=fps))
                report.event(stage, "passed", scene=scene_id, detail=str(scene_path))
                previous_state = closing_state(visual_scene, previous_state)
                if on_scene:
                    on_scene(scene_index, "done")
                continue
            parts: list[Path] = []
            for beat_index, lesson_beat in enumerate(lesson_scene.beats):
                beat_id = lesson_beat.id
                stage = "narration"
                report.event(stage, "start", scene=scene_id, beat=beat_id)
                audio = synthesize(lesson_beat.spoken_text, out_dir=audio_dir, engine=tts_engine)
                report.event(stage, "passed", scene=scene_id, beat=beat_id,
                             detail=f"{audio.duration:.3f}s")
                if state is not None:
                    visual_beat = visual_scene.beats[beat_index]
                    timeline = visual_beat.timeline(audio.duration)
                    report.event("timing", "passed", scene=scene_id, beat=beat_id,
                                 evidence={"audio_duration": audio.duration, "windows": timeline})
                    if visual_beat.actions[0].start_fraction is not None:
                        stage = "animation"
                        report.event(stage, "start", scene=scene_id, beat=beat_id)
                        beat_clip = out / "beats" / f"scene_{scene_index:02d}_{beat_index:02d}.mp4"
                        try:
                            captured = render_animated_beat(visual_scene, visual_beat, beat_clip,
                                title=lesson_scene.title, opening=state, duration=audio.duration,
                                audio=audio.path, fps=fps, ball=ball)
                            attempt = 1
                        except BrowserLayoutError as exc:
                            report.event(stage, "retry", scene=scene_id, beat=beat_id,
                                         category="layout", issues=exc.issues,
                                         action="retry_compact_layout", attempt=1,
                                         evidence={"geometry": exc.geometry})
                            captured = render_animated_beat(visual_scene, visual_beat, beat_clip,
                                title=lesson_scene.title, opening=state, duration=audio.duration,
                                audio=audio.path, fps=fps, layout_mode="compact", ball=ball)
                            attempt = 2
                        ball = ball_after(visual_scene, visual_beat, ball)
                        for action in visual_beat.actions:
                            apply_action(state, action)
                        frames.extend(captured)
                        parts.append(beat_clip)
                        report.event(stage, "passed", scene=scene_id, beat=beat_id, attempt=attempt,
                                     evidence={"frames": len(captured), "fps": fps})
                        continue
                    action_clips: list[Path] = []
                    events = [(action, (timeline[index + 1][0] if index + 1 < len(timeline)
                                        else audio.duration) - timeline[index][0])
                              for index, action in enumerate(visual_beat.actions)]
                    if timeline[0][0] > 0:
                        events.insert(0, (None, timeline[0][0]))
                    for action_index, (action, seconds) in enumerate(events):
                        if action is not None:
                            apply_action(state, action)
                        action_id = action.id if action is not None else "opening_hold"
                        stage = "layout"
                        frame_path = out / "frames" / (
                            f"scene_{scene_index:02d}_{beat_index:02d}_{action_index:02d}.png")
                        report.event(stage, "start", scene=scene_id, beat=beat_id,
                                     detail=action_id, attempt=1)
                        try:
                            frame = render_scene(visual_scene, frame_path,
                                                 title=lesson_scene.title, state=state)
                            attempt = 1
                        except BrowserLayoutError as exc:
                            report.event(stage, "retry", scene=scene_id, beat=beat_id,
                                         detail=action_id, attempt=1, category="layout",
                                         issues=exc.issues, action="retry_compact_layout",
                                         evidence={"geometry": exc.geometry})
                            frame = render_scene(visual_scene, frame_path,
                                                 title=lesson_scene.title, state=state,
                                                 layout_mode="compact")
                            attempt = 2
                        report.event(stage, "passed", scene=scene_id, beat=beat_id,
                                     detail=action_id, attempt=attempt)
                        frames.append(frame)
                        stage = "clip"
                        segment = out / "beats" / (
                            f"scene_{scene_index:02d}_{beat_index:02d}_{action_index:02d}.mp4")
                        action_clips.append(_norm_clip(
                            frame, segment, seconds=seconds, fps=fps))
                    beat_clip = out / "beats" / f"scene_{scene_index:02d}_{beat_index:02d}.mp4"
                    parts.append(_concat_clips(action_clips, beat_clip, audio=audio.path))
                    report.event(stage, "passed", scene=scene_id, beat=beat_id)
                    continue
                stage = "layout"
                frame_path = out / "frames" / f"scene_{scene_index:02d}_{beat_index:02d}.png"
                report.event(stage, "start", scene=scene_id, beat=beat_id, attempt=1)
                try:
                    frame = render_scene(visual_scene, frame_path, title=lesson_scene.title,
                                         active_beat_id=beat_id)
                    layout_attempt = 1
                except BrowserLayoutError as exc:
                    report.event(stage, "retry", scene=scene_id, beat=beat_id, attempt=1,
                                 category="layout", issues=exc.issues,
                                 action="retry_compact_layout",
                                 evidence={"geometry": exc.geometry})
                    report.event(stage, "start", scene=scene_id, beat=beat_id, attempt=2,
                                 action="compact_layout")
                    frame = render_scene(visual_scene, frame_path, title=lesson_scene.title,
                                         active_beat_id=beat_id, layout_mode="compact")
                    layout_attempt = 2
                report.event(stage, "passed", scene=scene_id, beat=beat_id,
                             attempt=layout_attempt)
                frames.append(frame)
                stage = "clip"
                report.event(stage, "start", scene=scene_id, beat=beat_id)
                hold = scene_hold_s if beat_index == len(lesson_scene.beats) - 1 else _BEAT_PAD
                parts.append(_norm_clip(frame, out / "beats" / f"scene_{scene_index:02d}_{beat_index:02d}.mp4",
                                        seconds=audio.duration + hold, fps=fps, audio=audio.path))
                report.event(stage, "passed", scene=scene_id, beat=beat_id)
            if state is not None:
                previous_state = state
            stage = "scene_stitch"
            beat_id = None
            report.event(stage, "start", scene=scene_id)
            scene_path = out / f"scene_{scene_index:02d}.mp4"
            if plan.schema_version != 2 and beat_transition > 0 and len(parts) > 1:
                _xfade_chain(parts, scene_path, dur=beat_transition)
            else:
                _concat_clips(parts, scene_path)
            scene_mp4s.append(scene_path)
            report.event(stage, "passed", scene=scene_id, detail=str(scene_path))
            if on_scene:
                on_scene(scene_index, "done")
        stage, scene_id, beat_id = "stitch", None, None
        report.event(stage, "start")
        final = out / "browser-video.mp4"
        if plan.schema_version != 2 and transition > 0 and len(scene_mp4s) > 1:
            _xfade_chain(scene_mp4s, final, dur=transition)
        else:
            _concat_clips(scene_mp4s, final)
        report.event(stage, "passed", detail=str(final))
        if owns_report:
            report.complete(artifact=final)
        return BrowserVideoResult(mp4=final, scene_mp4s=scene_mp4s, frames=frames)
    except Exception as exc:
        if on_scene and scene_index is not None and scene_id is not None:
            on_scene(scene_index, "failed")
        issues = exc.issues if isinstance(exc, BrowserLayoutError) else None
        evidence = {"geometry": exc.geometry} if isinstance(exc, BrowserLayoutError) else None
        if report.data["status"] != "failed":
            report.failure(stage, exc, scene=scene_id, beat=beat_id, issues=issues,
                           evidence=evidence)
        raise


def plan(topic: str, *, recipe: str = "auto", approve_fn=None, out_dir: str | Path,
         client=None, max_scenes: int | None = None, report: RunReport | None = None,
         log=None, schema_version: int = 1) -> BrowserPlanResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    owns_report = report is None
    report = report or RunReport(out, topic=topic, recipe=recipe, log=log)
    stage = "recipe"
    try:
        skill = product_recipe.pick_recipe(topic, recipe)
        report.data["recipe"] = skill.id
        report.event(stage, "passed", detail=skill.id)
        stage = "lesson_plan"
        report.event(stage, "start")
        lesson_kwargs = {"schema_version": schema_version} if schema_version == 2 else {}
        lesson = lesson_plan.generate(topic, skill, client=client, **lesson_kwargs)
        report.event(stage, "passed", detail=f"{len(lesson.scenes)} scene(s)")
        if approve_fn is not None:
            lesson = approve_fn(lesson)
            if not isinstance(lesson, LessonPlan):
                raise TypeError("browser-video approval must return a LessonPlan")
        if max_scenes is not None:
            lesson = lesson.model_copy(update={"scenes": lesson.scenes[:max_scenes]})
        lesson_path = out / "lesson_plan.json"
        lesson_path.write_text(lesson.model_dump_json(indent=2), encoding="utf-8")
        stage = "visual_plan"
        report.event(stage, "start")
        visual_kwargs = ({**lesson_kwargs, "diagnostic_dir": out / "visual_attempts"}
                         if schema_version == 2 else {})
        plan = browser_visual_plan.generate(lesson, skill, client=client, **visual_kwargs)
        report.event(stage, "passed", detail=f"{len(plan.scenes)} scene(s)")
        visual_path = out / "browser_visual_plan.json"
        visual_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        if owns_report:
            report.planned()
        return BrowserPlanResult(skill=skill, lesson=lesson, visual_plan=plan)
    except Exception as exc:
        if report.data["status"] != "failed":
            report.failure(stage, exc)
        raise


def generate(topic: str, *, recipe: str = "auto", approve_fn=None, out_dir: str | Path,
             client=None, tts_engine: str | None = None, fps: int = 30,
             transition: float = 0.45, log=None, schema_version: int = 1) -> BrowserGenerationResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = RunReport(out, topic=topic, recipe=recipe, log=log)
    try:
        plan_kwargs = {"schema_version": schema_version} if schema_version == 2 else {}
        planned = plan(topic, recipe=recipe, approve_fn=approve_fn, out_dir=out,
                       client=client, report=report, log=log, **plan_kwargs)
        render = build(planned.lesson, planned.visual_plan, planned.skill, out_dir=out,
                       tts_engine=tts_engine, fps=fps, transition=transition,
                       report=report, log=log)
        report.complete(artifact=render.mp4)
        return BrowserGenerationResult(skill=planned.skill, lesson=planned.lesson,
                                       visual_plan=planned.visual_plan, render=render)
    except Exception as exc:
        if report.data["status"] != "failed":
            report.failure("run", exc)
        raise
