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


def load_recipes() -> dict[str, Recipe]:
    data = json.loads(_RECIPES_PATH.read_text(encoding="utf-8"))
    return {rid: Recipe(id=rid, keywords=tuple(r["keywords"]),
                       outline_guidance=r["outline_guidance"], scene_guidance=r["scene_guidance"],
                       visual_pattern=r["visual_pattern"],
                       allowed_patterns=tuple(r["allowed_patterns"]),
                       required_roles=tuple(r["required_roles"]))
            for rid, r in data.items()}


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

    low = topic.lower()
    best_id, best_score = FALLBACK_ID, 0
    for rid, recipe in recipes.items():
        score = sum(1 for kw in recipe.keywords if kw.lower() in low)
        if score > best_score:
            best_id, best_score = rid, score
    return recipes[best_id]
