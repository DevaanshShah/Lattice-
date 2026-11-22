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

from pydantic import BaseModel, ConfigDict, Field

from core.graph_search import frontier_line, problems, search
from core.llm import LLMClient, get_client
from core.schemas.lesson_plan import LINE_LENGTH, LessonBrief, LessonPlan
from planner import lesson_trace
from planner.lesson_recurrence import _ask
from planner.product_recipe import Recipe
from prompts.loader import load


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


class GraphConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: LessonBrief
    graph: GraphSpec

    def model_post_init(self, _) -> None:
        # the turning point is shown on screen; found here, it is repaired with the rest of the brief
        if len(self.brief.turning_point) > LINE_LENGTH:
            raise ValueError(f"brief.turning_point is shown on screen: at most {LINE_LENGTH} "
                             f"characters, not {len(self.brief.turning_point)}; say it in fewer words")


def build_run(concept: GraphConcept) -> tuple[dict, list[dict]]:
    """The whole lesson as code decides it, and the steps the narration step is shown."""
    graph, brief = concept.graph, concept.brief
    found = search(graph.nodes, graph.edges, graph.source, graph.goal, graph.order)
    trace = {"data": [
        {"id": "graph", "kind": "graph", "label": graph.label, "nodes": graph.nodes,
         "edges": graph.edges, "source": graph.source, "goal": graph.goal, "order": graph.order},
        {"id": "taken", "kind": "counter", "label": "Taken so far", "counts": "graph"}]}
    waiting = "queue" if graph.order == "bfs" else "stack"
    steps: list[tuple[int, dict, str, str]] = []

    def step(scene: int, move: dict, sees: str, explain: str) -> None:
        steps.append((scene, move, sees, explain))

    step(0, {"do": "show", "items": ["graph"]},
         f"the graph '{graph.label}': nodes {', '.join(graph.nodes)}; {graph.means}; the search "
         f"starts at {graph.source} and looks for {graph.goal}",
         f"State the problem ({brief.problem}) and say what a node and a line stand for.")
    step(0, {"do": "ask"}, f"the question on screen: {brief.question}", "said by code")
    step(1, {"do": "turn"}, f"the idea on screen: {brief.turning_point}", "said by code")
    # one node per step while the rule is new, then two at a time
    taken, index = 0, 0
    while taken < len(found["steps"]):
        count = 1 if index < 3 else min(2, len(found["steps"]) - taken)
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
    step(2, {"do": "found", "graph": "graph"},
         f"the path found is drawn: {' -> '.join(found['path'])}, {len(found['path']) - 1} edges",
         "Say how the path is read back from where each node was first found, and how long it is"
         + (", and why breadth-first search makes it the shortest." if graph.order == "bfs"
            else ", and that depth-first search does not promise the shortest."))
    titles = ("The problem", "The search", "The way through")
    scenes = [{"title": title, "learning_goal": title,
               "beats": [{"move": move, "spoken_text": ""} for scene, move, _, _ in steps if scene == number]}
              for number, title in enumerate(titles)]
    lesson = {"brief": brief.model_dump(exclude_none=True), "trace": trace, "scenes": scenes}
    shown = [{"step": index + 1, "scene": scene + 1, "the viewer sees": sees, "the sentence must": explain}
             for index, (scene, _, sees, explain) in enumerate(steps)]
    return lesson, shown


def generate(topic: str, skill: Recipe, *, client: LLMClient | None = None) -> LessonPlan:
    """Plan a graph-search lesson in two model calls with code between them."""
    client = client or get_client()
    concept = _ask(client, [{"role": "system", "content": load("graph-concept")},
                            {"role": "user", "content": f"Topic: {topic}\n\nReturn the JSON now."}],
                   GraphConcept.model_validate)
    lesson, shown = build_run(concept)

    def narrated(answer: dict) -> dict:
        sentences, scenes = answer.get("sentences"), answer.get("scenes")
        if not isinstance(sentences, list) or len(sentences) != len(shown):
            raise ValueError(f"give exactly {len(shown)} sentences, one for each step, in order")
        if not isinstance(scenes, list) or len(scenes) != len(lesson["scenes"]):
            raise ValueError(f"give exactly {len(lesson['scenes'])} scenes, each with a title and a takeaway")
        long = [index + 1 for index, text in enumerate(sentences) if len(str(text).split()) > 40]
        if long:
            raise ValueError(f"sentence(s) {long} run past forty words; say one thing in each")
        missing = [index + 1 for index, (text, entry) in enumerate(zip(sentences, shown))
                   if entry["the sentence must"] != "said by code" and not str(text).strip()]
        if missing:
            raise ValueError(f"step(s) {missing} have no sentence")
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
