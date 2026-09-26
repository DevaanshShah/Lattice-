"""Compile bounded array, pointer, and counter actions into the existing Manim scene."""
from __future__ import annotations

import json

from core.schemas.browser_visual_plan import BrowserScene
from core.visual_state import VisualState
from generation.lattice_scene import LATTICE_SCENE_SRC


def compile_scene(scene: BrowserScene, *, title: str, opening: VisualState,
                  audio: list[tuple[str, float]]) -> str:
    if scene.render_mode != "manim" or len(audio) != len(scene.beats):
        raise ValueError("Manim compiler needs a Manim scene and audio for every beat")
    data = scene.model_dump()
    data["title"] = title
    data["opening_payloads"] = opening.payloads
    data["audio"] = [{"path": path, "duration": duration} for path, duration in audio]
    data["timelines"] = [beat.timeline(duration) if beat.actions[0].start_fraction is not None else None
                         for beat, (_, duration) in zip(scene.beats, audio)]
    encoded = json.dumps(data, ensure_ascii=False)
    return LATTICE_SCENE_SRC + f"\nimport json\nPLAN = json.loads({encoded!r})\n" + '''

class GeneratedScene(LatticeScene):
    def construct(self):
        self.setup_scene(PLAN["title"])
        objects = {obj["id"]: obj for obj in PLAN["objects"]}
        payloads = PLAN["opening_payloads"]
        array = next(obj for obj in PLAN["objects"] if obj["kind"] == "array")
        values = payloads[array["id"]]["items"]
        width = min(1.18, (11.7 - (len(values) - 1) * .12) / len(values))
        cells = VGroup()
        for index, value in enumerate(values):
            box = RoundedRectangle(width=width, height=1.04, corner_radius=.12,
                                   color="#77a8d1", fill_color="#1c2b39", fill_opacity=1)
            number = Text(str(value), font_size=min(34, int(width * 32)), weight=BOLD)
            number.move_to(box)
            mark = Text(str(index), font_size=14, color=GRAY_B).next_to(box, DOWN, buff=.12)
            cells.add(VGroup(box, number, mark))
        cells.arrange(RIGHT, buff=.12).move_to(DOWN * .25)
        for index in payloads[array["id"]].get("discarded_indices", []):
            cells[index].set_opacity(.2)
        check_marks = {}
        for index, outcome in payloads[array["id"]].get("checked_results", {}).items():
            i = int(index)
            mark = Text("✓" if outcome == "match" else "✗", font_size=20,
                        color=GREEN if outcome == "match" else RED)
            mark.move_to(cells[i][0].get_corner(UR) + LEFT * .18 + DOWN * .18)
            check_marks[i] = mark
        caption = Text(array["label"], font_size=26).next_to(cells, UP, buff=1.0)
        visuals = {array["id"]: VGroup(cells, caption)}
        pointer_offsets = {}
        for number, obj in enumerate(o for o in PLAN["objects"] if o["kind"] == "pointer"):
            pointer_offsets[obj["id"]] = number * .42
            marker = Triangle(color=YELLOW, fill_color=YELLOW, fill_opacity=1).scale(.14).rotate(PI)
            name = Text(obj["label"], font_size=18, color=YELLOW)
            pointer = VGroup(name, marker).arrange(DOWN, buff=.06)
            pointer.next_to(cells[payloads[obj["id"]]["index"]], UP,
                            buff=.16 + pointer_offsets[obj["id"]])
            visuals[obj["id"]] = pointer
        for number, obj in enumerate(o for o in PLAN["objects"]
                                     if o["kind"] in {"counter", "value", "formula", "gate"}):
            content = (str(payloads[obj["id"]]["expression"])
                       if obj["kind"] == "formula" else
                       obj["label"] if obj["kind"] == "gate" else
                       f'{obj["label"]}: {payloads[obj["id"]]["value"] if payloads[obj["id"]]["value"] is not None else "?"}')
            visual = Text(content, font_size=27, color=YELLOW)
            visual.next_to(cells, DOWN, buff=.7 + number * .48)
            visuals[obj["id"]] = visual
        visible = set(PLAN["opening_visible_ids"])
        for obj_id in visible:
            self.add(visuals[obj_id])
        if array["id"] in visible:
            self.add(*check_marks.values())
        for beat, audio, timeline in zip(PLAN["beats"], PLAN["audio"], PLAN["timelines"]):
            beat_start = self.renderer.time
            self.add_sound(audio["path"])
            actions = beat["actions"]
            merged = sum(action["kind"] == "compare" and actions[i + 1]["kind"] == "increment"
                         for i, action in enumerate(actions[:-1]))
            steps = len(actions) - merged
            run = min(.65, audio["duration"] / (steps + 1))
            action_index = 0
            while action_index < len(actions):
                action = actions[action_index]
                kind, targets, params = action["kind"], action["target_ids"], action["params"]
                next_action = actions[action_index + 1] if action_index + 1 < len(actions) else None
                paired_increment = next_action if kind == "compare" and next_action and next_action["kind"] == "increment" else None
                if timeline is not None:
                    paired_increment = None
                    start, end = timeline[action_index]
                    gap = beat_start + start - self.renderer.time
                    if gap > 0:
                        self.wait(gap)
                    run = end - start
                if kind == "appear":
                    new = [target for target in targets if target not in visible]
                    if new:
                        self.play(*[FadeIn(visuals[target]) for target in new], run_time=run)
                    visible.update(targets)
                elif kind == "hide":
                    shown = [target for target in targets if target in visible]
                    if shown:
                        self.play(*[FadeOut(visuals[target]) for target in shown], run_time=run)
                    visible.difference_update(targets)
                elif kind == "move":
                    motions = []
                    for target in targets:
                        index = params["index"]
                        destination = visuals[target].copy().next_to(
                            cells[index], UP, buff=.16 + pointer_offsets[target]).get_center()
                        motions.append(visuals[target].animate.move_to(destination))
                        payloads[target]["index"] = index
                    self.play(*motions, run_time=run)
                elif kind == "set_state":
                    motions = []
                    for target in targets:
                        if objects[target]["kind"] == "array" and "discarded_indices" in params:
                            discarded = set(params["discarded_indices"])
                            motions.extend(cell.animate.set_opacity(.2 if i in discarded else 1)
                                           for i, cell in enumerate(cells))
                        elif objects[target]["kind"] == "counter" and "value" in params:
                            updated = Text(f'{objects[target]["label"]}: {params["value"]}',
                                           font_size=27, color=YELLOW).move_to(visuals[target])
                            motions.append(Transform(visuals[target], updated))
                        payloads[target].update(params)
                    if motions:
                        self.play(*motions, run_time=run)
                elif kind == "increment":
                    motions = []
                    for target in targets:
                        payloads[target]["value"] += params.get("by", 1)
                        updated = Text(f'{objects[target]["label"]}: {payloads[target]["value"]}',
                                       font_size=29, color=YELLOW).move_to(visuals[target])
                        motions.append(Transform(visuals[target], updated))
                    self.play(*motions, run_time=run)
                elif kind == "compare":
                    pointer_id, target_id = targets
                    index = payloads[pointer_id]["index"]
                    outcome = ("match" if values[index] == payloads[target_id]["value"]
                               else "miss")
                    payloads[array["id"]].setdefault("checked_results", {})[str(index)] = outcome
                    mark = Text("✓" if outcome == "match" else "✗", font_size=20,
                                color=GREEN if outcome == "match" else RED)
                    mark.move_to(cells[index][0].get_corner(UR) + LEFT * .18 + DOWN * .18)
                    motions = []
                    if index in check_marks:
                        motions.append(Transform(check_marks[index], mark))
                    else:
                        check_marks[index] = mark
                        motions.append(FadeIn(mark))
                    if paired_increment:
                        for counter_id in paired_increment["target_ids"]:
                            payloads[counter_id]["value"] += paired_increment["params"].get("by", 1)
                            updated = Text(f'{objects[counter_id]["label"]}: {payloads[counter_id]["value"]}',
                                           font_size=29, color=YELLOW).move_to(visuals[counter_id])
                            motions.append(Transform(visuals[counter_id], updated))
                    self.play(*motions, run_time=run)
                elif kind in {"focus", "highlight"}:
                    self.play(*[Indicate(visuals[target]) for target in targets], run_time=run)
                elif kind == "hold":
                    self.wait(run)
                if timeline is not None:
                    gap = beat_start + end - self.renderer.time
                    if gap > 0:
                        self.wait(gap)
                action_index += 2 if paired_increment else 1
            remaining = audio["duration"] - (self.renderer.time - beat_start)
            if remaining > 0:
                self.wait(remaining)
'''
