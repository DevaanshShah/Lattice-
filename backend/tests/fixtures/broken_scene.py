# Deliberately broken scene for the compile-repair live check (FR-5).
# It passes the static guardrails (imports CE, defines GeneratedScene + construct) so the
# failure surfaces only at RENDER time: `undefined_circle` is never defined -> NameError.
# The repair loop should feed the trimmed traceback back and recover within the cap.
from manim import *


class GeneratedScene(Scene):
    def construct(self):
        self.play(Create(undefined_circle))  # NameError: undefined_circle is not defined
        self.wait(0.5)
