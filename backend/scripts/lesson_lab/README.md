# Lesson lab: plan, render and review a lesson by hand

Scripts used to develop the staged table lessons. Run them from the repo root with the project's
Python (`.venv/Scripts/python.exe`). Live calls cost money (OpenRouter, Jev): state a cap first.

| Script | What it does |
|---|---|
| `plan_staged.py <tag> <model> "<topic>"` | Plans one table lesson with `planner/lesson_recurrence.py`, live. Saves every model answer and the lesson to `out/domains/<tag>/`. Model used so far: `deepseek/deepseek-v4.1-flash`. |
| `render_plan.py <plan dir> <out dir>` | Renders a saved lesson (`lesson_plan.json` + `browser_visual_plan.json`) with voice into a video. About 4 minutes per minute of video. |
| `stills.py <plan dir> <out prefix>` | Screenshots the closing frame of every scene and runs the layout check. Fast; use before a full render. |
| `review_pack.py <tag> <pack dir>` | Builds a review pack for a staged lesson: the prompts, the model's answers, the lesson, a storyboard and two frames per beat. Needs the rendered video in `out/phase4_review/<tag>/`. |
| `jev_route_trial.py` | Routes 15 fixed topics with the keyword match and with Jev, against known answers. |
| `jev_gate_eval.py <out json>` | Measures Jev's sentence judge on saved lessons and known-bad copies of their sentences. |

## The independent review

A lesson is judged by an independent reviewer that is given the review pack and not told what to
conclude. The brief used for every score in `MEMORY.md`:

> You are an independent reviewer of one short AI-generated teaching video. Nobody has told you what
> to conclude; the builders want a critical, unbiased verdict. The video is for a BEGINNER who has
> never met the idea, meant for teachers and YouTube creators to publish. Read input.md, the model's
> answers and the lesson; open every frame in storyboard order. Judge as a new learner watching once
> and as an experienced teacher: correctness (work the problem yourself; list every error), storyline
> (question, naive attempt with felt cost, turning point, payoff), explainability (is the reason said
> AND shown), understandability for a newcomer, narration against picture beat by beat (flag
> mismatches with frame names), pacing and visual clarity. Return: a one-sentence verdict (would a new
> learner properly understand: yes / partly / no; would a teacher publish as is); scores out of 10 for
> correctness, storyline, explainability, understandability, narration-picture match, pacing, visual
> clarity, overall; every error with frame names; the five most harmful problems ranked; what works;
> what you could not judge. Do not soften findings.

Scores so far: single-call lessons 3.5 to 5; staged lessons 5 to 6 (best: climbing stairs, 6).
