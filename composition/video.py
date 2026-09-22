"""M5 orchestrator — topic -> approved outline -> styled, narrated, parallel-rendered scenes
-> one stitched video. Composes the planner + style + M1–M4 build + DAG + bounded pool + stitch.

`build_scene` (expand -> narrate one scene with the shared style) is the unit both the parallel
build and isolated regeneration (regen.py) reuse.
"""
from __future__ import annotations

from pathlib import Path

from composition import pool, slides, stitch
from composition.scene_dag import SceneNode, VideoProject
from core.config import settings
from core.llm import LLMClient, get_client
from core.schemas.outline import Outline, OutlineItem
from core.schemas.scene_spec import SceneSpec
from generation import style as style_gen
from narration import narrate
from planner import expand as planner_expand
from planner import outline as planner_outline
from planner import product_recipe, slide_plan


def _outline_of(project: VideoProject) -> Outline:
    return Outline(topic=project.topic,
                   items=[OutlineItem(title=s.title, intent=s.intent) for s in project.scenes])


def _deck_outline(topic: str, deck: slide_plan.Deck) -> tuple[Outline, list[tuple[str, str]]]:
    """Present the existing approval gate with deck content, then map it back to deck order."""
    keys = []
    items = []
    for index, slide in enumerate(deck.slides):
        title = slide.title or f"Slide {index + 1}"
        intent = slide.script() or slide.kind
        key = (title, intent)
        keys.append(key)
        items.append(OutlineItem(title=title, intent=intent))
    return Outline(topic=topic, items=items), keys


def _approved_deck(deck: slide_plan.Deck, topic: str, approve_fn):
    outline, keys = _deck_outline(topic, deck)
    if approve_fn is None:
        return deck.slides
    approved = approve_fn(outline)
    by_key: dict[tuple[str, str], list[int]] = {}
    for index, key in enumerate(keys):
        by_key.setdefault(key, []).append(index)
    selected = []
    for item in approved.items:
        matches = by_key.get((item.title, item.intent))
        if not matches:
            raise ValueError("deck approval returned a slide that was not planned")
        selected.append(deck.slides[matches[0]])
    return selected


def _build_recipe_deck(topic: str, recipe, *, approve_fn, out_dir: Path, client: LLMClient,
                       quality: str, log) -> VideoProject:
    """Product recipes use the existing content-only browser renderer, not generated Manim code."""
    guidance = (f"{recipe.outline_guidance}\n\n{recipe.scene_guidance}\n\n"
                f"Required visual pattern: {recipe.visual_pattern}. Use only the supported fixed "
                "slide kinds and make every important mechanism a named card, chip, or bullet.")
    deck = slide_plan.plan_deck(topic, client=client, recipe_guidance=guidance)
    chosen = _approved_deck(deck, topic, approve_fn)
    say = log or (lambda _m: None)
    say(f"-> recipe: {recipe.id} (browser deck)")
    say(f"-> building {len(chosen)} fixed-layout slide(s)")
    final = slides.build_deck(chosen, out_dir, footer="Lattice", math_quality=quality)

    outline, _ = _deck_outline(topic, slide_plan.Deck(title=deck.title, slides=chosen))
    project = VideoProject.from_outline(outline)
    for index, (node, slide) in enumerate(zip(project.scenes, chosen)):
        node.script = [str(beat.get("say", "")).strip() for beat in slide.beats]
        node.compiled = True
        clip = out_dir / f"clip_{index:02d}.mp4"
        node.mp4 = str(clip) if clip.exists() else None
    project.final_mp4 = str(final)
    project.save(out_dir / "project.json")
    return project


