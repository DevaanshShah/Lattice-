"""A recurrence-table lesson planned in three steps, so that no model writes a move.

One call was being asked to design the teaching, declare the data, pick every move and obey
some forty rules it could not check for itself, and both a cheap and a strong model failed it
more often than not. Here the work is split by who can do it:

1. A model decides the teaching and describes the table (`ConceptSpec`): the brief, the rule,
   the cases of the instance and how they split. Code checks that description against itself,
   which it can: the last cell is the answer, there are as many cases as the answer, and each
   group of cases is as large as the earlier cell it stands for.
2. Code builds the whole run from it: every step, in order, with the numbers it shows.
3. A model is shown that run and writes one sentence for each step.

The lesson that comes out is an ordinary trace lesson, compiled and checked like any other.
A pilot for one family of lessons; nothing routes to it yet.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from core.llm import LLMClient, get_client
from core.schemas.lesson_plan import LessonBrief, LessonPlan, TableRule
from core.textutil import extract_json
from planner import jev_gates, lesson_trace
from planner.lesson_plan import JSON_ONLY, PLAN_EXTRA, TRANSPORT_ATTEMPTS, LessonPlanError
from planner.lesson_shared import number
from planner.product_recipe import Recipe
from prompts.loader import load

ATTEMPTS = 3        # tries for each of the two model steps; each is small and says what was wrong
SAME_INSTANCE = 0.3     # below this, the judge is taken to say the instance is not the topic's


class TableSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(..., min_length=1, max_length=22)
    unit: str = Field(..., min_length=1, max_length=16)
    first: int = Field(default=0, ge=0, le=1)
    size: int = Field(..., ge=3, le=12)
    start: list[int | float] = Field(..., min_length=1, max_length=6)
    back: list[int] = Field(..., min_length=1, max_length=4)
    op: str
    plus: float = 0

    def values(self) -> list[tuple]:
        """Every cell: what it holds and the cells it reads, worked out from the rule."""
        rule = TableRule(start=self.start, back=self.back, op=self.op, plus=self.plus)
        table: list[tuple] = []
        for cell in range(self.size):
            reads = [] if cell < len(rule.start) else [cell - step for step in rule.back if step <= cell]
            held = (rule.start[cell] if not reads else
                    {"sum": sum, "min": min, "max": max}[rule.op]([table[i][0] for i in reads]) + rule.plus)
            table.append((number(held), reads))
        return table


class CaseGroup(BaseModel):
    """Cases that belong together because they end the same way. The model says how they end;
    code finds which cases those are, so a case cannot be put in the wrong group."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=24)
    ends: str = Field(..., min_length=1, max_length=9)
    cells: list[int] = Field(default_factory=list)      # worked out from `ends`, never given


class CasesSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(..., min_length=1, max_length=22)
    items: list[str] = Field(..., min_length=2, max_length=12)
    groups: list[CaseGroup] = Field(..., min_length=2, max_length=3)


class TeachingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: TableSpec
    cases: CasesSpec
    name: str = Field(..., min_length=1, max_length=40)


