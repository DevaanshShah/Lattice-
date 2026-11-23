"""A breadth-first search lesson on the trace: the model names the graph and the moves; code runs
the search, so the node taken, the queue and the path on screen are always what BFS does."""
import copy

import pytest
from pydantic import ValidationError

from core.schemas.lesson_plan import LessonPlan
from planner.lesson_trace import fill_trace_lesson, plan_trace_scenes
from planner.product_recipe import load_recipes
from verification.visual_plan_validation import validate

SKILL = load_recipes()["algorithm_explainer"]
NODES = ["S", "A", "B", "C", "G", "D"]
EDGES = [["S", "A"], ["A", "B"], ["B", "G"], ["S", "C"], ["C", "G"], ["C", "D"]]
ANSWER = {
    "brief": {"learner": "A beginner who knows lists.", "can_do": "Trace breadth-first search on a maze.",
              "question": "How does a search find the shortest way out of a maze?",
              "problem": "Get from S to G in a small maze in the fewest steps.",
              "turning_point": "Take rooms in the order they were found, nearest first."},
    "trace": {"data": [
        {"id": "maze", "kind": "graph", "label": "The maze", "nodes": NODES, "edges": EDGES,
         "source": "S", "goal": "G", "order": "bfs"},
        {"id": "taken", "kind": "counter", "label": "Rooms taken", "counts": "maze"}]},
    "scenes": [
        {"title": "The maze", "learning_goal": "See the maze.", "beats": [
            {"spoken_text": "Here is a small maze of six rooms, starting at S.", "move": {"do": "show", "items": ["maze"]}},
            {"spoken_text": "We start at S, and S adds its neighbours A and C to the queue.", "move": {"do": "explore", "graph": "maze"}},
            {"spoken_text": "A comes out first and adds B; then C adds G and D.", "move": {"do": "explore", "graph": "maze", "count": 2}},
        ]},
        {"title": "The way out", "learning_goal": "Find the path.", "beats": [
            {"spoken_text": "B comes out next, then G: the goal is taken.", "move": {"do": "explore", "graph": "maze", "count": 2}},
            {"spoken_text": "Following each room back to where it was found gives S, C, G.", "move": {"do": "found", "graph": "maze"}},
        ]},
    ]}


def _lesson(answer: dict) -> LessonPlan:
    data = fill_trace_lesson(copy.deepcopy(answer))
    return LessonPlan.model_validate({**data, "schema_version": 2, "topic": "t", "skill_id": SKILL.id})


@pytest.mark.unit
def test_a_bfs_lesson_compiles_and_the_screen_follows_the_search():
    from core.schemas.browser_visual_plan import BrowserVisualPlan
    from core.visual_state import closing_state

    lesson = _lesson(ANSWER)
    scenes = plan_trace_scenes(lesson, SKILL)
    validate(lesson, BrowserVisualPlan(schema_version=2, topic="t", skill_id=SKILL.id, scenes=scenes), SKILL)
    first = closing_state(scenes[0])
    graph = first.payloads["maze"]
    assert (graph["visited"], graph["current"], graph["frontier"]) == (["S", "A"], "C", ["B", "G", "D"])
    assert first.payloads["taken"]["value"] == 3
    last = closing_state(scenes[1], first).payloads["maze"]
    assert last["path"] == ["S", "C", "G"]
    assert "Queue: B, G, D" in lesson.scenes[0].beats[2].visual_anchors


@pytest.mark.unit
def test_a_search_cannot_be_run_past_its_goal_or_found_early():
    too_far = copy.deepcopy(ANSWER)
    too_far["scenes"][1]["beats"][0]["move"]["count"] = 4
    with pytest.raises(ValueError, match="explore at most 2 more"):
        plan_trace_scenes(_lesson(too_far), SKILL)
    early = copy.deepcopy(ANSWER)
    early["scenes"][1]["beats"][0]["move"]["count"] = 1     # G not yet taken
    with pytest.raises(ValueError, match="only once the search has taken it"):
        plan_trace_scenes(_lesson(early), SKILL)


