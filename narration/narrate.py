"""M4 orchestrator — prompt's scene spec -> narrated, synced, captioned scene.

Flow: narration script (FR-9) -> host-side TTS clips (FR-10) -> narrated codegen (add_sound
sync, FR-11) -> compile-repair render in the NO-NET sandbox (audio mounted in) -> SRT captions
(FR-12). TTS is the only networked step and it runs on the host; the render never touches the
network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.config import settings
from core.llm import LLMClient, get_client
from core.schemas.narration import NarrationScript
from core.schemas.scene_spec import SceneSpec
from core.textutil import strip_code_fences
from generation import codegen
from narration import captions, tts
from narration import script as narr_script
from narration.tts import Clip
from prompts.loader import load
from verification import compile_repair, vision_critic


@dataclass
class NarratedResult:
    compiled: bool
    code: str
    mp4: Path | None = None
    srt: Path | None = None
    clips: list[Clip] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


def _narration_aware_fixer(spec: SceneSpec, style, client: LLMClient | None):
    """Visual-issue fixer for the critic loop that PRESERVES the add_sound narration sync.

    The default vision-critic fixer rewrites code with the plain codegen prompt, which would drop
    the `self.add_sound(...)` calls and desync the audio. This one uses the NARRATED codegen
    conventions and explicitly tells the model to keep every add_sound call and its timing.
    """
    client = client or get_client()
    system = load("manim-conventions") + "\n\n---\n\n" + load("codegen-narrated")
    style_block = ("\n\n" + style.as_prompt()) if style else ""
    intent = f"\n\nScene spec (keep the intent):\n{spec.model_dump_json(indent=2)}" if spec else ""

    def fix(code: str, report) -> str:
        issues = "\n".join(
            f"- [{i.type}] {i.location}: {i.description} -> FIX: {i.suggested_fix}"
            for i in report.issues) or "- (no specific issues listed)"
        user = (f"A vision critic found these visual defects in the rendered scene:\n{issues}\n\n"
                f"CURRENT CODE:\n{code}{intent}{style_block}\n\n"
                "Fix ONLY the visual problems: reposition/resize so nothing overlaps or runs off the "
                "frame, and keep the title within the frame. PRESERVE every self.add_sound(...) call and "
                "its position/timing EXACTLY — do not change the narration sync. "
                "Resend the full corrected file (code only).")
        raw = client.chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
        new = strip_code_fences(raw)
        # GUARD: a visual fix must NEVER silence the scene. If the rewrite dropped add_sound calls
        # (the model ignored the instruction), reject it and keep the prior voiced code — a known
        # visual nit beats a silent scene that then drops audio from the whole stitched film.
        if code.count("add_sound") > new.count("add_sound"):
            return code
        return new

    return fix


def build(spec: SceneSpec, *, work_dir: str | Path, quality: str = "preview",
          client: LLMClient | None = None, style=None, lines: list[str] | None = None,
          context: str | None = None, critic: bool | None = None, log=print) -> NarratedResult:
    client = client or get_client()
    wd = Path(work_dir)
    wd.mkdir(parents=True, exist_ok=True)
    say = log or (lambda _m: None)

    if lines is not None:
        script = NarrationScript(lines=list(lines))      # verbatim (an edit supplies the lines)
        say(f"-> using {len(script.lines)} supplied narration line(s)")
    else:
        say("-> narration script (narration-first)")
        script = narr_script.generate(spec, context=context, client=client)  # context = the story arc
        say(f"   {len(script.lines)} line(s)")

    say("-> synthesizing audio (host-side gTTS, render stays no-net)")
    clips = tts.synthesize_lines(script.lines, out_dir=wd / "audio")
    beats_audio = [(c.text, c.path.relative_to(wd).as_posix(), c.duration) for c in clips]
    say(f"   {len(clips)} clip(s), {sum(c.duration for c in clips):.1f}s total")

    say("-> narrated codegen (add_sound sync)")
    code = codegen.generate_narrated(spec, beats_audio, client=client, style=style)

    use_critic = settings.video_critic_enabled if critic is None else critic
    if use_critic:
        # LAYER 1 (free compile-repair) then LAYER 2 (paid vision critic), reusing the M2 loop but
        # with a narration-preserving fixer. Returns the best attempt; mp4 is set whenever it compiled.
        say("-> rendering + free layout lint (paid vision off by default for video; audio mounted in)")
        cr = vision_critic.run(code, wd, spec, quality=quality, client=client,
                               issue_regen_fn=_narration_aware_fixer(spec, style, client),
                               vision_confirm=settings.video_vision_confirm, log=say)
        compiled, code_out, mp4 = cr.compiled, cr.code, cr.mp4
    else:
        say("-> rendering (sandboxed, no network; audio mounted in)")
        rep = compile_repair.repair(code, wd, quality=quality, spec=spec, client=client, log=say)
        compiled, code_out, mp4 = rep.ok, rep.code, (rep.mp4 if rep.ok else None)

    srt: Path | None = None
    if compiled and mp4:
        srt = wd / "captions.srt"
        srt.write_text(captions.build_srt(script.lines, [c.duration for c in clips]),
                       encoding="utf-8")

    return NarratedResult(compiled, code_out, mp4, srt, clips, script.lines)
