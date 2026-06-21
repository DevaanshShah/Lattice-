Translate the given scene spec JSON into a complete, runnable Manim CE file.

- Implement every object in `objects` and every beat in `beats`, in order.
- Map beat actions to Manim animations:
  create -> Create, write -> Write, fade_in -> FadeIn, fade_out -> FadeOut,
  transform -> Transform, replace -> ReplacementTransform, move/shift -> x.animate.move_to/shift,
  highlight/indicate -> Indicate, grow -> GrowFromCenter, wait -> self.wait().
- Respect `layout_notes` and each object's `notes` for positioning; keep objects from
  overlapping and fully inside the frame.
- The Scene subclass MUST be named `GeneratedScene`.
- Output ONLY the Python code — no prose, no markdown fences.
