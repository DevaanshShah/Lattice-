"""M0 sample scene — hand-written, NO AI involved.

Its whole job is to prove the toolchain end-to-end: a shape animation (Manim renders)
AND a `MathTex` expression (LaTeX compiles — the #1 source of silent breakage). A Manim
install that animates shapes but chokes on equations *looks* fine and isn't.

Rendered inside the container only: `python -m scripts.render_sample`.
"""
from manim import (
    BLUE,
    DOWN,
    YELLOW,
    Circle,
    Create,
    MathTex,
    Scene,
    Square,
    Transform,
    Write,
)


class SampleScene(Scene):
    def construct(self):
        square = Square(color=BLUE)
        self.play(Create(square))            # shape animation

        circle = Circle(color=YELLOW)
        self.play(Transform(square, circle))  # transform

        equation = MathTex(r"e^{i\pi} + 1 = 0").scale(1.5).next_to(circle, DOWN)
        self.play(Write(equation))            # LaTeX / MathTex — proves the TeX path
        self.wait(0.5)
