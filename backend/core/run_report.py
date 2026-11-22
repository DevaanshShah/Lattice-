"""Durable, structured diagnostics for one generated video run."""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any, Callable


def classify_exception(exc: Exception, stage: str) -> str:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if isinstance(exc, PermissionError):
        return "filesystem"
    if "layout" in name or "clipped" in message or "overlaps" in message:
        return "layout"
    if "validation" in name or "invalid" in message:
        return "content_contract"
    if "timeout" in name or "timed out" in message:
        return "timeout"
    if "playwright" in name or "chrome" in message or "chromium" in message:
        return "browser_infrastructure"
    if "ffmpeg" in message or "ffprobe" in message or stage in {"clip", "scene_stitch", "stitch"}:
        return "media"
    if stage == "narration":
        return "narration"
    if stage in {"lesson_plan", "visual_plan"}:
        return "model_or_plan"
    return "runtime"


class RunReport:
    def __init__(self, out_dir: str | Path, *, topic: str, recipe: str,
                 log: Callable[[str], None] | None = None) -> None:
        self.path = Path(out_dir) / "run_report.json"
        self.started_at = time.time()
        self.data: dict[str, Any] = {
            "topic": topic,
            "recipe": recipe,
            "status": "running",
            "started_at": round(self.started_at, 3),
            "finished_at": None,
            "elapsed_s": None,
            "events": [],
        }
        self.log = log or (lambda _message: None)
        self._stage_started: dict[tuple, float] = {}
        self._write()

    def event(self, stage: str, status: str, *, scene: str | None = None,
              beat: str | None = None, attempt: int | None = None,
              category: str | None = None, detail: str | None = None,
              issues: list[str] | None = None, action: str | None = None,
              evidence: dict | None = None, traceback_text: str | None = None) -> None:
        now = time.time()
        key = (stage, scene, beat, attempt)
        row = {
            "ts": round(now, 3),
            "elapsed_s": round(now - self.started_at, 3),
            "stage": stage,
            "status": status,
        }
        if status == "start":
            self._stage_started[key] = now
        elif key in self._stage_started:
            row["duration_s"] = round(now - self._stage_started.pop(key), 3)
        optional = {
            "scene": scene, "beat": beat, "attempt": attempt, "category": category,
            "detail": detail[:2000] if detail else None, "issues": issues, "action": action,
            "evidence": evidence,
            "traceback": traceback_text[-4000:] if traceback_text else None,
        }
        row.update({key: value for key, value in optional.items() if value is not None})
        self.data["events"].append(row)
        self._write()
        suffix = f" · {scene}" if scene else ""
        suffix += f"/{beat}" if beat else ""
        self.log(f"[browser:{stage}] {status}{suffix}" + (f": {detail}" if detail else ""))

    def failure(self, stage: str, exc: Exception, **context: Any) -> None:
        self.data["status"] = "failed"
        trace = traceback.format_exc(limit=6)
        if trace.strip() == "NoneType: None":
            trace = ""
        self.event(stage, "failed", category=classify_exception(exc, stage),
                   detail=f"{type(exc).__name__}: {exc}", traceback_text=trace, **context)
        self._finish_timestamp()

    def complete(self, *, artifact: str | Path | None = None) -> None:
        self.data["status"] = "complete"
        self.event("run", "complete", detail=str(artifact) if artifact else None)
        self._finish_timestamp()

    def planned(self) -> None:
        self.data["status"] = "planned"
        self.event("run", "planned")
        self._finish_timestamp()

    def _finish_timestamp(self) -> None:
        finished = time.time()
        self.data["finished_at"] = round(finished, 3)
        self.data["elapsed_s"] = round(finished - self.started_at, 3)
        self._write()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        for attempt in range(5):
            try:
                temp.replace(self.path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
