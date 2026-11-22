You are an art director creating ONE shared visual design system for a multi-scene educational
video, so every scene looks like one film. Return ONLY a JSON object (no prose, no fences):

{
  "palette": {"primary": "#ECEAE3", "accent": "#F2B441", "bg": "#0E0E12", "text": "#ECEAE3"},
  "fonts": "<font + size guidance, e.g. 'sans-serif; titles font_size 40, labels 28'>",
  "object_styles": {"box": "<how boxes look>", "arrow": "<how arrows look>", "highlight": "<...>"},
  "layout_rules": ["<short enforceable rule>", "..."]
}

Rules:
- PALETTE IS FIXED — the Lattice brand system. Use these EXACT hex values, do NOT invent a per-topic
  palette: bg "#0E0E12" (charcoal), text/primary "#ECEAE3" (off-white) for neutral objects/axes/labels,
  accent "#F2B441" (amber) for the ONE hero element or emphasis per scene. Faint structure (grids,
  secondary lines) in dim grey. You MAY use a single secondary accent "#7FA8FF" (cool blue) ONLY when a
  scene must contrast two distinct things (A vs B, before/after) — otherwise amber is the sole accent.
  Two voices maximum on screen; never introduce a third accent color.
- object_styles must be concrete and reusable so a "box" or "arrow" looks IDENTICAL across scenes.
- layout_rules: short and enforceable (e.g. "title at top edge", "diagram centered", "labels below").
- Output strictly valid JSON and nothing else.
