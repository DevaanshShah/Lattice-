"""M4 orchestrator — prompt's scene spec -> narrated, synced, captioned scene.

Flow: narration script (FR-9) -> host-side TTS clips (FR-10) -> narrated codegen (add_sound
sync, FR-11) -> compile-repair render in the NO-NET sandbox (audio mounted in) -> SRT captions
(FR-12). TTS is the only networked step and it runs on the host; the render never touches the
network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.llm import LLMClient, get_client
from core.schemas.narration import NarrationScript
from core.schemas.scene_spec import SceneSpec
from generation import codegen
from narration import captions, tts
from narration import script as narr_script
from narration.tts import Clip
from verification import compile_repair


@dataclass
class NarratedResult:
    compiled: bool
    code: str
    mp4: Path | None = None
    srt: Path | None = None
    clips: list[Clip] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


def build(spec: SceneSpec, *, work_dir: str | Path, quality: str = "preview",
          client: LLMClient | None = None, style=None, lines: list[str] | None = None,
          log=print) -> NarratedResult:
    client = client or get_client()
    wd = Path(work_dir)
    wd.mkdir(parents=True, exist_ok=True)
    say = log or (lambda _m: None)

    if lines is not None:
        script = NarrationScript(lines=list(lines))      # verbatim (an edit supplies the lines)
        say(f"-> using {len(script.lines)} supplied narration line(s)")
    else:
        say("-> narration script (narration-first)")
        script = narr_script.generate(spec, client=client)
        say(f"   {len(script.lines)} line(s)")

    say("-> synthesizing audio (host-side gTTS, render stays no-net)")
    clips = tts.synthesize_lines(script.lines, out_dir=wd / "audio")
    beats_audio = [(c.text, c.path.relative_to(wd).as_posix(), c.duration) for c in clips]
    say(f"   {len(clips)} clip(s), {sum(c.duration for c in clips):.1f}s total")

    say("-> narrated codegen (add_sound sync)")
    code = codegen.generate_narrated(spec, beats_audio, client=client, style=style)

    say("-> rendering (sandboxed, no network; audio mounted in)")
    rep = compile_repair.repair(code, wd, quality=quality, spec=spec, client=client, log=say)

    srt: Path | None = None
    if rep.ok and rep.mp4:
        srt = wd / "captions.srt"
        srt.write_text(captions.build_srt(script.lines, [c.duration for c in clips]),
                       encoding="utf-8")

    return NarratedResult(rep.ok, rep.code, rep.mp4 if rep.ok else None, srt, clips, script.lines)