def _story_context(project: VideoProject, idx: int) -> str:
    """The narration's story arc: where this scene sits in the whole video + what's around it, so
    the narrator links scenes into one continuous lesson (callbacks/bridges) instead of isolated clips.
    Uses the outline (titles+intents — known up front, so it works during parallel build)."""
    n = len(project.scenes)
    if n <= 1:
        return ""
    arc = "\n".join(f"  {i + 1}. {s.title} — {s.intent}" for i, s in enumerate(project.scenes))
    lines = [f'STORY CONTEXT — this is scene {idx + 1} of {n} in ONE continuous explainer video on '
             f'"{project.topic}". It is part of a flowing lesson, not a standalone clip.',
             "Full arc, in order:", arc]
    prev = [s.title for s in project.scenes[:idx]]
    if prev:
        lines.append(f'Scenes BEFORE this one already covered: {", ".join(prev)}. OPEN by connecting to '
                     'what the viewer just saw (e.g. "Now that we have a single neuron, ..."); do NOT '
                     're-introduce those ideas from scratch.')
    if idx + 1 < n:
        lines.append(f'The NEXT scene is "{project.scenes[idx + 1].title}". END with a short bridge that '
                     'leads into it, so the video flows.')
    lines.append("Write it like a great explainer-YouTube narrator teaching a story: warm, connected, "
                 "building on what we already know.")
    return "\n".join(lines)


def _expand_scene_spec(node: SceneNode, project: VideoProject, *, client: LLMClient,
                       recipe_scene_guidance: str | None = None,
                       recipe_visual_pattern: str | None = None,
                       previous_spec: SceneSpec | None = None) -> SceneSpec:
    """Create one locked spec. Product recipes call this in outline order before parallel render."""
    if node.spec is not None:
        return node.spec
    item = OutlineItem(title=node.title, intent=node.intent)
    expand_kwargs = {"client": client}
    if recipe_scene_guidance:
        expand_kwargs["recipe_guidance"] = recipe_scene_guidance
    if recipe_visual_pattern:
        expand_kwargs["visual_pattern"] = recipe_visual_pattern
    if previous_spec is not None:
        expand_kwargs["previous_spec"] = previous_spec
    node.spec = planner_expand.expand(item, _outline_of(project), node.index, **expand_kwargs)
    return node.spec


def build_scene(node: SceneNode, project: VideoProject, *, scenes_dir: Path,
                quality: str, client: LLMClient, log=print,
                recipe_scene_guidance: str | None = None,
                recipe_visual_pattern: str | None = None,
                recipe_structural: bool = False,
                previous_spec: SceneSpec | None = None) -> SceneNode:
    """Build one scene: (expand if needed) -> narrate+render with the shared style.

    Mutates and returns `node`. Reuses `node.spec` when it already exists (so re-time/tweak/regen
    are deterministic and don't silently re-author the scene); only expands a fresh scene. The
    work dir is keyed off the IMMUTABLE `node.sid`, so reorder/insert never collide. Each call
    uses its own dir, so parallel builds don't clash.

    recipe_scene_guidance: optional product-video recipe guidance (planner/product_recipe.py),
    forwarded to expand() only when a spec still needs generating. None (the default, and every
    caller that doesn't pass --recipe) leaves scene generation unchanged.
    """
    spec = _expand_scene_spec(node, project, client=client,
                              recipe_scene_guidance=recipe_scene_guidance,
                              recipe_visual_pattern=recipe_visual_pattern,
                              previous_spec=previous_spec)
    wd = scenes_dir / f"scene_{node.sid}"
    narrate_kwargs = {"work_dir": wd, "quality": quality, "client": client,
                      "style": project.style, "context": _story_context(project, node.index), "log": log}
    if recipe_structural:
        narrate_kwargs["structural"] = True
    res = narrate.build(spec, **narrate_kwargs)
    node.spec = spec
    node.code = res.code
    node.compiled = res.compiled
    node.mp4 = str(res.mp4) if res.mp4 else None
    node.srt = str(res.srt) if res.srt else None
    node.script = list(res.lines)   # persist narration text (rollback reproducibility, FR-21)
    return node