@pytest.mark.unit
def test_a_graph_that_cannot_be_searched_is_refused():
    broken = copy.deepcopy(ANSWER)
    broken["trace"]["data"][0]["goal"] = "Z"
    with pytest.raises(ValidationError, match="'Z' is not a node"):
        _lesson(broken)


class _Scripted:
    def __init__(self, answers):
        import json
        self.answers, self.asked = [json.dumps(answer) for answer in answers], []

    def chat(self, messages, **_):
        self.asked.append(list(messages))
        return self.answers.pop(0)


CONCEPT = {
    "brief": {"learner": "A beginner who knows lists.", "can_do": "Trace breadth-first search on a maze.",
              "question": "How does a search find the shortest way out of a maze?",
              "problem": "Get from the entrance S to the exit G of a six-room maze.",
              "turning_point": "Take rooms in the order they were found, nearest first.",
              "catch": "It must remember every room it has found."},
    "graph": {"label": "The maze", "means": "a node is a room, a line is a doorway", "nodes": NODES,
              "edges": EDGES, "source": "S", "goal": "G", "order": "bfs", "name": "breadth-first search"}}


def _said(shown):
    """One sentence for each step, as a model writes them; the catch says the count as {taken}."""
    return [("It took {taken} rooms." if "{taken}" in entry["the sentence must"]
             else f"Sentence {n} explains it.") for n, entry in enumerate(shown, 1)]


@pytest.mark.unit
def test_a_maze_topic_is_planned_in_steps_and_code_runs_the_search():
    """2026-11-22: 'How breadth-first search finds the shortest path in a maze' failed five tries
    live, the model asking for a queue the board could not draw. Now the model names the graph,
    code runs BFS, and the model writes one sentence per step."""
    from planner import lesson_plan
    from planner.lesson_graph import build_run

    skill = load_recipes()["graph_explainer"]
    _, shown = build_run(__import__("planner.lesson_graph", fromlist=["GraphConcept"]).GraphConcept.model_validate(CONCEPT))
    narration = {"scenes": [{"title": f"Part {n}", "takeaway": "A point."} for n in (1, 2, 3, 4)],
                 "sentences": _said(shown)}
    client = _Scripted([CONCEPT, narration])
    plan = lesson_plan.generate("BFS shortest path in a maze", skill, client=client, schema_version=2)
    assert len(client.asked) == 2
    moves = [beat.move.do for scene in plan.scenes for beat in scene.beats]
    assert moves[:3] == ["show", "ask", "turn"] and "found" in moves
    assert sum(beat.move.count for scene in plan.scenes for beat in scene.beats if beat.move.do == "explore") == 5
    steps = client.asked[1][1]["content"]
    assert "Queue: B, G, D" in steps and "S -> C -> G" in steps


@pytest.mark.unit
def test_a_graph_the_search_cannot_teach_on_is_sent_back_with_its_reason():
    from planner.lesson_graph import GraphConcept
    near = copy.deepcopy(CONCEPT)
    near["graph"]["edges"] = [["S", "G"], ["S", "A"], ["A", "B"], ["B", "C"], ["C", "D"]]
    with pytest.raises(ValueError, match="next to the start"):
        GraphConcept.model_validate(near)
    wide = copy.deepcopy(CONCEPT)
    wide["graph"]["nodes"][0] = "Start"
    with pytest.raises(ValueError, match="at most three characters"):
        GraphConcept.model_validate(wide)


@pytest.mark.unit
def test_a_turning_point_too_long_for_the_screen_is_sent_back_at_the_first_step():
    """Live 2026-11-22: a 126-character turning point was found only when the finished lesson was
    compiled, too late to repair; the BFS lesson was lost."""
    from planner.lesson_graph import GraphConcept
    long = copy.deepcopy(CONCEPT)
    long["brief"]["turning_point"] = "Take " + "rooms " * 25
    with pytest.raises(ValueError, match="at most 110 characters"):
        GraphConcept.model_validate(long)


