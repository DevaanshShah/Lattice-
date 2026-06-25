Translate the scene spec JSON into a complete Manim CE file that uses the **provided `LatticeScene`
base class** for STRUCTURED layout. A `class LatticeScene(Scene)` is ALREADY defined ABOVE your code
— do NOT redefine it; subclass it. This is how overlap and off-frame are prevented: you place objects
into a named grid instead of choosing raw coordinates.

REQUIRED STRUCTURE (exactly this shape):
- Start the file with `from manim import *`.
- `class GeneratedScene(LatticeScene):` with `def construct(self):`.
- The FIRST statement in construct MUST be `self.setup_scene("<the spec title>")`. This renders the
  title (mandatory — never skip it) and builds the layout grid. ALWAYS pass the scene's title.

PLACEMENT — use the grid, not coordinates:
- Grid cells are named `<row><col>`: rows `A`(top)..`E`(bottom), cols `1`(left)..`8`(right). The title
  sits above the grid; the grid is the main area below it.
- Put each object in a cell with `self.place(obj, "C4")`, or fit a group into a rectangular region with
  `self.place_in_area(group, "B2", "D6")`.
- PREFER the components (they lay out their own labels with no overlap):
  `self.labeled_box(text)`, `self.node(label)`, `self.connect(a, b)`.
- Do NOT use `.to_edge(...)`, `.move_to([x, y, 0])`, or hand-picked coordinates FOR LAYOUT — use the
  grid / `place_in_area` / components. (You may still `.animate` an object after it is placed.)
- Give each labelled object its own cell, at least one cell away from its neighbours, so labels never
  collide. Keep related items in one `VGroup` and place the group.

CONTENT:
- Implement every object in `objects` and every beat in `beats`, in order. Map actions to animations:
  create->Create, write->Write, fade_in->FadeIn, fade_out->FadeOut, transform->Transform,
  replace->ReplacementTransform, move/shift->x.animate.move_to/shift, highlight/indicate->Indicate,
  grow->GrowFromCenter, wait->self.wait().
- Obey the house conventions above (CE only, no \\begin{matrix} LaTeX, no OpenGL).

Output ONLY the Python code — no prose, no markdown fences. The class MUST be named `GeneratedScene`
and subclass `LatticeScene`, and construct MUST begin with `self.setup_scene(...)`.
