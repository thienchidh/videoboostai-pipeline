"""
modules/pipeline/audit.py — Structured per-run audit logger.

Writes runs/YYYY-MM-DD/{run_id}/audit.json with:
- Step timings (start/complete timestamps, duration_ms)
- API call latencies and costs
- Error messages with stack traces
- Credit usage per provider
- Crash-safe (try/finally flush on runner.run())

Usage:
    audit = AuditLogger(run_id=42, run_dir=Path("/path/to/run_dir"), config={...})
    audit.start_run()

    audit.start_step(step=1, name="TTS", scene_id=1)
    # ... do work ...
    audit.log_api_call(provider="minimax", model="speech-02-hd", latency_ms=500, cost_usd=0.001)
    audit.complete_step(step=1, status="success")

    audit.start_step(step=2, name="Image", scene_id=1)
    try:
        ...
    except Exception as e:
        audit.log_error(step=2, exc=e)
        audit.complete_step(step=2, status="failed")
        raise

    # On pipeline crash, flush is still called via try/finally in runner.run()
    audit.flush()
"""

import json
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from core.base_pipeline import log as pipeline_log


class AuditLogger:
    """Structured audit logger for a single pipeline run.

    Writes a single audit.json file to run_dir. All methods are idempotent —
    the file is only written on flush().
    """

    _STEP_NAMES = {
        1: "TTS",
        2: "Image",
        3: "Lipsync",
        4: "Crop",
        5: "Whisper",
        6: "Concat",
        7: "Watermark",
        8: "Subtitles",
        9: "Music",
        99: "Done",
    }

    def __init__(self, run_id: int, run_dir: Path, config: Optional[Dict[str, Any]] = None):
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self._started_at = self._now()
        self._completed_at: Optional[str] = None

        # Config snapshot
        self._config = config or {}

        # Steps list
        self._steps: List[Dict[str, Any]] = []

        # Per-provider credit totals
        self._credits_spent: Dict[str, float] = {}

        # Top-level errors
        self._errors: List[Dict[str, Any]] = []

        # Overall status
        self._status = "running"

        # Track current open step (for nested API call logging)
        self._current_step: Optional[int] = None

        # Lazily created run subdirectory
        self._audit_dir: Optional[Path] = None

    # ─── Public API ─────────────────────────────────────────

    def start_run(self) -> None:
        """Mark the audit as started. Creates audit subdirectory."""
        self._audit_dir = self.run_dir
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        pipeline_log(f"📋 Audit: run started, run_id={self.run_id}, dir={self._audit_dir}")

    def start_step(self, step: int, name: str, scene_id: Optional[int] = None) -> None:
        """Log the start of a step."""
        self._current_step = step
        self._steps.append({
            "step": step,
            "name": name,
            "scene_id": scene_id,
            "started_at": self._now(),
            "completed_at": None,
            "duration_ms": None,
            "api_calls": [],
            "errors": [],
            "status": "running",
        })

    def log_api_call(self, provider: str, model: str,
                     latency_ms: float,
                     cost_usd: float = 0.0,
                     extra: Optional[Dict[str, Any]] = None) -> None:
        """Record an API call within the current open step."""
        if not self._steps:
            return
        current = self._steps[-1]
        if current.get("status") == "running" and current.get("step") == self._current_step:
            api_call = {
                "provider": provider,
                "model": model,
                "latency_ms": latency_ms,
                "cost_usd": round(cost_usd, 6),
            }
            if extra:
                api_call.update(extra)
            current["api_calls"].append(api_call)

            # Accumulate credits
            self._credits_spent[provider] = round(
                self._credits_spent.get(provider, 0.0) + cost_usd, 6
            )

    def complete_step(self, step: int, status: str = "success",
                      scene_id: Optional[int] = None) -> None:
        """Mark the most recently started step as complete."""
        if not self._steps:
            return
        # Find the most recent step with matching step number
        for s in reversed(self._steps):
            if s["step"] == step and s.get("status") == "running":
                s["completed_at"] = self._now()
                s["duration_ms"] = self._duration_ms(s["started_at"], s["completed_at"])
                s["status"] = status
                if scene_id is not None:
                    s["scene_id"] = scene_id
                break
        if self._current_step == step:
            self._current_step = None

    def log_error(self, step: Optional[int] = None, exc: Optional[Exception] = None,
                  message: Optional[str] = None) -> None:
        """Log an error to the current step or to top-level errors."""
        error_entry = {
            "message": message or (str(exc) if exc else "unknown error"),
            "type": type(exc).__name__ if exc else "Error",
            "traceback": traceback.format_exc() if exc else None,
            "timestamp": self._now(),
        }

        if step is not None:
            # Find step with this step number
            for s in reversed(self._steps):
                if s["step"] == step:
                    s["errors"].append(error_entry)
                    if s["status"] == "running":
                        s["status"] = "failed"
                    break
        else:
            self._errors.append(error_entry)

    def log_pipeline_error(self, exc: Exception, context: str = "") -> None:
        """Log a top-level pipeline error (not tied to a specific step)."""
        self._errors.append({
            "context": context,
            "message": str(exc),
            "type": type(exc).__name__,
            "traceback": traceback.format_exc(),
            "timestamp": self._now(),
        })
        self._status = "failed"

    def complete_run(self, status: str = "success") -> None:
        """Mark the whole run as complete."""
        self._completed_at = self._now()
        self._status = status

    def flush(self) -> Optional[Path]:
        """Write the audit.json file to disk. Returns the path, or None on error."""
        try:
            self._completed_at = self._completed_at or self._now()

            # Finalize any still-running steps as failed
            for s in self._steps:
                if s.get("status") == "running":
                    s["status"] = "failed"
                    s["completed_at"] = s.get("completed_at") or self._now()
                    if not s.get("duration_ms"):
                        s["duration_ms"] = self._duration_ms(s["started_at"], s["completed_at"])

            # Compute total cost
            total_cost = round(sum(self._credits_spent.values()), 6)

            audit_data = {
                "run_id": str(self.run_id),
                "started_at": self._started_at,
                "completed_at": self._completed_at,
                "config": self._config,
                "steps": self._steps,
                "total_credits_spent": self._credits_spent,
                "total_cost_usd": total_cost,
                "errors": self._errors,
                "status": self._status,
            }

            audit_path = self._audit_dir / "audit.json"
            with open(audit_path, "w", encoding="utf-8") as f:
                json.dump(audit_data, f, ensure_ascii=False, indent=2)

            pipeline_log(f"📋 Audit: flushed to {audit_path}")
            return audit_path
        except Exception as e:
            pipeline_log(f"⚠️  Audit: flush failed: {e}")
            return None

    # ─── Context manager ───────────────────────────────────

    def __enter__(self):
        self.start_run()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.log_pipeline_error(exc_val, context=f"pipeline_runner.run()")
            self._status = "failed"
            self._completed_at = self._now()
        self.flush()
        return False

    # ─── Helpers ───────────────────────────────────────────

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    @staticmethod
    def _duration_ms(start: str, end: str) -> Optional[int]:
        try:
            s = datetime.fromisoformat(start.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end.replace("Z", "+00:00"))
            return int((e - s).total_seconds() * 1000)
        except Exception:
            return None

    # ─── Convenience step helpers ────────────────────────────

    def log_tts(self, scene_id: int, provider: str, model: str,
                latency_ms: float, cost_usd: float, status: str = "success") -> None:
        self.start_step(step=1, name="TTS", scene_id=scene_id)
        self.log_api_call(provider=provider, model=model, latency_ms=latency_ms, cost_usd=cost_usd)
        self.complete_step(step=1, status=status, scene_id=scene_id)

    def log_image(self, scene_id: int, provider: str, model: str,
                  latency_ms: float, cost_usd: float, status: str = "success") -> None:
        self.start_step(step=2, name="Image", scene_id=scene_id)
        self.log_api_call(provider=provider, model=model, latency_ms=latency_ms, cost_usd=cost_usd)
        self.complete_step(step=2, status=status, scene_id=scene_id)

    def log_lipsync(self, scene_id: int, provider: str, model: str,
                    latency_ms: float, cost_usd: float, status: str = "success") -> None:
        self.start_step(step=3, name="Lipsync", scene_id=scene_id)
        self.log_api_call(provider=provider, model=model, latency_ms=latency_ms, cost_usd=cost_usd)
        self.complete_step(step=3, status=status, scene_id=scene_id)
