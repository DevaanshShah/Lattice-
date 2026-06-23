"""FR-24 / FR-29 — async render jobs with trackable status + a streamable progress log.

Renders take minutes, so the web layer never runs them inside a request. A submitted build/
regen/tweak becomes a `Job` that runs on a bounded background thread pool; the HTTP handler
returns immediately with a job id and the UI polls/streams status. Two users' jobs run on
separate threads, so they don't block each other (FR-24).

Each job carries:
- a coarse lifecycle `status`: queued -> running -> done | failed,
- per-scene `scenes` status (queued/rendering/done/failed) so a timeline shows live state,
- an append-only `events` log (every engine `log(...)` line) with a monotonic cursor so a late
  or reconnecting client can replay from where it left off — the basis of streaming (FR-29).

Everything here is thread-safe and free of network/docker, so the queue logic is unit-tested
directly (with `synchronous=True`, jobs run inline and deterministically).
"""
from __future__ import annotations

import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

# lifecycle states
QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"
# per-scene states
S_QUEUED, S_RENDERING, S_DONE, S_FAILED = "queued", "rendering", "done", "failed"
_TERMINAL = {DONE, FAILED}


@dataclass
class JobEvent:
    seq: int
    ts: float
    message: str


class Job:
    """A single async unit of work and its observable state. `now` is injectable for tests."""

    def __init__(self, *, kind: str, project_id: str, scene_index: int | None = None,
                 now: Callable[[], float] = time.time) -> None:
        self.id: str = uuid4().hex[:12]
        self.kind = kind                       # "build" | "regenerate" | "tweak" | "narration" | "insert"
        self.project_id = project_id
        self.scene_index = scene_index
        self._now = now
        self.status: str = QUEUED
        self.scenes: dict[int, str] = {}       # index -> per-scene status
        self.events: list[JobEvent] = []
        self.error: str | None = None
        self.result: Any = None
        self.created_at = now()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self._lock = threading.Lock()

    # --- progress (called from the worker thread via the engine's log= callback) ---
    def log(self, message: str) -> None:
        with self._lock:
            self.events.append(JobEvent(len(self.events), self._now(), str(message)))

    def set_scene(self, index: int, status: str) -> None:
        with self._lock:
            self.scenes[index] = status

    def events_since(self, cursor: int) -> list[JobEvent]:
        with self._lock:
            return [e for e in self.events if e.seq >= cursor]

    def progress(self) -> dict:
        """A COARSE, user-facing progress snapshot — the cylinder's fill + a friendly phase label.

        Deliberately hides the technical log: just thinking → Scene k → merging → done, plus a
        0–100 fill. Derived from the per-scene status map + lifecycle, so it needs no extra wiring.
        """
        with self._lock:
            scenes = dict(self.scenes)
            status = self.status
            scene_index = self.scene_index
        total = len(scenes) if scenes else (1 if scene_index is not None else 0)
        done = sum(1 for v in scenes.values() if v == S_DONE)
        rendering = sorted(i for i, v in scenes.items() if v == S_RENDERING)
        failed = sum(1 for v in scenes.values() if v == S_FAILED)

        if status == FAILED:
            phase, label, pct = "failed", "Something went wrong", 100
        elif status == DONE:
            phase, label, pct = "done", "Done", 100
        elif total == 0 or (done == 0 and not rendering and failed == 0):
            phase, label, pct = "thinking", "Thinking…", 8           # planning / style, no scene yet
        elif done >= total:
            phase, label, pct = "merging", "Merging…", 95            # all scenes rendered, stitching
        else:
            cur = rendering[0] if rendering else done
            phase = "rendering"
            label = f"Scene {cur + 1}" + (f" of {total}" if total > 1 else "")
            pct = 10 + int(80 * done / total)                        # fill the band 10→90 as scenes land
        return {"phase": phase, "label": label, "pct": pct,
                "done": done, "total": total, "scenes": scenes}

    @property
    def done(self) -> bool:
        return self.status in _TERMINAL

    # --- lifecycle (owned by the queue worker) ---
    def _mark_running(self) -> None:
        with self._lock:
            self.status = RUNNING
            self.started_at = self._now()

    def _mark_finished(self, status: str, *, error: str | None = None, result: Any = None) -> None:
        with self._lock:
            self.status = status
            self.error = error
            self.result = result
            self.finished_at = self._now()

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "project_id": self.project_id,
                "scene_index": self.scene_index,
                "status": self.status,
                "scenes": dict(self.scenes),
                "error": self.error,
                "event_count": len(self.events),
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }


class JobQueue:
    """Bounded background executor over `Job`s. `synchronous=True` runs inline (tests)."""

    def __init__(self, *, workers: int = 2, synchronous: bool = False,
                 now: Callable[[], float] = time.time) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._now = now
        self._synchronous = synchronous
        self._pool: ThreadPoolExecutor | None = (
            None if synchronous else ThreadPoolExecutor(max_workers=max(1, workers),
                                                        thread_name_prefix="lattice-job")
        )

    def submit(self, fn: Callable[[Job], Any], *, kind: str, project_id: str,
               scene_index: int | None = None) -> Job:
        """Register a job and run `fn(job)` (inline if synchronous, else on a worker thread).

        `fn` does the real work and may call `job.log(...)` / `job.set_scene(...)`. Its return
        value becomes `job.result`; any exception flips the job to FAILED (never propagates here).
        """
        job = Job(kind=kind, project_id=project_id, scene_index=scene_index, now=self._now)
        with self._lock:
            self._jobs[job.id] = job
        if self._synchronous:
            self._run(job, fn)
        else:
            assert self._pool is not None
            self._pool.submit(self._run, job, fn)
        return job

    @staticmethod
    def _run(job: Job, fn: Callable[[Job], Any]) -> None:
        job._mark_running()
        try:
            result = fn(job)
            job._mark_finished(DONE, result=result)
        except Exception as e:  # a failed render must never take the server down
            job.log(f"[error] {type(e).__name__}: {e}")
            job._mark_finished(FAILED, error=f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, *, project_id: str | None = None) -> list[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        if project_id is not None:
            jobs = [j for j in jobs if j.project_id == project_id]
        return sorted(jobs, key=lambda j: j.created_at)

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