class ConceptSpec(BaseModel):
    """What the teaching step returns: the brief, and a description of the table small enough
    for code to check against itself."""
    model_config = ConfigDict(extra="forbid")
    brief: LessonBrief
    spec: TeachingSpec

    @model_validator(mode="after")
    def _the_cases_show_the_rule(self) -> "ConceptSpec":
        table, cases = self.spec.table, self.spec.cases
        if len(table.start) >= table.size:
            raise ValueError("every cell of the table is given: make the table long enough for the "
                             "rule to work at least one cell out")
        whole = table.values()
        answer, reads = whole[-1]
        last = table.first + table.size - 1
        facts = ", ".join(f"cell {index + table.first} holds {value}" for index, (value, _) in enumerate(whole))
        wide = [item for item in cases.items if len(item) > 9 or " " in item]
        if wide:
            raise ValueError(f"the case {wide[0]!r} does not fit in a box: at most nine characters, no spaces")
        if len(cases.items) != answer:
            # A live run answered "exactly 5" by cutting cases, then the table, three times over.
            # Listed cases are concrete and easy to check; a table's start is where slips happen.
            raise ValueError(f"the table's last cell, cell {last}, holds {answer}, but {len(cases.items)} "
                             f"cases are listed. The table comes to: {facts}. Check the cases first: if "
                             f"all {len(cases.items)} are right and none is missing, the table is wrong, "
                             "so fix its \"start\" (the simply known first cells, counted from cell "
                             f"{table.first}) so that its last cell holds {len(cases.items)}; keep the "
                             "instance the same size")
        for group in cases.groups:
            group.cells = [index for index, item in enumerate(cases.items) if item.endswith(group.ends)]
        for index, item in enumerate(cases.items):
            homes = [group.ends for group in cases.groups if index in group.cells]
            if len(homes) != 1:
                raise ValueError(f"the case {item!r} ends like {homes or 'none'} of the groups; every "
                                 "case must end like exactly one group's \"ends\"")
        wanted = sorted(whole[index][0] for index in reads)
        if any(not group.cells for group in cases.groups):
            raise ValueError("a group has no case that ends that way")
        if sorted(len(group.cells) for group in cases.groups) != wanted:
            raise ValueError(
                f"cell {last} is worked out from cells {[index + table.first for index in reads]}, "
                f"which hold {[whole[index][0] for index in reads]}, so the groups have {wanted} "
                f"cases; yours have {sorted(len(group.cells) for group in cases.groups)}. Either a "
                "case is missing or wrong, or the groups are not split by the last choice made")
        return self


def bigger_instance(table: TableSpec, steps: int = 15) -> tuple[int, int] | None:
    """The same rule run on a bigger instance: how big, and what its last cell holds. Only for a
    table that counts cases (a sum), where that number is how many cases a list would need."""
    if table.op != "sum" or table.plus:
        return None
    longer = table.model_copy(update={"size": table.size + steps})
    values = longer.values()
    return table.first + longer.size - 1, int(values[-1][0])