@pytest.mark.unit
def test_a_sentence_opening_on_the_node_a_is_sent_back():
    """2026-11-22 BFS video: 'A comes out next' was read 'uh comes out next'. The voice reads a
    sentence-opening 'A' as the article, so a sentence may not open on that node."""
    from planner import lesson_plan
    from planner.lesson_graph import GraphConcept, build_run

    skill = load_recipes()["graph_explainer"]
    _, shown = build_run(GraphConcept.model_validate(CONCEPT))
    sentences = _said(shown)
    bad = {"scenes": [{"title": f"Part {n}", "takeaway": "A point."} for n in (1, 2, 3, 4)],
           "sentences": ["A comes out next."] + sentences[1:]}
    good = {**bad, "sentences": sentences}
    client = _Scripted([CONCEPT, bad, good])
    lesson_plan.generate("BFS shortest path in a maze", skill, client=client, schema_version=2)
    assert len(client.asked) == 3
    assert "starts a sentence with the node 'A'" in client.asked[2][-1]["content"]


@pytest.mark.unit
def test_node_names_written_in_lower_case_are_sent_back():
    """Live 2026-11-22: told not to open a sentence on 'A', the model wrote 'Room a ... adds c',
    and the voice read 'a' as the article again."""
    from planner import lesson_plan
    from planner.lesson_graph import GraphConcept, build_run

    skill = load_recipes()["graph_explainer"]
    _, shown = build_run(GraphConcept.model_validate(CONCEPT))
    sentences = _said(shown)
    bad = {"scenes": [{"title": f"Part {n}", "takeaway": "A point."} for n in (1, 2, 3, 4)],
           "sentences": ["Room a comes out next and adds c."] + sentences[1:]}
    good = {**bad, "sentences": ["Room A comes out next and adds C, a new room."] + sentences[1:]}
    client = _Scripted([CONCEPT, bad, good])
    lesson_plan.generate("BFS shortest path in a maze", skill, client=client, schema_version=2)
    assert len(client.asked) == 3
    assert "writes the node 'C' as 'c'" in client.asked[2][-1]["content"]


@pytest.mark.unit
def test_a_narration_that_leaves_out_the_steps_code_speaks_is_placed_by_code():
    """Live 2026-11-22: the model gave one sentence for each step it had to write and left out the
    two that code says; the lesson was refused three times and lost."""
    from planner import lesson_plan
    from planner.lesson_graph import GraphConcept, build_run

    skill = load_recipes()["graph_explainer"]
    _, shown = build_run(GraphConcept.model_validate(CONCEPT))
    written = [said for said, entry in zip(_said(shown), shown) if entry["the sentence must"] != "said by code"]
    narration = {"scenes": [{"title": f"Part {n}", "takeaway": "A point."} for n in (1, 2, 3, 4)],
                 "sentences": written}
    client = _Scripted([CONCEPT, narration])
    plan = lesson_plan.generate("BFS shortest path in a maze", skill, client=client, schema_version=2)
    assert len(client.asked) == 2
    beats = [beat for scene in plan.scenes for beat in scene.beats]
    assert beats[0].spoken_text == "Sentence 1 explains it."
    assert beats[3].spoken_text == "Sentence 4 explains it."      # after the ask and the turn


@pytest.mark.unit
def test_the_steps_that_must_say_several_things_get_more_words():
    """Live 2026-11-22: the opening and the path, each asked for two or three things, were refused
    three times at forty words."""
    from planner.lesson_graph import WORDS_ONE, WORDS_SEVERAL, GraphConcept, build_run

    _, shown = build_run(GraphConcept.model_validate(CONCEPT))
    found = next(entry for entry in shown if "path is read back" in entry["the sentence must"])
    assert shown[0]["at most words"] == found["at most words"] == WORDS_SEVERAL
    one_node = [entry for entry in shown if entry["the sentence must"].startswith("Say which node comes out")]
    assert one_node and {entry["at most words"] for entry in one_node} == {WORDS_ONE}
    assert all("at most words" not in entry for entry in shown if entry["the sentence must"] == "said by code")


