"""FR-21 — per-scene version history + rollback. PER-SCENE, not global.

snapshot() freezes a scene's CURRENT render (copying the real deep mp4/srt into an immutable
versions/vNN/ dir) into node.versions. The editing ops (tweak, narration edit) auto-snapshot
before they re-render, so any edit is reversible. rollback() restores a frozen version and
re-stitches WITHOUT re-rendering — node.mp4 simply points at the frozen copy (stitch copies all
inputs into parts/ before concat, so the live media dir is irrelevant). Rollback validates the
frozen artifact exists and snapshots the current state first, so it never half-mutates and is
itself reversible.

Defined in editing/ (operates on composition's SceneVersion); composition never imports editing.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from composition.scene_dag import SceneNode, SceneVersion, VideoProject
from editing._common import restitch_and_save


def _versions_dir(out_dir: str | Path, node: SceneNode) -> Path:
    return Path(out_dir) / "scenes" / f"scene_{node.sid}" / "versions"


def snapshot(node: SceneNode, *, out_dir: str | Path, label: str = "") -> SceneVersion | None:
    """Freeze the node's current render into versions/vNN/. No-op if the scene has no clip yet."""
    if not node.mp4 or not Path(node.mp4).exists():
        return None
    vnum = len(node.versions)
    vdir = _versions_dir(out_dir, node) / f"v{vnum:02d}"
    vdir.mkdir(parents=True, exist_ok=True)

    frozen_mp4 = vdir / "clip.mp4"
    shutil.copy2(node.mp4, frozen_mp4)
    frozen_srt: Path | None = None
    if node.srt and Path(node.srt).exists():
        frozen_srt = vdir / "captions.srt"
        shutil.copy2(node.srt, frozen_srt)

    ver = SceneVersion(
        version=vnum, label=label, spec=node.spec, code=node.code, script=list(node.script),
        mp4=str(frozen_mp4), srt=(str(frozen_srt) if frozen_srt else None), score=node.score,
    )
    node.versions.append(ver)
    return ver


def rollback(project: VideoProject, index: int, version: int, *, out_dir: str | Path,
             log=print) -> VideoProject:
    """Restore scene `index` to a previous frozen version and re-stitch. No re-render."""
    if not (0 <= index < len(project.scenes)):
        raise IndexError(f"scene index {index} out of range")
    node = project.scene(index)
    if not (0 <= version < len(node.versions)):
        raise IndexError(f"scene {index} has no version {version} (have {len(node.versions)})")
    ver = node.versions[version]
    if not ver.mp4 or not Path(ver.mp4).exists():
        raise FileNotFoundError(f"frozen clip for scene {index} v{version} is missing: {ver.mp4}")

    say = log or (lambda _m: None)
    # snapshot the CURRENT state first so the rollback is itself reversible (and never half-mutates)
    snapshot(node, out_dir=out_dir, label=f"pre-rollback-to-v{version}")
    say(f"-> rolling scene {index} back to v{version} (no re-render); re-stitching")

    node.spec = ver.spec
    node.code = ver.code
    node.script = list(ver.script)
    node.mp4 = ver.mp4            # point at the immutable frozen copy
    node.srt = ver.srt
    node.score = ver.score       # provenance: this clip's own critic score
    node.compiled = True
    restitch_and_save(project, out_dir, log=say)
    return project
