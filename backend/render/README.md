# render/

Turns Manim code into pixels, safely and cheaply. Built across **M0 / M2 / M3**, hardened in **M7**.

**Owns**
- `worker` — local single-process render: Manim code → MP4 + keyframe PNG(s); callable as a function the verification loops invoke repeatedly (**FR-22**).
- `sandbox` — run model-written code in a container with **no network, non-root** from day one (**FR-23** seed). Hardened later with resource caps + ephemeral FS for multi-user.
- `cache` — content-hash render cache: skip re-rendering unchanged scenes; any meaningful spec/style change busts the key (**FR-25**).
- `quality` — low-res fast preview vs high-res final (**FR-26**).

**Invariants this package enforces**
- Preview fast, finalize slow — iterate on low-res, produce high-res only on final approval.
- Run model-written Python sandboxed from day one — never unsandboxed in multi-user.

**Maps to:** Phase 0 / M0 (worker + basic sandbox), Phase 1 / M2 (loops call it), Phase 5 / M7 (hardened). **FRs:** FR-22, FR-23, FR-25, FR-26.
