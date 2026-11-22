"""Judgements code cannot make, asked of Jev: typed yes/no questions with a probability.

Code owns every number of a lesson; a model writes the sentences. What neither checks is whether
a sentence says only what its step shows, and whether it gives the reason it was asked to give.
Those are judgements, so they are asked of Jev, one request for the whole narration. Jev being
unavailable never stops a lesson: a gate that cannot be asked passes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable
from urllib.request import Request, urlopen

from core.config import settings

SUPPORTED = 0.4     # measured 2026-10-15: catches 65% of bad sentences, flags 6% of good ones
EXPLAINED = 0.3     # measured 2026-10-15: catches 83% of reasons removed, flags 15% of good ones


@dataclass(frozen=True)
class SentenceVerdict:
    step: int                   # counted from 1, as the narration step numbers them
    supported: float            # probability the sentence says only what the step shows
    explained: float | None     # probability it gives the reason, for steps that must


def ask(state: dict, questions: dict, *, open_url: Callable | None = None,
        timeout: float | None = None) -> dict | None:
    """One Jev request. Returns its answers, or None when Jev is off, unreachable or odd."""
    if not settings.jev_enabled or not settings.jev_api_key:
        return None
    body = json.dumps({"model": settings.jev_model, "state": state, "questions": questions}).encode("utf-8")
    request = Request(settings.jev_base_url, data=body, method="POST", headers={
        "Authorization": f"Bearer {settings.jev_api_key}", "Content-Type": "application/json"})
    try:
        with (open_url or urlopen)(request, timeout=timeout or settings.jev_timeout_s) as response:
            answers = json.loads(response.read().decode("utf-8"))["answers"]
    except (KeyError, TypeError, ValueError, OSError):
        return None
    return answers if isinstance(answers, dict) else None


def _probability(answer) -> float | None:
    value = answer.get("noul") if isinstance(answer, dict) else None
    return float(value) if isinstance(value, (int, float)) and 0 <= value <= 1 else None


def judge_narration(steps: list[dict], sentences: list[str], *, open_url: Callable | None = None) -> list[SentenceVerdict]:
    """Ask, for every sentence the model wrote, whether it says only what its step shows, and,
    where the step asks for a reason, whether it gives one. Empty when Jev cannot be asked."""
    state, questions = {"steps": []}, {}
    for index, (step, sentence) in enumerate(zip(steps, sentences)):
        if step["the sentence must"] == "said by code" or not str(sentence).strip():
            continue
        state["steps"].append({"step": index + 1, "shown": step["the viewer sees"],
                               "asked": step["the sentence must"], "sentence": sentence})
        at = len(state["steps"]) - 1
        questions[f"supported_{index + 1}"] = {
            "type": "noul",
            "instructions": (f"Every number, item and claim in `steps[{at}].sentence` is shown in "
                             f"`steps[{at}].shown` or follows directly from it; it states nothing "
                             "that contradicts it and no number that is not there."),
            "criteria": {"true": "Everything the sentence says is shown or follows from what is shown",
                         "false": "It states a number, case, or claim that is not shown or is contradicted"}}
        if "why" in step["the sentence must"].lower() or "reason" in step["the sentence must"].lower():
            questions[f"explained_{index + 1}"] = {
                "type": "noul",
                "instructions": (f"`steps[{at}].sentence` gives the reason that `steps[{at}].asked` "
                                 "asks for: it says why the step is true, not only what happens."),
                "criteria": {"true": "It gives the reason, such as 'because' or 'so' followed by why",
                             "false": "It only says what happens, or gives no reason"}}
    if not questions:
        return []
    answers = ask(state, questions, open_url=open_url)
    if answers is None:
        return []
    verdicts = []
    for entry in state["steps"]:
        number = entry["step"]
        supported = _probability(answers.get(f"supported_{number}"))
        if supported is None:
            continue
        verdicts.append(SentenceVerdict(number, supported, _probability(answers.get(f"explained_{number}"))))
    return verdicts


def weak_sentences(verdicts: list[SentenceVerdict]) -> str:
    """Why sentences go back to be rewritten, in words the narration step can act on."""
    unsupported = [v.step for v in verdicts if v.supported < SUPPORTED]
    unexplained = [v.step for v in verdicts if v.explained is not None and v.explained < EXPLAINED]
    faults = []
    if unsupported:
        faults.append(f"sentence(s) {unsupported} say something their step does not show; use only "
                      "the numbers and cases given for that step")
    if unexplained:
        faults.append(f"sentence(s) {unexplained} say what happens but not why; give the reason the "
                      "step asks for")
    return "; ".join(faults)


def instance_matches_topic(topic: str, problem: str, *, open_url: Callable | None = None) -> float | None:
    """The probability that the lesson's worked instance is the one the topic asks about."""
    answers = ask({"topic": topic, "instance": problem}, {"same": {
        "type": "noul",
        "instructions": ("`instance` is the problem `topic` asks about, with the same numbers: the "
                         "same size, amounts and choices wherever `topic` gives them."),
        "criteria": {"true": "Same problem and the same numbers wherever the topic states them",
                     "false": "A different problem, or different numbers from the ones the topic states"}}},
        open_url=open_url)
    return _probability(answers.get("same")) if answers else None
