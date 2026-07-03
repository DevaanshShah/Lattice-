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
- For MATH labels (subscripts, superscripts, Greek), pass a RAW LaTeX string — the component renders
  it as math: `self.node(r"x_1")`, `self.node(r"\hat{y}")`, `self.labeled_box(r"\sigma")`. Do NOT wrap
  in `$...$` and do NOT pass plain `"x_1"` for a subscript (it would show literally).
- Do NOT use `.to_edge(...)`, `.move_to([x, y, 0])`, or hand-picked coordinates FOR LAYOUT — use the
  grid / `place_in_area` / components. (You may still `.animate` an object after it is placed.)
- Give each labelled object its own cell, at least one cell away from its neighbours, so labels never
  collide. Keep related items in one `VGroup` and place the group.

STRUCTURED DATA — use Manim's built-ins, NOT the grid, for these (the grid is for freeform diagrams;
placing tabular values into cells by hand is the #1 broken-scene cause — cells won't line up):
- A TABLE / MATRIX of numbers or words (counts, probabilities, comparisons): build ONE `Table(...)`
  (or `IntegerTable(...)` / `MathTable(...)`) — it draws the grid lines and aligns every cell for you.
  Then place the whole table as a single object: `self.place_in_area(table, "B2", "D7")`. NEVER create
  separate row/column VGroups and position cell values with next_to/place — they will not align.
  ```python
  t = Table([["", "the", "cat"], ["the", "0", "2"], ["cat", "1", "0"]], include_outer_lines=True)
  self.place_in_area(t, "B2", "E7")
  ```
  Highlight cells via `t.add_highlighted_cell((2, 3))`, `t.get_rows()[i]`, `t.get_entries((r, c))`.
- A BAR CHART / probability distribution: one `BarChart(values=[...], bar_names=[...])`, placed as one object.
- A PLOTTED FUNCTION / axes: build `ax = Axes(...)`, place the AXES ONCE with
  `self.place_in_area(ax, "B2", "E7")`, THEN plot and mark everything relative to it:
  `curve = ax.plot(f)`, `dot = Dot(ax.c2p(x0, y0))`, `tan = ax.plot(tangent_fn)`. Do NOT call
  `self.place(...)` on the curve, dot, or tangent separately — `c2p` already positions them ON the
  axes; re-placing a sub-element re-centers it on a cell and DETACHES it from the graph. Group extra
  labels with the axes and place the group once if you must move it.
- A BRACE annotation ("these form a group / a bigram"): `self.braced(mob, "text", DOWN)` — or Manim's
  `Brace(mob)` + `BraceLabel(mob, "text")`.
- HIGHLIGHT: pass the ORIGINAL, already-placed object to `SurroundingRectangle` — NEVER `.copy()`
  (a copy has no placed position, so the box draws in the wrong spot).

GEOMETRY / CONSTRUCTIONS — do NOT hand-compute coordinates for these; the model gets the precise math
wrong blind. Use the helper or the built-in:
- A SQUARE flush on a triangle/segment side: `self.square_on_segment(A, B, away_from=REF)` — pass the
  two vertex POINTS and a THIRD reference point the square must extend away from (the triangle's other
  vertex, or `triangle.get_center()`), e.g. `self.square_on_segment(tri.get_vertices()[0], tri.get_vertices()[1], away_from=tri.get_center())`.
  ALWAYS pass `away_from` — it is what makes the square land on the correct outside every time,
  regardless of vertex order; guessing `outward=True/False` instead is a coin flip that can put the
  square INSIDE the triangle. It is already positioned — do NOT `self.place()` it. NEVER build a
  `Square()` and `next_to()` a corner: it will float, not sit flush on the side.
- A RIGHT-ANGLE mark or an ANGLE arc: use Manim's `RightAngle(line1, line2)` / `Angle(line1, line2)` —
  build the two `Line`s along the sides and pass them in; do not hand-place an arc.
- A POINT / label ON a plotted curve: `Dot(ax.c2p(x0, f(x0)))` — it sits on the axes; never `self.place()` it.

CONTENT:
- Implement every object in `objects` and every beat in `beats`, in order. Map actions to animations:
  create->Create, write->Write, fade_in->FadeIn, fade_out->FadeOut, transform->Transform,
  replace->ReplacementTransform, move/shift->x.animate.move_to/shift, highlight/indicate->Indicate,
  grow->GrowFromCenter, wait->self.wait().
- Obey the house conventions above (CE only, no \\begin{matrix} LaTeX, no OpenGL).

Output ONLY the Python code — no prose, no markdown fences. The class MUST be named `GeneratedScene`
and subclass `LatticeScene`, and construct MUST begin with `self.setup_scene(...)`.
