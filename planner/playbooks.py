"""The playbooks: each way a lesson can be drawn from one model call.

A playbook is a lesson prompt, a menu of moves, and the code that turns those moves into scenes
and checks them. The recipe picked for a topic names its playbook in `board`; a board with no
playbook ("free") keeps the model-written visual step.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.schemas.lesson_plan import LessonPlan
from planner import lesson_map, lesson_trace


@dataclass(frozen=True)
class Playbook:
    board: str          # the value of a recipe's `board`
    key: str            # the lesson field that carries its picture
    prompt: str         # the lesson prompt, a file in prompts/
    needs_icons: bool   # whether the model is given the icon list
    beat_words: int     # words in a typical sentence, for turning a length into a number of beats
    fill: Callable      # complete what the model wrote: ids, claims, proof
    problems: Callable  # why the lesson cannot be drawn
    scenes: Callable    # compile every scene, checked by the validator
    craft: Callable     # where the lesson falls short as teaching


PLAYBOOKS = {
    "map": Playbook("map", "map", "lesson-plan-map", True, 17, lesson_map.fill_map_lesson,
                    lesson_map.lesson_map_problems, lesson_map.plan_map_scenes,
                    lesson_map.craft_problems),
    # sentences about a step of an algorithm are short ("Seventeen is not thirty."), so more beats
    "trace": Playbook("trace", "trace", "lesson-plan-trace", False, 13, lesson_trace.fill_trace_lesson,
                      lesson_trace.trace_problems, lesson_trace.plan_trace_scenes,
                      lesson_trace.craft_trace),
}


def playbook_of(lesson: LessonPlan) -> Playbook | None:
    """The playbook a saved lesson was written for, from the picture it carries."""
    return next((playbook for playbook in PLAYBOOKS.values()
                 if getattr(lesson, playbook.key) is not None), None)
