# narration/

Makes a scene explain itself out loud, animation synced to the script. Built in **M4** (Phase 2).

**Owns**
- `script` — **narration-first** generation: write the script, then generate animation that syncs to it (**FR-9**). The script drives the visuals, not a caption bolted on after.
- `tts` — text-to-speech engines, swappable: free **gTTS** to start, OpenAI/Azure for quality (**Q3**, **FR-10**). The clean seam FR-33 (voice swap) and FR-34 (multi-language) plug into later. Audio cached by content hash.
- `sync` — `manim-voiceover` `with self.voiceover(...)` blocks; each animation's duration comes from its audio segment — no hand-tuned timing (**FR-11**).
- `captions` — auto subtitle track / burned-in captions from the narration (**FR-12**).

**Known coupling (inherent, not a bug):** editing narration text re-renders that scene, because timing derives from audio duration. Made cheap via TTS + render caching.

**Maps to:** Phase 2 / M4. **FRs:** FR-9, FR-10, FR-11, FR-12.
