"""A graph-search lesson (breadth-first or depth-first) planned in steps, so no model writes a move.

Single-call algorithm lessons failed on graphs: the trace board had no graph, and a model asked to
act a search out step by step lost track of the queue. The work is split the way the table lessons
are (`planner/lesson_recurrence.py`):

1. A model decides the teaching and describes the graph as a real situation (rooms of a maze,
   cities, pages): its nodes, edges, start, goal and which search. Code checks the graph.
2. Code runs the search (`core/graph_search.py`) and builds every step in order.
3. A model is shown those steps, with the node taken and the queue at each, and writes one
   sentence for each.

The lesson that comes out is an ordinary trace lesson, compiled and checked like any other.
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field

from core.graph_search import frontier_line, problems, search
from core.llm import LLMClient, get_client
from narration.tts import opens_on_name
from core.schemas.lesson_plan import LINE_LENGTH, LessonBrief, LessonPlan
from planner import lesson_trace
from planner.lesson_recurrence import _ask
from planner.product_recipe import Recipe
from prompts.loader import load


# How long a step's narration may run. A step that must say one thing gets one sentence; the opening
# (the problem and what a node and a line stand for) and the path (how it is read back, how long,
# whether it is shortest) must say several, and were refused three times live at forty words
# (2026-11-22).
WORDS_ONE, WORDS_SEVERAL = 40, 60


class GraphSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(..., min_length=1, max_length=22)        # "The maze", "Train lines"
    means: str = Field(..., min_length=1, max_length=120)       # what a node and an edge stand for (not shown on screen)
    nodes: list[str] = Field(..., min_length=3, max_length=10)
    edges: list[list[str]] = Field(..., min_length=2, max_length=14)
    source: str
    goal: str
    order: str = Field(..., pattern="^(bfs|dfs)$")
    name: str = Field(..., min_length=1, max_length=40)         # "breadth-first search"

    def model_post_init(self, _) -> None:
        long = [node for node in self.nodes if len(node) > 3]
        if long:
            raise ValueError(f"node {long[0]!r} is drawn in a circle: at most three characters, "
                             "such as 'S', 'A' or 'NYC'; say what it stands for in 'means'")
        faults = problems(self.nodes, self.edges, self.source, self.goal)
        if faults:
            raise ValueError("; ".join(faults))
        found = search(self.nodes, self.edges, self.source, self.goal, self.order)
        if len(found["path"]) < 3:
            raise ValueError(f"the goal {self.goal!r} is next to the start, so there is nothing to "
                             "search for; put it at least two lines away, with two routes to it")
        if len(found["steps"]) < 3:
            raise ValueError("the search reaches the goal in fewer than three steps; make the graph "
                             "big enough that the order of the search matters")


# A target at or over this many seconds gets the full lesson: every step of the search on its own
# beat, and a closing scene on the catch and where the technique is used. A lesson asked for no
# length is a full one: the one-minute lessons the owner saw on 2026-11-22 were "really short".
FULL_FROM_SECONDS = 100
DEFAULT_SECONDS = 150


class GraphConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: LessonBrief
    graph: GraphSpec
    uses: str | None = Field(None, min_length=1, max_length=200)    # where it is used in real life

    def model_post_init(self, _) -> None:
        # the turning point is shown on screen; found here, it is repaired with the rest of the brief
        if len(self.brief.turning_point) > LINE_LENGTH:
            raise ValueError(f"brief.turning_point is shown on screen: at most {LINE_LENGTH} "
                             f"characters, not {len(self.brief.turning_point)}; say it in fewer words")


def build_run(concept: GraphConcept, full: bool = True) -> tuple[dict, list[dict]]:
    """The whole lesson as code decides it, and the steps the narration step is shown.
    `full` is the long lesson: one node a step to the end, then the catch and the uses."""
    graph, brief = concept.graph, concept.brief
    found = search(graph.nodes, graph.edges, graph.source, graph.goal, graph.order)
    trace = {"data": [
        {"id": "graph", "kind": "graph", "label": graph.label, "nodes": graph.nodes,
         "edges": graph.edges, "source": graph.source, "goal": graph.goal, "order": graph.order},
        {"id": "taken", "kind": "counter", "label": "Taken so far", "counts": "graph"}]}
    waiting = "queue" if graph.order == "bfs" else "stack"
    steps: list[tuple[int, dict, str, str]] = []

    def step(scene: int, move: dict, sees: str, explain: str, words: int = WORDS_ONE) -> None:
        steps.append((scene, move, sees, explain, words))

    step(0, {"do": "show", "items": ["graph"]},
         f"the graph '{graph.label}': nodes {', '.join(graph.nodes)}; {graph.means}; the search "
         f"starts at {graph.source} and looks for {graph.goal}",
         f"State the problem ({brief.problem}) and say what a node and a line stand for.",
         WORDS_SEVERAL)
    step(0, {"do": "ask"}, f"the question on screen: {brief.question}", "said by code")
    step(1, {"do": "turn"}, f"the idea on screen: {brief.turning_point}", "said by code")
    if full:
        step(1, {"do": "show", "items": ["graph"]},
             f"the graph again, with the {waiting} holding only {graph.source}",
             f"Explain the {waiting} before the search starts: what it is (a waiting list of rooms "
             f"found but not yet visited), the rule for which room leaves it first "
             f"({'the one that has waited longest' if graph.order == 'bfs' else 'the one added last'}), "
             f"and that the search starts by putting {graph.source} in it.", WORDS_SEVERAL)
    # one node per step while the rule is new, then two at a time
    taken, index = 0, 0
    while taken < len(found["steps"]):
        count = 1 if full or index < 3 else min(2, len(found["steps"]) - taken)
        batch = found["steps"][taken:taken + count]
        taken += count
        last = batch[-1]
        what = "; ".join(f"{one['node']} is taken" + (f" and adds {', '.join(one['added'])}"
                                                       if one["added"] else " and adds nothing new")
                         for one in batch)
        step(1 if taken <= 3 else 2, {"do": "explore", "graph": "graph", **({"count": count} if count > 1 else {})},
             f"{what}. {frontier_line({'order': graph.order, 'frontier': last['frontier']})}. "
             f"Taken so far: {taken}",
             (f"Say which node comes out of the {waiting} and why it is that one, and what it adds."
              if count == 1 else f"Say these come out of the {waiting} in turn, and what they add.")
             + (f" This is {graph.goal}, the goal: say the search stops here." if last["node"] == graph.goal else ""))
        index += 1
        if full and index == 4 and taken < len(found["steps"]) - 1:
            step(2, {"do": "show", "items": ["graph"]},
                 f"the search part way through: {taken} rooms taken, {len(graph.nodes) - taken} to go",
                 f"Pause to say, in your own words, the one rule the learner has now seen work "
                 f"({taken} rooms in), and what to watch for in the next step.")
    step(2, {"do": "found", "graph": "graph"},
         f"the path found is drawn: {' -> '.join(found['path'])}, {len(found['path']) - 1} edges",
         "Say how the path is read back from where each node was first found, and how long it is"
         + (", and why breadth-first search makes it the shortest." if graph.order == "bfs"
            else ", and that depth-first search does not promise the shortest."), WORDS_SEVERAL)
    if full:
        step(3, {"do": "count", "counter": "taken", "expect": len(found["steps"])},
             f"the count reads {len(found['steps'])}: every room the search took",
             f"Say the catch: {brief.catch} Say the number as {{taken}}, the rooms the search had to take.")
        if concept.uses:
            step(3, {"do": "show", "items": ["graph"]}, "the whole graph again, with the path lit",
                 f"Say where {graph.name} is used in real life ({concept.uses}) and when to pick it.",
                 WORDS_SEVERAL)
    titles = ("The problem", "The search", "The way through", "What to remember")[:4 if full else 3]
    scenes = [{"title": title, "learning_goal": title,
               "beats": [{"move": move, "spoken_text": ""} for scene, move, *_ in steps if scene == number]}
              for number, title in enumerate(titles)]
    lesson = {"brief": brief.model_dump(exclude_none=True), "trace": trace, "scenes": scenes}
    shown = [{"step": index + 1, "scene": scene + 1, "the viewer sees": sees, "the sentence must": explain,
              **({"at most words": words} if explain != "said by code" else {})}
             for index, (scene, _, sees, explain, words) in enumerate(steps)]
    return lesson, shown


def generate(topic: str, skill: Recipe, *, client: LLMClient | None = None,
             target_seconds: float | None = None) -> LessonPlan:
    """Plan a graph-search lesson in two model calls with code between them."""
    client = client or get_client()
    full = (target_seconds or DEFAULT_SECONDS) >= FULL_FROM_SECONDS
    concept = _ask(client, [{"role": "system", "content": load("graph-concept")},
                            {"role": "user", "content": f"Topic: {topic}\n\nReturn the JSON now."}],
                   GraphConcept.model_validate)
    lesson, shown = build_run(concept, full)

    def narrated(answer: dict) -> dict:
        sentences, scenes = answer.get("sentences"), answer.get("scenes")
        by_code = [index for index, entry in enumerate(shown) if entry["the sentence must"] == "said by code"]
        if isinstance(sentences, list) and len(sentences) == len(shown) - len(by_code):
            # the steps code speaks were left out rather than given as "": code knows where they go
            # (live 2026-11-22 a good narration was refused three times for this alone)
            given = iter(sentences)
            sentences = ["" if index in by_code else next(given) for index in range(len(shown))]
            answer = {**answer, "sentences": sentences}
        if not isinstance(sentences, list) or len(sentences) != len(shown):
            raise ValueError(f"give exactly {len(shown)} sentences, one for each step, in order")
        if not isinstance(scenes, list) or len(scenes) != len(lesson["scenes"]):
            raise ValueError(f"give exactly {len(lesson['scenes'])} scenes, each with a title and a takeaway")
        long = [(index + 1, entry["at most words"]) for index, (text, entry) in enumerate(zip(sentences, shown))
                if len(str(text).split()) > entry.get("at most words", WORDS_ONE)]
        if long:
            raise ValueError("; ".join(f"step {number} runs past {limit} words" for number, limit in long)
                             + "; say it in fewer words")
        missing = [index + 1 for index, (text, entry) in enumerate(zip(sentences, shown))
                   if entry["the sentence must"] != "said by code" and not str(text).strip()]
        if missing:
            raise ValueError(f"step(s) {missing} have no sentence")
        unsaid = [index + 1 for index, (text, entry) in enumerate(zip(sentences, shown))
                  if "{taken}" in entry["the sentence must"] and "{taken}" not in str(text)]
        if unsaid:
            raise ValueError(f"step {unsaid[0]} must say the count as the slot {{taken}}, which code "
                             "fills in with the number on screen, such as 'it took {taken} rooms'")
        # A name is read by what is written: "c" is not the room C, and a lower-case "a" is the
        # article. Live 2026-11-22 the model, told not to open on "A", wrote every room in lower case.
        lowered = [(index + 1, node) for index, text in enumerate(sentences) for node in concept.graph.nodes
                   if node.lower() not in ("a", "i") and node.lower() != node
                   and re.search(rf"(?<![\w'’-]){re.escape(node.lower())}(?![\w'’-])", str(text))]
        if lowered:
            step_no, node = lowered[0]
            raise ValueError(f"step {step_no} writes the node {node!r} as {node.lower()!r}; write every "
                             f"node name exactly as shown, in capitals: {', '.join(concept.graph.nodes)}")
        # a sentence opening on the node "A" is read as the article "a" (narration/tts.py)
        opening = [(index + 1, name) for index, text in enumerate(sentences)
                   if (name := opens_on_name(str(text), set(concept.graph.nodes)))]
        if opening:
            step_no, name = opening[0]
            raise ValueError(f"step {step_no} starts a sentence with the node {name!r}, which the voice "
                             f"reads as the word 'a'; start it another way, such as 'Room {name} ...'")
        return answer

    told = _ask(client, [
        {"role": "system", "content": load("graph-narration")},
        {"role": "user", "content": f"The teaching: {json.dumps(concept.brief.model_dump(exclude_none=True), ensure_ascii=False)}\n\n"
                                    f"The steps:\n{json.dumps(shown, ensure_ascii=False, indent=1)}\n\n"
                                    "Return the JSON now."}], narrated)
    sentences = iter(told["sentences"])
    for scene, written in zip(lesson["scenes"], told["scenes"]):
        scene["title"] = str(written.get("title") or scene["title"])[:60]
        if written.get("takeaway"):
            scene["takeaway"] = str(written["takeaway"])[:80]
        for beat in scene["beats"]:
            beat["spoken_text"] = str(next(sentences)).strip() or "."
    data = lesson_trace.fill_trace_lesson(lesson)
    plan = LessonPlan.model_validate({**data, "topic": topic, "skill_id": skill.id, "schema_version": 2})
    lesson_trace.plan_trace_scenes(plan, skill)        # compiled and checked like any trace lesson
    return plan
