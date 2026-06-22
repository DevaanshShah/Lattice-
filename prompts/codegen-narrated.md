Translate the scene spec into a complete Manim CE file whose animation is SYNCED to narration
audio. For each beat you are given a narration line, its pre-rendered audio file, and the
audio's duration in seconds. The audio already exists — just play it and time the visuals to it.

For EACH beat i, in order, follow this pattern:

    self.add_sound("<audio path for beat i>")     # starts that beat's narration audio
    # play this beat's animation, lasting about <duration_i> seconds total:
    self.play(<animation for this beat>, run_time=min(<a sensible run_time>, <duration_i>))
    self.wait(max(0.0, <duration_i> - <the run_time you used>))   # pad to match the narration

Rules:
- Call self.add_sound(...) with the EXACT audio path given for each beat (relative paths like
  "audio/xxxx.mp3"). One add_sound per beat, right before that beat's animation.
- Make each beat's total on-screen time ≈ its narration duration so the visuals match the words.
- Implement the objects and beats per the scene spec, obeying ALL the house conventions above
  (layout bands, no overlap, CE only, GeneratedScene(Scene) with construct(self)).
- Output ONLY the Python code — no prose, no markdown fences.