def build_run(concept: ConceptSpec) -> tuple[dict, list[dict]]:
    """The whole lesson as code decides it: the trace, and every step in order with what it
    shows and what its sentence has to explain. Returns the lesson as a model would have
    written it, sentences still empty, and the steps the narration step is shown."""
    table, cases, brief = concept.spec.table, concept.spec.cases, concept.brief
    whole = table.values()
    base, given, last = table.first, len(table.start), table.size - 1
    unit, held = table.unit, lambda cell: whole[cell][0]
    trace = {"data": [
        # two cases are shown as examples and the rest held back, so the answer is not on
        # screen before the question is asked
        {"id": "cases", "kind": "array", "label": cases.label, "items": list(cases.items),
         "shown_at_first": 2, "numbered": False},
        {"id": "table", "kind": "array", "label": table.label, "size": table.size, "first": base,
         "rule": {"start": table.start, "back": table.back, "op": table.op, "plus": table.plus}}]}

    def working(cell: int) -> str:
        return lesson_trace._worked_out(table.label, cell + base, TableRule(**trace["data"][1]["rule"]),
                                        [held(index) for index in whole[cell][1]], held(cell))

    steps: list[tuple[int, dict, str, str]] = []        # scene, move, what is seen, what to explain

    def step(scene: int, move: dict, sees: str, explain: str) -> None:
        steps.append((scene, move, sees, explain))

    step(0, {"do": "show", "items": ["cases"]},
         f"a row of boxes labelled '{cases.label}': the first two show {cases.items[0]} and "
         f"{cases.items[1]}, the others show only '?'",
         f"State the problem ({brief.problem}), say what one box holds using the two examples, "
         "and say there are more. Do not say how many.")
    step(0, {"do": "ask"}, f"the question on screen: {brief.question}", "said by code")
    step(0, {"do": "reveal", "array": "cases"},
         f"every case is now shown: {', '.join(cases.items)}",
         f"Listing every case by hand is the first thing anyone tries, and here it finds "
         f"{len(cases.items)}. Say why that cannot be trusted as the number of {unit} grows.")
    step(1, {"do": "turn"}, f"the turning point on screen: {brief.turning_point}", "said by code")
    for group in cases.groups:
        step(1, {"do": "group", "array": "cases", "cells": list(group.cells), "text": group.name,
                 "ends": group.ends},
             f"{len(group.cells)} of the boxes take one colour, named '{group.name}', and the last "
             f"part '{group.ends}' of each is struck through, leaving: "
             f"{', '.join(cases.items[cell][:-len(group.ends)] for cell in group.cells)}",
             f"Say what these {len(group.cells)} cases have in common, and why that makes each of "
             f"them a case of a smaller problem, of which there are {len(group.cells)}.")
    known = [cell + base for cell in range(given)]
    step(2, {"do": "show", "items": ["table"]},
         f"an empty table '{table.label}' of {table.size} boxes numbered {base} to {last + base}",
         f"Say what one box of the table holds: the answer for that many {unit}.")
    step(2, {"do": "fill", "array": "table", "cells": known, "expect": [held(cell) for cell in range(given)]}
         if given > 1 else {"do": "fill", "array": "table", "cell": known[0], "expect": held(0)},
         "the first boxes are filled: " + ", ".join(f"box {cell + base} = {held(cell)}" for cell in range(given)),
         "Say why these are simply known, with no working.")
    step(2, {"do": "fill", "array": "table", "cell": given + base, "expect": held(given)},
         f"box {given + base} is filled from the boxes it reads: {working(given)}",
         "Give the rule in words on this one box: which boxes it reads, and why adding them is right.")
    middle = list(range(given + 1, last))
    # which group of cases each cell the answer reads stands for: the group of the same size
    sizes = {group.name: len(group.cells) for group in cases.groups}
    matched = []
    for cell in whole[last][1]:
        name = next(name for name, size in sizes.items() if size == held(cell) and name not in matched)
        matched.append(name)
    if middle:
        step(3, {"do": "fill", "array": "table", "cells": [cell + base for cell in middle],
                 "expect": [held(cell) for cell in middle]},
             "the next boxes are filled the same way: " + "; ".join(working(cell) for cell in middle),
             "Say the same rule carries on, and read out the numbers it gives.")
    step(3, {"do": "fill", "array": "table", "cell": last + base, "expect": held(last), "match": matched},
         f"the last box is filled: {working(last)}. The boxes it reads take the colours of the "
         f"groups they stand for: " + ", ".join(f"box {cell + base} ({held(cell)}) = '{name}'"
                                                for cell, name in zip(whole[last][1], matched))
         + f". It matches the {len(cases.items)} cases listed at the start.",
         f"This is the answer to the question. Say which boxes it uses, that the answer is "
         f"{held(last)}, and that it matches the {len(cases.items)} cases listed by hand.")
    big = bigger_instance(table)
    if big is not None:
        size, cases_there = big
        trace["data"] += [
            {"id": "list_cost", "kind": "value", "label": f"Cases for {size} {unit}"[:22], "value": cases_there},
            {"id": "table_cost", "kind": "value", "label": f"Boxes for {size} {unit}"[:22],
             "value": size - table.first + 1}]
        step(3, {"do": "show", "items": ["list_cost", "table_cost"]},
             f"two numbers come on: listing every case for {size} {unit} means {cases_there} cases; "
             f"the table needs {size - table.first + 1} boxes",
             f"Say what was done: each answer was written down once and later answers were built "
             f"from earlier ones, which is called {concept.spec.name}. Then compare the two numbers "
             f"shown: {cases_there} cases to list against {size - table.first + 1} boxes to fill.")
    else:
        step(3, {"do": "show", "items": ["table"]}, "the finished table, lit",
             f"Say what was done: each answer was written down once and later answers were built from "
             f"earlier ones, and that this is called {concept.spec.name}. Then say the table needs one "
             f"more box for one more of the {unit}, while the list of cases keeps multiplying. Give no "
             "numbers for that.")

    scenes = []
    for number_of, title in enumerate(("The problem", "The reason", "The table", "The answer")):
        scenes.append({"title": title, "learning_goal": title, "beats": [
            {"move": move, "spoken_text": ""} for scene, move, _, _ in steps if scene == number_of]})
    lesson = {"brief": brief.model_dump(), "trace": trace, "scenes": scenes}
    shown = [{"step": index + 1, "scene": scene + 1, "the viewer sees": sees,
              "the sentence must": explain} for index, (scene, _, sees, explain) in enumerate(steps)]
    return lesson, shown


