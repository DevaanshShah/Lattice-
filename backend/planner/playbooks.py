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
    shortest: int = 0   # seconds below which this kind of lesson is not asked for
    guided: bool = True     # whether the recipe's own outline is sent as well as the prompt
    facts: Callable | None = None   # what code works out from the picture alone, sent with a repair


PLAYBOOKS = {
    "map": Playbook("map", "map", "lesson-plan-map", True, 17, lesson_map.fill_map_lesson,
                    lesson_map.lesson_map_problems, lesson_map.plan_map_scenes,
                    lesson_map.craft_problems),
    # A sentence that carries the reason for a step runs to about fifteen words; sized any
    # shorter, a lesson that explains itself comes out over length and is sent back for it.
    # The recipe's outline is not sent: it is an older story than the prompt's and was read last.
    # An algorithm needs a naive attempt, a better one and the reason between them: reviewed at
    # 45 seconds, every lesson rushed its core, so none is asked for in under ninety.
    "trace": Playbook("trace", "trace", "lesson-plan-trace", False, 15, lesson_trace.fill_trace_lesson,
                      lesson_trace.trace_problems, lesson_trace.plan_trace_scenes,
                      lesson_trace.craft_trace, shortest=90, guided=False,
                      facts=lesson_trace.trace_facts),
}


def playbook_of(lesson: LessonPlan) -> Playbook | None:
    """The playbook a saved lesson was written for, from the picture it carries."""
    return next((playbook for playbook in PLAYBOOKS.values()
                 if getattr(lesson, playbook.key) is not None), None)
