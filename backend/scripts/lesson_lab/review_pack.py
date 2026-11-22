import json, shutil, subprocess, sys
from pathlib import Path
tag, out = sys.argv[1], Path(sys.argv[2])
plan_dir, video_dir = Path("out/domains") / tag, Path("out/phase4_review") / tag
(out / "frames").mkdir(parents=True, exist_ok=True)
lesson = json.loads((plan_dir / "lesson_plan.json").read_text(encoding="utf-8"))
(out / "input.md").write_text(
    "# How this lesson was made\n\nTwo model calls with program code between them.\n\n"
    "## Call 1: the model decides the teaching and describes the table\n\n"
    + Path("prompts/recurrence-concept.md").read_text(encoding="utf-8")
    + "\n\nUser message: Topic: " + lesson["topic"] + "\n\nCode then checks the description and builds every step of the video, with all numbers.\n\n"
    "## Call 2: the model writes one sentence for each step it is shown\n\n"
    + Path("prompts/recurrence-narration.md").read_text(encoding="utf-8") + "\n", encoding="utf-8")
(out / "model_answers").mkdir(exist_ok=True)
for f in sorted(plan_dir.glob("call_*.txt")): shutil.copy(f, out / "model_answers" / f.name)
shutil.copy(plan_dir / "lesson_plan.json", out / "lesson_as_built.json")
rows = ["# Storyboard\n", f"Topic given: {lesson['topic']}\n", "`mid` is the frame half-way through the sentence, `end` is its last frame.\n"]
clock = 0.0
for s, scene in enumerate(lesson["scenes"]):
    rows.append(f"\n## Scene {s+1}: {scene['title']}\n")
    if scene.get("takeaway"): rows.append(f"Line shown as the scene closes: \"{scene['takeaway']}\"\n")
    for b, beat in enumerate(scene["beats"]):
        clip = video_dir / "beats" / f"scene_{s:02d}_{b:02d}.mp4"
        length = float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(clip)],capture_output=True,text=True).stdout.strip())
        names = []
        for label, moment in (("mid", length/2), ("end", max(0.0, length-0.05))):
            name = f"s{s+1}_b{b+1}_{label}.png"
            subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error","-ss",f"{moment:.2f}","-i",str(clip),"-frames:v","1",str(out/"frames"/name)],check=True)
            names.append(f"frames/{name}")
        rows.append(f"- **{clock:5.1f}s to {clock+length:5.1f}s** | spoken: \"{beat['spoken_text']}\" | frames: {names[0]}, {names[1]}")
        clock += length
rows.append(f"\nTotal length: {clock:.0f} seconds.\n")
(out / "storyboard.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
print(tag, "beats", sum(len(x["beats"]) for x in lesson["scenes"]), "seconds", round(clock))
