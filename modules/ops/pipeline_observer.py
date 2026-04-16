#!/usr/bin/env python3
"""
modules/ops/pipeline_observer.py — FastAPI HTTP server for live pipeline run monitoring.

Endpoints:
  GET /health             — health check
  GET /runs               — list recent runs
  GET /runs/{run_id}      — detailed run status (scenes, steps, credits, errors)
  GET /runs/{run_id}/stream — SSE live status stream
  GET /                   — HTML dashboard

Usage:
  # Standalone
  python -m modules.ops.pipeline_observer --port 8080

  # Within pipeline (background thread)
  from modules.ops.pipeline_observer import PipelineObserver
  observer = PipelineObserver(port=8080, host="0.0.0.0")
  observer.start()   # starts in background thread
  # ... run pipeline ...
  observer.stop()
"""

import asyncio
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

# Add project root to path for imports
_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import db
from db import get_session
import db_models as models

logger = logging.getLogger(__name__)

# ─── Step definitions ────────────────────────────────────────────────────────────

STEP_NAMES = {
    1: "TTS",
    2: "Image",
    3: "Lipsync",
    4: "Crop",
    5: "Done",
}

STEP_LABELS = ["TTS", "Image", "Lipsync", "Crop", "Done"]

SCENE_STATUS_COLORS = {
    "pending": "#94a3b8",
    "running": "#3b82f6",
    "completed": "#22c55e",
    "failed": "#ef4444",
}


