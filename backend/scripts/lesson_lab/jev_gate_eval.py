"""Does Jev tell a sentence that matches its step from one that does not? Measured before trusting it.

For each saved staged lesson: the real sentences (taken as good), and three kinds of known-bad copy
of each one: a number changed, the reason removed, and a claim from another step swapped in.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, ".")
from core.textutil import extract_json
from planner.lesson_recurrence import ConceptSpec, build_run
from planner import jev_gates

lessons = ["staged_stairs", "staged_trib", "staged_binary", "staged2_stairs", "staged2_trib",
           "staged2_binary", "staged3_stairs", "staged3_trib", "staged_pay", "staged_tiles"]


def bump(sentence):
    """The first number in the sentence, made wrong."""
    match = re.search(r"\d+", sentence)
    return None if not match else sentence[:match.start()] + str(int(match.group()) + 2) + sentence[match.end():]


rows = []
for tag in lessons:
    folder = Path("out/domains") / tag
    if not (folder / "lesson_plan.json").exists():
        continue
    concept = None
    for call in sorted(folder.glob("call_*.txt")):
        try:
            concept = ConceptSpec.model_validate(extract_json(call.read_text(encoding="utf-8")))
        except Exception:
            continue
    if concept is None:
        print(tag, "skipped: no concept in the current form")
        continue
    _, steps = build_run(concept)
    lesson = json.loads((folder / "lesson_plan.json").read_text(encoding="utf-8"))
    sentences = [beat["spoken_text"] for scene in lesson["scenes"] for beat in scene["beats"]][:len(steps)]
    sentences = [s if step["the sentence must"] != "said by code" else "" for s, step in zip(sentences, steps)]
    variants = {"good": sentences}
    variants["wrong number"] = [bump(s) or s for s in sentences]
    variants["no reason"] = [re.split(r",? (?:so|because|since|which means)\b", s)[0].rstrip(".") + "." if s else s
                             for s in sentences]
    variants["other step"] = [sentences[(i + 4) % len(sentences)] or s for i, s in enumerate(sentences)]
    for kind, said in variants.items():
        verdicts = jev_gates.judge_narration(steps, said)
        for v in verdicts:
            changed = said[v.step - 1] != sentences[v.step - 1]
            rows.append({"lesson": tag, "kind": kind, "step": v.step, "changed": changed,
                         "supported": v.supported, "explained": v.explained})
    print(tag, "done", flush=True)

Path(sys.argv[1]).write_text(json.dumps(rows, indent=1), encoding="utf-8")


def rate(selected, key, threshold=0.5):
    flagged = [r for r in selected if r[key] is not None and r[key] < threshold]
    scored = [r for r in selected if r[key] is not None]
    return f"{len(flagged)}/{len(scored)} flagged"


good = [r for r in rows if r["kind"] == "good"]
print("GOOD sentences   supported:", rate(good, "supported"), "| explained:", rate(good, "explained"))
for kind in ("wrong number", "other step"):
    bad = [r for r in rows if r["kind"] == kind and r["changed"]]
    print(f"{kind:16} supported:", rate(bad, "supported"))
bad = [r for r in rows if r["kind"] == "no reason" and r["changed"]]
print(f"{'no reason':16} explained:", rate(bad, "explained"))