def build_project(project: VideoProject, *, quality: str = "preview",
                  out_dir: str | Path, client: LLMClient | None = None, cap: int | None = None,
                  log=print, on_scene=None, recipe_scene_guidance: str | None = None,
                  recipe_visual_pattern: str | None = None,
                  recipe_structural: bool = False,
                  recipe_continuity: bool = False) -> VideoProject:
    """Build all scenes of an already-planned project (style set) in parallel, stitch, persist.

    The post-approval half of generate_video, factored out so the web layer (M7) can drive it
    after its own outline-approval gate WITHOUT re-planning. `on_scene(index, status)` fires with
    status in {"rendering","done","failed"} around each scene so a UI can show live per-scene
    state (FR-24/FR-29). Failure isolation is unchanged: a scene failing doesn't abort the rest.

    recipe_scene_guidance: optional product-video recipe guidance, forwarded to each build_scene
    call. None (the default) leaves every call identical to before this parameter existed.
    """
    client = client or get_client()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    say = log or (lambda _m: None)
    scenes_dir = out / "scenes"

    if recipe_continuity:
        # Rendering remains parallel. Only planning is ordered, because scene N+1 must know the
        # final visual state of scene N before it can declare a carryover anchor.
        say("-> planning visual handoffs between recipe scenes")
        previous_spec = None
        for node in project.scenes:
            previous_spec = _expand_scene_spec(
                node, project, client=client, recipe_scene_guidance=recipe_scene_guidance,
                recipe_visual_pattern=recipe_visual_pattern, previous_spec=previous_spec,
            )

    def work(node: SceneNode, _i: int) -> SceneNode:
        if on_scene:
            on_scene(node.index, "rendering")
        try:
            build_kwargs = {"scenes_dir": scenes_dir, "quality": quality, "client": client, "log": say}
            if recipe_scene_guidance:
                build_kwargs["recipe_scene_guidance"] = recipe_scene_guidance
            if recipe_visual_pattern:
                build_kwargs["recipe_visual_pattern"] = recipe_visual_pattern
            if recipe_structural:
                build_kwargs["recipe_structural"] = True
            build_scene(node, project, **build_kwargs)
        except Exception:
            if on_scene:
                on_scene(node.index, "failed")
            raise
        if on_scene:
            on_scene(node.index, "done" if node.mp4 else "failed")
        return node

    say(f"-> building {len(project.scenes)} scenes in parallel (cap={cap or settings.concurrency_cap})")
    results = pool.run_bounded(project.scenes, work, cap=cap)  # build_scene mutates each node in place
    for result in results:
        if not result.ok:
            say(f"   scene {result.index + 1} failed: {result.error}")

    ready = project.ordered_mp4s()
    say(f"   {len(ready)}/{len(project.scenes)} scene(s) rendered")
    if ready:
        say("-> stitching final video")
        project.final_mp4 = str(stitch.stitch(ready, work_dir=out, out_name="final.mp4"))

    project.save(out / "project.json")
    return project


def generate_video(topic: str, *, approve_fn=None, quality: str = "preview",
                   out_dir: str | Path | None = None, client: LLMClient | None = None,
                   cap: int | None = None, log=print, on_scene=None,
                   recipe: str | None = None) -> VideoProject:
    """recipe: None (the default — no --recipe given) skips product-video recipe selection
    entirely, so outline/scene generation is byte-identical to before this parameter existed.
    "auto" runs the deterministic keyword picker (planner/product_recipe.py, falls back to
    workflow_explainer on no match); a specific recipe id selects that recipe directly."""
    client = client or get_client()
    out = Path(out_dir) if out_dir else settings.out_dir / "video"
    out.mkdir(parents=True, exist_ok=True)
    say = log or (lambda _m: None)

    if recipe is not None:
        selected = product_recipe.pick_recipe(topic, recipe)
        return _build_recipe_deck(topic, selected, approve_fn=approve_fn, out_dir=out,
                                  client=client, quality=quality, log=say)

    outline_guidance = scene_guidance = visual_pattern = None
    recipe_structural = recipe_continuity = False

    say(f"-> planning outline for: {topic!r}")
    outline_kwargs = {"client": client}
    if outline_guidance:
        outline_kwargs["recipe_guidance"] = outline_guidance
    outline = planner_outline.generate(topic, **outline_kwargs)
    if approve_fn is not None:
        outline = approve_fn(outline)          # the approval gate, BEFORE any render
    say(f"   {len(outline.items)} scene(s) approved")

    say("-> style spec (one per video)")
    style = style_gen.generate(topic, outline, client=client)

    project = VideoProject.from_outline(outline, style=style)
    return build_project(project, quality=quality, out_dir=out, client=client, cap=cap,
                         log=say, on_scene=on_scene, recipe_scene_guidance=scene_guidance,
                         recipe_visual_pattern=visual_pattern, recipe_structural=recipe_structural,
                         recipe_continuity=recipe_continuity)