def _ask(client: LLMClient, messages: list[dict], check, attempts: int = ATTEMPTS):
    """One small model step: its answer is checked, and a fault goes back with its reason."""
    last: Exception | None = None
    asked = list(messages)
    for _ in range(attempts):
        raw = client.chat(messages, max_tokens=2500, attempts=TRANSPORT_ATTEMPTS, timeout=60.0,
                          response_format=JSON_ONLY, extra_body=PLAN_EXTRA)
        try:
            return check(extract_json(raw))
        except (ValueError, ValidationError) as fault:
            last = fault
            reason = ("; ".join(error["msg"].removeprefix("Value error, ") for error in fault.errors())
                      if isinstance(fault, ValidationError) else str(fault))
            messages = asked + [{"role": "assistant", "content": raw},
                                {"role": "user", "content": f"That was invalid ({reason}). Change only "
                                                            "that and return the whole JSON again."}]
    raise LessonPlanError(f"this step failed after {attempts} attempts: {last}")


def generate(topic: str, skill: Recipe, *, client: LLMClient | None = None) -> LessonPlan:
    """Plan a recurrence-table lesson in two model calls with code between them."""
    import json

    client = client or get_client()
    def described(answer: dict) -> ConceptSpec:
        concept = ConceptSpec.model_validate(answer)
        # Whether the worked instance is the one the topic asks about is a judgement code cannot
        # make; Jev is asked once, and a clear no goes back like any other fault.
        same = jev_gates.instance_matches_topic(topic, concept.brief.problem)
        if same is not None and same < SAME_INSTANCE:
            raise ValueError("the instance in brief.problem is not the one the topic asks about; "
                             "use the topic's own numbers")
        return concept

    concept = _ask(client, [{"role": "system", "content": load("recurrence-concept")},
                            {"role": "user", "content": f"Topic: {topic}\n\nReturn the JSON now."}],
                   described)
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
        {"role": "system", "content": load("recurrence-narration")},
        {"role": "user", "content": f"The teaching: {json.dumps(concept.brief.model_dump(), ensure_ascii=False)}\n\n"
                                    f"The steps:\n{json.dumps(shown, ensure_ascii=False, indent=1)}\n\n"
                                    "Return the JSON now."}], narrated)
    # Each sentence is judged against its step: does it say only what the step shows, and does it
    # give the reason the step asks for. Weak ones are rewritten once. The judge is right most of
    # the time, not always, so a second weak verdict never stops the lesson.
    faults = jev_gates.weak_sentences(jev_gates.judge_narration(shown, told["sentences"]))
    if faults:
        asked = [
            {"role": "system", "content": load("recurrence-narration")},
            {"role": "user", "content": f"The teaching: {json.dumps(concept.brief.model_dump(), ensure_ascii=False)}\n\n"
                                        f"The steps:\n{json.dumps(shown, ensure_ascii=False, indent=1)}\n\n"
                                        "Return the JSON now."},
            {"role": "assistant", "content": json.dumps(told, ensure_ascii=False)},
            {"role": "user", "content": f"Rewrite only these: {faults}. Keep every other sentence "
                                        "exactly as it was and return the whole JSON again."}]
        try:
            told = _ask(client, asked, narrated, attempts=1)
        except LessonPlanError:
            pass                    # the first narration stands
    sentences = iter(told["sentences"])
    for scene, written in zip(lesson["scenes"], told["scenes"]):
        scene["title"] = str(written.get("title") or scene["title"])[:60]
        if written.get("takeaway"):
            scene["takeaway"] = str(written["takeaway"])[:80]
        for beat in scene["beats"]:
            beat["spoken_text"] = str(next(sentences)).strip() or "."
    data = lesson_trace.fill_trace_lesson(lesson)
    plan = LessonPlan.model_validate({**data, "topic": topic, "skill_id": skill.id, "schema_version": 2})
    scenes = lesson_trace.plan_trace_scenes(plan, skill)        # compiled and checked like any trace lesson
    weak = lesson_trace.craft_trace(plan, scenes)
    if weak:
        raise LessonPlanError("the built lesson falls short: " + "; ".join(weak))
    return plan