@pytest.mark.unit
def test_a_lesson_asked_for_no_length_is_a_full_one_and_a_short_target_is_compact():
    """The one-minute graph lessons of 2026-11-22 were 'really short'. No target is a full lesson:
    every node on its own beat, then the catch and the uses in a closing scene."""
    from planner.lesson_graph import GraphConcept, build_run

    concept = GraphConcept.model_validate({**CONCEPT, "uses": "Maps use it for fewest-stops routes."})
    full, shown = build_run(concept)
    short, compact = build_run(concept, full=False)
    moves = lambda lesson: [beat["move"] for scene in lesson["scenes"] for beat in scene["beats"]]
    assert len(full["scenes"]) == 4 and len(short["scenes"]) == 3
    assert all(move.get("count", 1) == 1 for move in moves(full) if move["do"] == "explore")
    assert any(move.get("count") == 2 for move in moves(short) if move["do"] == "explore")
    assert [move["do"] for move in moves(full)][-3:] == ["found", "count", "show"]
    assert len(shown) >= len(compact) + 3
    assert "{taken}" in shown[-2]["the sentence must"]          # the catch says the count as the screen shows it


def _seek(browser, html, seconds):
    page = browser.new_page(viewport={"width": 1920, "height": 1080})     # a fresh page: the plan is a const
    page.set_content(html)
    page.evaluate("window.animationReady()")
    page.evaluate(f"window.seekAnimation({seconds})")
    return page.evaluate("""() => [...document.querySelectorAll('.graph-walker,.graph-scout')].map(d => ({
        kind: d.classList.contains('graph-walker') ? 'walker' : 'scout',
        x: new DOMMatrix(getComputedStyle(d).transform).e,
        opacity: +getComputedStyle(d).opacity}))""")


@pytest.mark.integration
def test_the_search_moves_dots_to_the_rooms_found_and_a_walker_along_the_path():
    """Owner review, 2026-11-22: KodeKloud's picture moves; ours only changed colour. When S is
    taken a dot runs to each room it finds (A and C); when the path is found a walker goes from
    S to G and fades on arrival."""
    from playwright.sync_api import sync_playwright
    from composition.slides import chrome_path
    from core.visual_state import closing_state
    from generation.browser_scene import CAPTURE_ARGS, animation_html

    scenes = plan_trace_scenes(_lesson(ANSWER), SKILL)
    first, second = scenes
    explore = first.beats[1]
    taking = next(index for index, action in enumerate(explore.actions) if action.kind == "set_state"
                  and action.target_ids == ["maze"])
    start, end = explore.timeline(6.0)[taking]
    walk = second.beats[1]
    path_at = next(index for index, action in enumerate(walk.actions) if action.params.get("path"))
    walk_start, walk_end = walk.timeline(8.0)[path_at]
    before_explore = closing_state(first.model_copy(update={"beats": first.beats[:1]}), None)
    before_walk = closing_state(second.model_copy(update={"beats": second.beats[:1]}), closing_state(first))
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=chrome_path(), args=CAPTURE_ARGS)
        explore_html = animation_html(first, explore, title="t", opening=before_explore, duration=6.0)
        scouts = [d for d in _seek(browser, explore_html, start + .7) if d["kind"] == "scout"]
        assert len(scouts) == 2 and all(d["opacity"] > .5 for d in scouts)
        walk_html = animation_html(second, walk, title="t", opening=before_walk, duration=8.0)
        early = [d for d in _seek(browser, walk_html, walk_start + .2) if d["kind"] == "walker"]
        later = [d for d in _seek(browser, walk_html, walk_start + 1.0) if d["kind"] == "walker"]
        gone = [d for d in _seek(browser, walk_html, walk_start + 1.75) if d["kind"] == "walker"]
        browser.close()
    assert early and later and later[0]["x"] > early[0]["x"] + 20       # it walks toward the goal
    assert gone[0]["opacity"] < .2                                       # and fades there
