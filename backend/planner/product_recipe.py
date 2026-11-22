"""Deterministic product-video recipe selection — structured generation guidance.

A recipe is plain data (keywords + guidance strings) that biases the existing planning
prompts toward a teaching approach. No new
schema, no LLM call: `pick_recipe` is pure keyword matching over
`prompts/product_video_recipes.json`. Callers that never pass a recipe see byte-identical
behavior — this module is only ever invoked when `--recipe` is explicitly given.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from core.config import settings
from planner.jev_router import RouteDecision, route as jev_route

_RECIPES_PATH = Path(__file__).resolve().parent.parent / "prompts" / "product_video_recipes.json"
FALLBACK_ID = "workflow_explainer"


@dataclass(frozen=True)
class Recipe:
    id: str
    keywords: tuple[str, ...]
    outline_guidance: str
    scene_guidance: str
    visual_pattern: str
    allowed_patterns: tuple[str, ...]
    required_roles: tuple[str, ...]
    # How a learning video on this recipe is drawn: "map" is one diagram of pieces for the whole
    # lesson, planned in a single call; "free" lets the visual step choose forms scene by scene.
    board: str = "free"
    # How the lesson is planned: "single" is one model call through the board's playbook;
    # "staged_table" is the staged table planner (`planner.lesson_recurrence`) and "staged_graph"
    # the graph-search one (`planner.lesson_graph`); each falls back to the single call when it
    # cannot plan the topic.
    planner: str = "single"


def load_recipes() -> dict[str, Recipe]:
    data = json.loads(_RECIPES_PATH.read_text(encoding="utf-8"))
    return {rid: Recipe(id=rid, keywords=tuple(r["keywords"]),
                       outline_guidance=r["outline_guidance"], scene_guidance=r["scene_guidance"],
                       visual_pattern=r["visual_pattern"],
                       allowed_patterns=tuple(r["allowed_patterns"]),
                       required_roles=tuple(r["required_roles"]), board=r.get("board", "free"),
                       planner=r.get("planner", "single"))
            for rid, r in data.items()}


def _keyword_pick(topic: str, recipes: dict[str, Recipe]) -> Recipe:
    """The established offline route, kept as the fallback for every Jev outcome."""
    low = topic.lower()
    best_id, best_score = FALLBACK_ID, 0
    for rid, recipe in recipes.items():
        score = sum(1 for kw in recipe.keywords if kw.lower() in low)
        if score > best_score:
            best_id, best_score = rid, score
    return recipes[best_id]


def _jev_pick(topic: str, recipes: dict[str, Recipe]) -> Recipe | None:
    if not settings.jev_enabled or not settings.jev_api_key:
        return None
    criteria = {
        recipe_id: f"{recipe.board} board: {recipe.outline_guidance}"
        for recipe_id, recipe in recipes.items()
    }
    decision: RouteDecision | None = jev_route(
        topic, criteria, api_key=settings.jev_api_key, base_url=settings.jev_base_url,
        model=settings.jev_model, timeout=settings.jev_timeout_s)
    if decision is None or decision.confidence < settings.jev_min_confidence:
        return None
    return recipes.get(decision.recipe_id)


def pick_recipe(topic: str, requested: str, *, recipes: dict[str, Recipe] | None = None) -> Recipe:
    """`requested` is "auto" or a recipe id — this is never called for the "no
    --recipe at all" case, which skips recipe selection entirely upstream.

    "auto": score each recipe by counting its keywords found (case-insensitive substring match)
    in `topic`; the highest-scoring recipe wins (first-declared wins a tie). Zero hits for every
    recipe -> FALLBACK_ID ("workflow_explainer").
    A specific id looks the recipe up directly and ignores keywords entirely.
    """
    recipes = recipes or load_recipes()
    if requested != "auto":
        if requested not in recipes:
            raise ValueError(f"unknown recipe id: {requested!r} (known: {sorted(recipes)})")
        return recipes[requested]

    return _jev_pick(topic, recipes) or _keyword_pick(topic, recipes)