# ─── Dashboard HTML ──────────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Video Pipeline Observer</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f172a; color: #e2e8f0; min-height: 100vh; }
  header { background: #1e293b; padding: 16px 24px; border-bottom: 1px solid #334155;
           display: flex; align-items: center; justify-content: space-between; }
  header h1 { font-size: 18px; font-weight: 600; color: #f1f5f9; }
  .badge { background: #22c55e; color: #fff; font-size: 12px; padding: 2px 8px;
           border-radius: 12px; font-weight: 500; }
  .badge.running { background: #3b82f6; }
  .badge.failed { background: #ef4444; }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
  .refresh-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; }
  .refresh-bar span { font-size: 13px; color: #94a3b8; }
  .runs-grid { display: grid; gap: 16px; }
  .run-card { background: #1e293b; border-radius: 12px; padding: 20px;
              border: 1px solid #334155; }
  .run-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
  .run-title { font-size: 15px; font-weight: 600; }
  .run-meta { font-size: 12px; color: #94a3b8; }
  .progress-bar-wrap { background: #334155; border-radius: 8px; height: 8px;
                        margin: 8px 0; overflow: hidden; }
  .progress-bar { height: 100%; border-radius: 8px; transition: width 0.4s ease;
                  background: #3b82f6; }
  .progress-bar.done { background: #22c55e; }
  .progress-bar.failed { background: #ef4444; }
  .scenes-grid { display: grid; gap: 8px; margin-top: 12px; }
  .scene-row { display: flex; align-items: center; gap: 12px; background: #0f172a;
               border-radius: 8px; padding: 8px 12px; }
  .scene-num { font-size: 12px; font-weight: 600; color: #64748b; min-width: 60px; }
  .scene-status { font-size: 11px; font-weight: 500; padding: 2px 8px; border-radius: 10px; }
  .scene-status.pending { background: #334155; color: #94a3b8; }
  .scene-status.running { background: #1e40af; color: #93c5fd; }
  .scene-status.completed { background: #14532d; color: #86efac; }
  .scene-status.failed { background: #7f1d1d; color: #fca5a5; }
  .scene-steps { display: flex; gap: 4px; flex: 1; }
  .step-dot { width: 10px; height: 10px; border-radius: 50%%; background: #334155; }
  .step-dot.done { background: #22c55e; }
  .step-dot.active { background: #3b82f6; box-shadow: 0 0 6px #3b82f6; }
  .step-dot.error { background: #ef4444; }
  .step-labels { display: flex; gap: 4px; font-size: 10px; color: #64748b; }
  .credits { display: flex; gap: 16px; margin-top: 12px; flex-wrap: wrap; }
  .credit-chip { background: #334155; border-radius: 6px; padding: 4px 10px;
                 font-size: 12px; color: #94a3b8; }
  .credit-chip span { color: #f1f5f9; font-weight: 600; }
  .errors { margin-top: 12px; }
  .error-item { background: #7f1d1d; border-radius: 6px; padding: 8px 12px;
                font-size: 12px; color: #fca5a5; margin-top: 6px; }
  .empty { text-align: center; padding: 60px; color: #64748b; font-size: 14px; }
  .empty-icon { font-size: 40px; margin-bottom: 12px; }
  .no-scene-steps { font-size: 11px; color: #475569; }
  .controls { display: flex; gap: 8px; align-items: center; }
  button { background: #334155; color: #e2e8f0; border: 1px solid #475569;
           border-radius: 6px; padding: 6px 14px; cursor: pointer; font-size: 13px; }
  button:hover { background: #475569; }
  .reload-btn { background: #1e40af; border-color: #3b82f6; }
  .reload-btn:hover { background: #1e3a8a; }
  .api-count { font-size: 12px; color: #64748b; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%%; background: #22c55e; }
  .status-dot.offline { background: #ef4444; }
</style>
</head>
<body>
<header>
  <h1>🎬 Video Pipeline Observer</h1>
  <div class="controls">
    <span id="status-dot" class="status-dot"></span>
    <span id="last-updated" style="font-size:12px;color:#94a3b8;"></span>
    <button class="reload-btn" onclick="loadRuns()">↻ Reload</button>
    <select id="status-filter" onchange="loadRuns()" style="background:#334155;color:#e2e8f0;border:1px solid #475569;border-radius:6px;padding:6px;">
      <option value="">All</option>
      <option value="running">Running</option>
      <option value="completed">Completed</option>
      <option value="failed">Failed</option>
    </select>
  </div>
</header>
<div class="container">
  <div id="runs-container"></div>
</div>
<script>
let lastEtag = '';
let es = null;

async function loadRuns() {
  const filter = document.getElementById('status-filter').value;
  const url = filter ? `/runs?status=${filter}` : '/runs';
  try {
    const r = await fetch(url);
    const data = await r.json();
    renderRuns(data.runs || data);
    document.getElementById('status-dot').className = 'status-dot';
    document.getElementById('last-updated').textContent = 'Updated: ' + new Date().toLocaleTimeString();
  } catch(e) {
    document.getElementById('status-dot').className = 'status-dot offline';
    document.getElementById('runs-container').innerHTML = '<div class="empty"><div class="empty-icon">⚠️</div>Failed to load runs</div>';
  }
}

function renderRuns(runs) {
  const c = document.getElementById('runs-container');
  if (!runs.length) {
    c.innerHTML = '<div class="empty"><div class="empty-icon">📭</div>No runs found</div>';
    return;
  }
  c.innerHTML = '<div class="runs-grid">' + runs.map(r => renderRun(r)).join('') + '</div>';
}

function renderRun(run) {
  const pct = run.total_scenes > 0
    ? Math.round((run.completed_scenes / run.total_scenes) * 100) : 0;
  const statusLabel = {running:'Running',completed:'Done',failed:'Failed'}[run.status] || run.status;
  const pClass = run.status === 'completed' ? 'done' : run.status === 'failed' ? 'failed' : '';
  const scenes = run.scenes || [];
  const credits = run.credits_by_provider || {};
  const creditsHtml = Object.entries(credits).map(([k,v]) =>
    `<div class="credit-chip">${k}: <span>$${v.toFixed(3)}</span></div>`).join('');
  const errors = (run.errors || []).map(e =>
    `<div class="error-item">Scene ${e.scene_index}: ${e.message || 'Unknown error'}</div>`).join('');
  const startTime = run.started_at ? new Date(run.started_at).toLocaleString() : 'N/A';
  const duration = run.completed_at && run.started_at
    ? Math.round((new Date(run.completed_at) - new Date(run.started_at)) / 1000) + 's'
    : run.started_at ? Math.round((Date.now() - new Date(run.started_at)) / 1000) + 's (ongoing)' : 'N/A';

  return `<div class="run-card" onclick="toggleScenes(this)">
    <div class="run-header">
      <span class="badge ${run.status}">${statusLabel}</span>
      <span class="run-title">Run #${run.id}</span>
      <span class="run-meta">${startTime} · ${duration}</span>
      ${run.api_calls_count != null ? `<span class="api-count">${run.api_calls_count} API calls</span>` : ''}
    </div>
    <div class="progress-bar-wrap">
      <div class="progress-bar ${pClass}" style="width:${pct}%"></div>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:12px;color:#94a3b8;margin-top:4px;">
      <span>${run.completed_scenes || 0} / ${run.total_scenes || 0} scenes</span>
      <span>${pct}%</span>
    </div>
    ${creditsHtml ? `<div class="credits">${creditsHtml}</div>` : ''}
    ${errors ? `<div class="errors">${errors}</div>` : ''}
    <div class="scenes-grid" style="display:none;">
      ${scenes.length ? scenes.map(s => renderScene(s)).join('') : '<div style="font-size:12px;color:#475569;padding:8px;">No scene data</div>'}
    </div>
  </div>`;
}

function renderScene(s) {
  const labels = ['TTS', 'Image', 'Lipsync', 'Crop', 'Done'];
  const steps = s.steps || [];
  const dots = labels.map((lbl, i) => {
    const stepNum = i + 1;
    const done = steps.includes(stepNum);
    const cls = done ? 'done' : '';
    return `<div class="step-dot ${cls}" title="${lbl}"></div>`;
  }).join('');
  const labelDots = labels.map((lbl, i) =>
    `<div style="text-align:center;font-size:9px;color:#475569;width:10px;">${lbl[0]}</div>`).join('');
  return `<div class="scene-row">
    <span class="scene-num">Scene ${s.scene_index}</span>
    <span class="scene-status ${s.status || 'pending'}">${s.status || 'pending'}</span>
    <div class="scene-steps" title="${steps.map(s=>labels[s-1]).join(', ') || 'No steps completed'}">${dots}</div>
  </div>`;
}

function toggleScenes(card) {
  const grid = card.querySelector('.scenes-grid');
  grid.style.display = grid.style.display === 'none' ? 'block' : 'none';
}

function connectSSE() {
  if (es) es.close();
  // Connect to last active run's SSE stream
  fetch('/runs?status=running')
    .then(r => r.json())
    .then(data => {
      const runs = data.runs || data;
      if (runs.length) {
        es = new EventSource(`/runs/${runs[0].id}/stream`);
        es.onmessage = ev => {
          const d = JSON.parse(ev.data);
          if (d.type === 'ping') return;
          // Re-render just the updated run card
          const cards = document.querySelectorAll('.run-card');
          cards.forEach(c => {
            const title = c.querySelector('.run-title');
            if (title && title.textContent.includes('#' + d.run_id)) {
              c.outerHTML = renderRun(d);
            }
          });
        };
        es.onerror = () => { es.close(); };
      }
    }).catch(() => {});
}

// Poll every 5s + optional SSE
loadRuns();
setInterval(loadRuns, 5000);
connectSSE();
</script>
</body>
</html>"""


# ─── FastAPI App ─────────────────────────────────────────────────────────────────

_FASTAPI_AVAILABLE = False
_SSEAvailable = False
app = None  # always defined; None when FastAPI is unavailable

try:
    from fastapi import FastAPI, Response, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    _FASTAPI_AVAILABLE = True
    try:
        import sse_starlette.sse as sse_module
        _SSEAvailable = True
    except ImportError:
        logger.info("sse_starlette not available, using StreamingResponse fallback")
except ImportError:
    logger.warning("FastAPI not available, running in fallback mode")

# ─── Module-level run state (in-memory) ────────────────────────────────────────
# Thread-safe in-memory registry of active runs
_import_lock = __import__("threading").Lock()
_active_runs: Dict[int, dict] = {}   # run_id -> {status, current_step, completed_scenes, total_scenes, errors[], started_at, updated_at}


def register_run(run_id: int, total_scenes: int = 0) -> None:
    """Register a run in the observer's in-memory state."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _active_runs[run_id] = {
        "id": run_id,
        "status": "running",
        "current_step": "init",
        "completed_scenes": 0,
        "total_scenes": total_scenes,
        "errors": [],
        "started_at": now,
        "updated_at": now,
        "credits_by_provider": {},
        "scene_durations": [],
        "api_call_counts": {"success": 0, "failure": 0},
        "start_time": time.time(),
    }
    # Persist to DB: update total_scenes on the video_run record
    try:
        db.update_video_run(run_id, total_scenes=total_scenes)
    except Exception:
        pass
    _broadcast_run(run_id, _active_runs.get(run_id, {}))


def update_run_progress(run_id: int, **kwargs) -> None:
    """Update in-memory run state and persist to DB.

    Allowed kwargs: status, current_step, completed_scenes, total_scenes, error (adds to errors list)
    """
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _import_lock:
        if run_id not in _active_runs:
            _active_runs[run_id] = {
                "id": run_id, "status": "running", "current_step": "init",
                "completed_scenes": 0, "total_scenes": 0,
                "errors": [], "started_at": now, "updated_at": now,
                "credits_by_provider": {},
            }
        run = _active_runs[run_id]

        if "status" in kwargs:
            run["status"] = kwargs["status"]
        if "current_step" in kwargs:
            run["current_step"] = kwargs["current_step"]
        if "completed_scenes" in kwargs:
            run["completed_scenes"] = kwargs["completed_scenes"]
        if "total_scenes" in kwargs:
            run["total_scenes"] = kwargs["total_scenes"]
        if "error" in kwargs:
            run["errors"].append(kwargs["error"])
        run["updated_at"] = now

    # Build broadcast payload — include avg_scene_duration if we have data
    broadcast_data = dict(run)
    if run.get("scene_durations"):
        durations = run["scene_durations"]
        broadcast_data["avg_scene_duration_s"] = sum(durations) / len(durations)

    # Persist to DB
    try:
        db_kwargs = {}
        for key in ["status", "completed_scenes"]:
            if key in kwargs:
                db_kwargs[key] = kwargs[key]
        if db_kwargs:
            db.update_video_run(run_id, **db_kwargs)
    except Exception:
        pass

    _broadcast_run(run_id, broadcast_data)


def _broadcast_run(run_id: int, data: dict) -> None:
    """Broadcast updated run data to all SSE subscribers.

    This is a no-op if SSE clients dict doesn't exist yet (app not started).
    """
    pass  # Will be overridden by FastAPI app's _broadcast_run when app is started


def record_scene_completed(run_id: int, scene_id: int, duration: float) -> None:
    """Record a scene completion with its duration in seconds."""
    with _import_lock:
        if run_id in _active_runs:
            run = _active_runs[run_id]
            run.setdefault("scene_durations", []).append(duration)
            run["updated_at"] = datetime.now(timezone.utc).isoformat()
            _broadcast_run(run_id, dict(run))


def record_api_call(run_id: int, provider: str, success: bool, duration_ms: float) -> None:
    """Record an API call outcome for a run."""
    with _import_lock:
        if run_id in _active_runs:
            run = _active_runs[run_id]
            counts = run.setdefault("api_call_counts", {"success": 0, "failure": 0})
            key = "success" if success else "failure"
            counts[key] = counts.get(key, 0) + 1
            run["updated_at"] = datetime.now(timezone.utc).isoformat()
            _broadcast_run(run_id, {
                "type": "api_call",
                "provider": provider,
                "success": success,
                "duration_ms": duration_ms,
            })


if _FASTAPI_AVAILABLE:
    app = FastAPI(title="Video Pipeline Observer", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── In-memory registry of active SSE clients ───────────────────────────
    _sse_clients: Dict[int, list] = {}  # run_id -> [queue.put, ...]

    def _broadcast_run(run_id: int, data: dict):
        """Push updated run data to all SSE subscribers of this run."""
        if run_id not in _sse_clients:
            return
        import queue
        msg = json.dumps(data)
        for q in _sse_clients[run_id]:
            try:
                q.put_nowait({"event": "run_update", "data": msg})
            except Exception:
                pass

    def _register_sse_client(run_id: int, q):
        if run_id not in _sse_clients:
            _sse_clients[run_id] = []
        _sse_clients[run_id].append(q)

    def _unregister_sse_client(run_id: int, q):
        if run_id in _sse_clients:
            try:
                _sse_clients[run_id].remove(q)
            except ValueError:
                pass

    # ── Routes ─────────────────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "pipeline-observer", "ts": datetime.now(timezone.utc).isoformat()}

    @app.get("/runs", response_class=JSONResponse)
    async def list_runs(status: str = None, limit: int = 20):
        try:
            runs = db.list_recent_runs(limit=limit, status=status or None)
            return {"runs": runs, "count": len(runs)}
        except Exception as e:
            logger.error(f"Error listing runs: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/runs/{run_id}", response_class=JSONResponse)
    async def get_run(run_id: int):
        try:
            details = db.get_run_details(run_id)
            if details is None:
                return JSONResponse({"error": "Run not found"}, status_code=404)
            return details
        except Exception as e:
            logger.error(f"Error getting run {run_id}: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/runs/{run_id}/stream")
    async def stream_run(run_id: int, request: Request):
        """Server-Sent Events stream for live run updates."""

        # Verify run exists
        run = db.get_video_run(run_id)
        if run is None:
            return JSONResponse({"error": "Run not found"}, status_code=404)

        import queue
        client_queue = queue.Queue()
        _register_sse_client(run_id, client_queue)

        async def event_generator():
            try:
                # Send initial state
                details = db.get_run_details(run_id)
                if details:
                    yield {"event": "init", "data": json.dumps(details)}
                # Stream updates until client disconnects
                last_completed = details.get("completed_scenes", 0) if details else 0
                last_status = details.get("status", "running") if details else "running"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = client_queue.get(timeout=5)
                        yield msg
                    except queue.Empty:
                        # Send keepalive + poll DB for changes
                        current = db.get_run_details(run_id)
                        if current:
                            # Detect changes
                            if (current.get("completed_scenes") != last_completed or
                                    current.get("status") != last_status):
                                last_completed = current.get("completed_scenes", 0)
                                last_status = current.get("status", "running")
                                yield {"event": "run_update", "data": json.dumps(current)}
                            else:
                                yield {"event": "ping", "data": "{}"}
                        else:
                            break
            finally:
                _unregister_sse_client(run_id, client_queue)

        if _SSEAvailable:
            from sse_starlette.sse import EventServerResponse
            return EventServerResponse(event_generator())
        else:
            # Fallback: StreamingResponse with text/event-stream
            from fastapi.responses import StreamingResponse
            async def text_stream():
                async for msg in event_generator():
                    yield f"data: {msg.get('data', '{}')}\n\n".encode()
            return StreamingResponse(text_stream(), media_type="text/event-stream")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        return DASHBOARD_HTML

    @app.get("/runs/{run_id}/steps", response_class=JSONResponse)
    async def get_run_steps(run_id: int):
        """Return per-scene step progress from checkpoint data."""
        try:
            details = db.get_run_details(run_id)
            if details is None:
                return JSONResponse({"error": "Run not found"}, status_code=404)
            scenes = details.get("scenes", [])
            # Enrich each scene with step progress from checkpoints
            with get_session() as session:
                scene_ids = [s["id"] for s in scenes]
                checkpoints = session.query(models.SceneCheckpoint)\
                    .filter(models.SceneCheckpoint.scene_id.in_([f"run_{run_id}_scene_{sid}" for sid in scene_ids]))\
                    .order_by(models.SceneCheckpoint.step).all()
                cp_map: Dict[str, set] = {}
                for cp in checkpoints:
                    if cp.scene_id not in cp_map:
                        cp_map[cp.scene_id] = set()
                    cp_map[cp.scene_id].add(cp.step)
            result = []
            for s in scenes:
                scene_key = f"run_{run_id}_scene_{s['id']}"
                steps_done = list(cp_map.get(scene_key, set()))
                result.append({**s, "steps": steps_done})
            return {**details, "scenes": result}
        except Exception as e:
            logger.error(f"Error getting steps for run {run_id}: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)


# ─── Observer Server (runs in background thread) ────────────────────────────────

class PipelineObserver:
    """Lightweight HTTP server running in a background thread.

    Args:
        host:     Bind address (default 0.0.0.0)
        port:     Bind port (default 8080)
        daemon:   If True, server stops when main process exits (default True)
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8080, daemon: bool = True):
        self.host = host
        self.port = port
        self.daemon = daemon
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        """Start the observer HTTP server in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Observer already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_server, daemon=self.daemon, name="PipelineObserver")
        self._thread.start()
        logger.info(f"Pipeline observer started on {self.host}:{self.port}")

    def stop(self):
        """Stop the observer server."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Pipeline observer stopped")

    def _run_server(self):
        import socket
        # Find available port if default is taken
        actual_port = self.port
        try:
            sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, actual_port))
            sock.close()
        except OSError:
            # Port in use, let uvicorn pick a free port
            actual_port = 0

        # Try uvicorn if available
        try:
            import uvicorn
            from importlib.resources import as_file
            uvicorn.run(
                app,
                host=self.host,
                port=actual_port if actual_port else 8080,
                log_level="info",
                access_log=False,
            )
        except ImportError:
            # Fallback: use wsgiref simple server
            logger.warning("uvicorn not available, using wsgiref fallback")
            from wsgiref.simple_server import make_server

            def wsgi_app(environ, start_response):
                path = environ.get("PATH_INFO", "/")
                method = environ.get("REQUEST_METHOD", "GET")

                if path == "/health":
                    status = "200 OK"
                    body = json.dumps({"status": "ok", "service": "pipeline-observer"}).encode()
                    start_response(status, [("Content-Type", "application/json")])
                    return [body]

                if path == "/runs":
                    status = "200 OK"
                    status_filter = None
                    qs = environ.get("QUERY_STRING", "")
                    for param in qs.split("&"):
                        if param.startswith("status="):
                            status_filter = param.split("=", 1)[1] or None
                    # Merge in-memory active runs with DB runs
                    runs = db.list_recent_runs(limit=20, status=status_filter)
                    body = json.dumps({"runs": runs}).encode()
                    start_response(status, [("Content-Type", "application/json")])
                    return [body]

                # /runs/{run_id}
                if path.startswith("/runs/"):
                    parts = path.split("/")
                    if len(parts) == 3 and parts[2].isdigit():
                        run_id = int(parts[2])
                        details = db.get_run_details(run_id)
                        if details is None:
                            status = "404 Not Found"
                            body = json.dumps({"error": "Run not found"}).encode()
                        else:
                            status = "200 OK"
                            body = json.dumps(details).encode()
                        start_response(status, [("Content-Type", "application/json")])
                        return [body]

                if path == "/":
                    status = "200 OK"
                    body = DASHBOARD_HTML.encode()
                    start_response(status, [("Content-Type", "text/html")])
                    return [body]

                status = "404 Not Found"
                body = b"Not Found"
                start_response(status, [])
                return [body]

            srv = make_server(self.host, actual_port or 8080, wsgi_app)
            srv.serve_forever()
