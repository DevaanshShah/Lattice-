Translate the scene spec JSON into a complete Manim CE file that BOTH (a) uses the provided
`LatticeScene` base class for structured layout AND (b) syncs the animation to narration audio.
A `class LatticeScene(Scene)` is ALREADY defined ABOVE your code — do NOT redefine it; subclass it.

REQUIRED STRUCTURE (exactly this shape):
- Start the file with `from manim import *`.
- `class GeneratedScene(LatticeScene):` with `def construct(self):`.
- The FIRST statement in construct MUST be `self.setup_scene("<the spec title>")`. It renders the
  title (mandatory — never skip it) and builds the layout grid. ALWAYS pass the scene's title.

LAYOUT — use the grid, never raw coordinates:
- Grid cells are `<row><col>`: rows `A`(top)..`E`(bottom), cols `1`(left)..`8`(right). Place objects
  with `self.place(obj, "C4")` or fit a group with `self.place_in_area(group, "B2", "D6")`.
- PREFER the components (they own their labels, no overlap): `self.labeled_box(text)`,
  `self.node(label)`, `self.connect(a, b)`. For MATH labels pass a RAW LaTeX string —
  `self.node(r"x_1")`, `self.node(r"\hat{y}")` — not `"x_1"` or `"$x_1$"` (those show literally).
- Do NOT use `.to_edge(...)`, `.move_to([x, y, 0])`, or hand-picked coordinates for layout. (You may
  `.animate` an object after placing it.) Give each labelled object its own cell, 1+ cell from neighbours.

NARRATION SYNC — the audio already exists; play it and time the visuals to it. For EACH beat i, in order:
    self.add_sound("<audio path for beat i>")     # starts that beat's narration (relative path like "audio/xxxx.mp3")
    self.play(<animation for this beat>, run_time=min(<sensible run_time>, <duration_i>))
    self.wait(max(0.0, <duration_i> - <the run_time you used>))   # pad to match the narration length
- One `self.add_sound(...)` per beat, right before that beat's animation, with the EXACT given path.
- Make each beat's on-screen time ≈ its narration duration so the visuals match the words.

CONTENT:
- Implement every object in `objects` and every beat in `beats`, in order. Obey the house conventions
  above (CE only, no \\begin{matrix} LaTeX, no OpenGL).

Output ONLY the Python code — no prose, no markdown fences. The class MUST be named `GeneratedScene`
and subclass `LatticeScene`, construct MUST begin with `self.setup_scene(...)`, and every beat MUST
call `self.add_sound(...)`.
