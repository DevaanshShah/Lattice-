Translate the given scene spec JSON into a complete, runnable Manim CE file.

- Implement every object in `objects` and every beat in `beats`, in order.
- Map beat actions to Manim animations:
  create -> Create, write -> Write, fade_in -> FadeIn, fade_out -> FadeOut,
  transform -> Transform, replace -> ReplacementTransform, move/shift -> x.animate.move_to/shift,
  highlight/indicate -> Indicate, grow -> GrowFromCenter, wait -> self.wait().

LAYOUT — THE MOST IMPORTANT RULE (almost every defect is overlap or off-frame). Do NOT place multiple
objects at absolute coordinates with move_to([x, y, 0]); that causes overlap. Use Manim's OWN layout
methods, which compute non-overlapping positions automatically:
- A ROW or COLUMN of items (tokens, boxes, vectors, steps): group them in a VGroup and arrange,
  e.g. `row = VGroup(a, b, c, d); row.arrange(RIGHT, buff=0.6)`. Keep buff >= 0.4.
- A GRID (e.g. an attention matrix): `grid = VGroup(*cells); grid.arrange_in_grid(rows=R, cols=C, buff=0.5)`.
- Place one object relative to another with `obj.next_to(other, RIGHT, buff=0.5)` — never on top of it.
- A shape's label goes via `label.move_to(box.get_center())` or `label.next_to(arrow, UP, buff=0.15)` —
  a label must NEVER sit on top of a DIFFERENT object's text.
- After arranging, centre the group: `group.move_to(ORIGIN)` (or `.next_to(title, DOWN, buff=0.6)`).
- TITLE: `title.to_edge(UP, buff=0.4)`; if wider than 12 units, `title.scale_to_fit_width(12)` so it
  never clips. The frame is ~14.2 wide x 8 tall, centred at the origin.
- If a row/group is wider than ~13 units, `group.scale_to_fit_width(13)` so nothing runs off-frame.
- Two pieces of text must never overlap. If they would, separate them with next_to/arrange + buff.
- TEXT INSIDE A CONTAINER (box, rectangle, circle): place the label AT the box center with
  `lbl.move_to(box.get_center())`, then fit it: `if lbl.width > box.width - 0.2: lbl.scale_to_fit_width(box.width - 0.2)`.
  The label must be INSIDE the box, never floating above or below it. If the content is long,
  widen the box first — never let text clip or overflow.
- SurroundingRectangle HIGHLIGHT: always pass the ORIGINAL mobject that is already placed in the
  scene — NEVER `.copy()`. Copies don't inherit the arranged position, so the rectangle draws in
  the wrong place. Correct: `SurroundingRectangle(token_a)`. Wrong: `SurroundingRectangle(token_a.copy())`.

TABLES / MATRICES / GRIDS OF NUMBERS OR WORDS — you MUST use Manim's built-in `Table`. NEVER build a
table by hand from separate row/column VGroups + `.next_to()`/`.arrange()` math — the cells will not
line up, headers detach, and values land in empty space (this is the #1 broken-scene cause). `Table`
draws the grid lines and aligns every cell automatically:
```python
t = Table(
    [["", "the", "cat", "sat"],
     ["the", "0", "2", "1"],
     ["cat", "1", "0", "1"]],
    include_outer_lines=True,
).scale(0.6)
t.next_to(title, DOWN, buff=0.5)
```
  - To highlight: `t.add_highlighted_cell((2, 3), color=YELLOW)`, or `t.get_rows()[i]`,
    `t.get_columns()[j]`, `t.get_entries((r, c))` — indices are 1-based and count label rows/cols.
  - For a matrix of pure numbers use `IntegerTable(...)`; for math use `MathTable(...)`.
  - Never draw your own SurroundingRectangle "table outline" around loose text — use `Table`.

COMPOSE THE WHOLE SCENE (prevents the table-overlaps-text defect) — after building each block (the
table, a sentence, a row of options, a formula), collect the non-title blocks into ONE VGroup and
arrange them so Manim spaces them; do NOT drop a second block at ORIGIN on top of a table:
```python
body = VGroup(table, sentence, options).arrange(RIGHT, buff=0.9)   # or DOWN for stacked blocks
body.next_to(title, DOWN, buff=0.5).move_to([0, -0.3, 0])
if body.width > 13:  body.scale_to_fit_width(13)
if body.height > 6:  body.scale_to_fit_height(6)
```
  Two major blocks must occupy SEPARATE regions. If a table is on the left, put everything else to
  its right with `next_to(table, RIGHT, buff=...)` — never at absolute coords that land on the table.

- The Scene subclass MUST be named `GeneratedScene`.
- Output ONLY the Python code — no prose, no markdown fences.
