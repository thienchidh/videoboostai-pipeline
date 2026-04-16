#!/usr/bin/env python3
"""
db.py - PostgreSQL database module for video pipeline state management.
Uses SQLAlchemy 2.0 with sync engine + sessionmaker.
"""
import logging
import os
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

from datetime import datetime, date, timezone, timedelta
from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import sessionmaker, Session

from modules.pipeline.exceptions import MissingConfigError
from modules.pipeline.db_config import DatabaseConnectionConfig
import db_models as models

logger = logging.getLogger(__name__)

# SQLAlchemy engine + session factory (set by configure())
_engine = None
_SessionFactory = None
_config: DatabaseConnectionConfig = None


def configure(config: DatabaseConnectionConfig):
    """Configure database connection from a DatabaseConnectionConfig Pydantic model.

    Raises:
        TypeError: If config is not a DatabaseConnectionConfig instance.
    """
    global _engine, _SessionFactory, _config

    if not isinstance(config, DatabaseConnectionConfig):
        raise TypeError(
            f"db.configure() requires a DatabaseConnectionConfig Pydantic model, "
            f"got {type(config).__name__} instead. "
            f"Use TechnicalConfig.load().storage.database or construct DatabaseConnectionConfig(...) directly."
        )

    _config = config
    connection_string = (
        f"postgresql://{config.user}:{config.password}@"
        f"{config.host}:{config.port}/{config.name}"
    )
    _engine = create_engine(connection_string, pool_pre_ping=True)
    _SessionFactory = sessionmaker(bind=_engine)
    logger.info(f"Database configured: {config.host}:{config.port}/{config.name}")


def get_config() -> DatabaseConnectionConfig:
    """Return the current database config. Raises if not yet configured."""
    if _config is None:
        raise RuntimeError("Database not configured. Call db.configure() first.")
    return _config


def _ensure_configured():
    """Ensure configure() has been called before any DB operation."""
    if _SessionFactory is None:
        # Auto-configure with defaults from environment or hardcoded fallbacks
        default_config = DatabaseConnectionConfig(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            name=os.getenv("POSTGRES_DB", "videopipeline"),
            user=os.getenv("POSTGRES_USER", "videopipeline"),
            password=os.getenv("POSTGRES_PASSWORD", "videopipeline123"),
        )
        configure(default_config)


@contextmanager
def get_session() -> Session:
    """Context manager for SQLAlchemy sessions. Commits on success, rolls back on exception."""
    _ensure_configured()
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Alias for backward compatibility
get_db = get_session


# ─── init_db ─────────────────────────────────────────────────────────

def init_db():
    """Initialize database schema using SQLAlchemy models (creates all tables)."""
    _ensure_configured()
    models.Base.metadata.create_all(_engine)


def init_pgvector():
    """Enable pgvector extension. Must be called BEFORE init_db() to enable vector type."""
    _ensure_configured()
    from sqlalchemy import text
    with get_session() as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        session.commit()


def init_db_full():
    """Init pgvector extension then create all tables."""
    init_pgvector()
    init_db()


# ─── Project Operations ──────────────────────────────────────────────

def create_project(name: str, config_file: str = None, description: str = None) -> int:
    """Create a new project, return project id."""
    with get_session() as session:
        project = models.Project(
            name=name,
            config_file=config_file,
            description=description,
        )
        session.add(project)
        session.flush()
        return project.id


def get_or_create_project(name: str, config_file: str = None) -> int:
    """Get existing project by name or create new one. Returns project id."""
    assert name is not None and name != "", "project name must not be null or empty"
    with get_session() as session:
        existing = session.query(models.Project).filter_by(name=name).first()
        if existing:
            return existing.id
        project = models.Project(name=name, config_file=config_file)
        session.add(project)
        session.flush()
        return project.id


def get_project(project_id: int) -> Optional[Dict]:
    """Get project by id, returns dict."""
    with get_session() as session:
        p = session.query(models.Project).filter_by(id=project_id).first()
        if p:
            return _project_to_dict(p)
        return None


def _project_to_dict(p: models.Project) -> Dict:
    return {
        "id": p.id,
        "name": p.name,
        "config_file": p.config_file,
        "description": p.description,
        "status": p.status,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


# ─── Video Run Operations ────────────────────────────────────────────

def start_video_run(project_id: int, config_name: str) -> int:
    """Start a new video run, return run id."""
    assert project_id is not None and project_id != "", "project_id must not be null or empty"
    with get_session() as session:
        run = models.VideoRun(
            project_id=project_id,
            config_snapshot={"config_file": config_name},
            status="running",
        )
        session.add(run)
        session.flush()
        return run.id


def complete_video_run(run_id: int, status: str = "completed"):
    with get_session() as session:
        run = session.query(models.VideoRun).filter_by(id=run_id).first()
        if run:
            run.status = status
            run.completed_at = datetime.now(timezone.utc)


def fail_video_run(run_id: int, error: str = None):
    with get_session() as session:
        run = session.query(models.VideoRun).filter_by(id=run_id).first()
        if run:
            run.status = "failed"
            run.completed_at = datetime.now(timezone.utc)


def mark_stale_runs_failed(threshold_seconds: int = 7200) -> int:
    """Mark runs stuck in 'in_progress' for too long as failed.

    Args:
        threshold_seconds: Runs in_progress longer than this are considered stale.
    Returns:
        Number of runs marked as failed.
    """
    with get_session() as session:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=threshold_seconds)
        stale = session.query(models.VideoRun).filter(
            models.VideoRun.status == "in_progress",
            models.VideoRun.started_at < cutoff,
        )
        count = stale.count()
        if count > 0:
            stale.update({"status": "failed", "completed_at": datetime.now(timezone.utc)})
        return count


def create_video_run(project_id: int, run_dir: str, config_snapshot: dict = None,
                     total_scenes: int = 0) -> int:
    with get_session() as session:
        run = models.VideoRun(
            project_id=project_id,
            run_dir=run_dir,
            config_snapshot=config_snapshot,
            total_scenes=total_scenes,
            status="running",
        )
        session.add(run)
        session.flush()
        return run.id


def update_video_run(run_id: int, **kwargs):
    """Update video run fields. Allowed: status, completed_scenes, total_cost, output_video, caption, completed_at."""
    allowed = ["status", "completed_scenes", "total_cost", "output_video", "caption", "completed_at"]
    with get_session() as session:
        run = session.query(models.VideoRun).filter_by(id=run_id).first()
        if not run:
            return
        for k, v in kwargs.items():
            if k in allowed:
                setattr(run, k, v)


def get_video_run(run_id: int) -> Optional[Dict]:
    with get_session() as session:
        run = session.query(models.VideoRun).filter_by(id=run_id).first()
        return _video_run_to_dict(run) if run else None


def get_runs_by_project(project_id: int) -> List[Dict]:
    with get_session() as session:
        runs = session.query(models.VideoRun).filter_by(project_id=project_id)\
            .order_by(models.VideoRun.started_at.desc()).all()
        return [_video_run_to_dict(r) for r in runs]


def list_recent_runs(limit: int = 20, status: str = None) -> List[Dict]:
    """List recent video runs across all projects.

    Args:
        limit: Maximum number of runs to return (default 20)
        status: Optional filter by status (e.g. 'running', 'completed', 'failed')

    Returns:
        List of run dicts ordered by started_at desc.
    """
    with get_session() as session:
        query = session.query(models.VideoRun)
        if status:
            query = query.filter_by(status=status)
        runs = query.order_by(models.VideoRun.started_at.desc()).limit(limit).all()
        return [_video_run_to_dict(r) for r in runs]


def get_run_details(run_id: int) -> Optional[Dict]:
    """Get detailed run info including scenes, cost breakdown, and API call summary.

    Args:
        run_id: The video run ID

    Returns:
        Dict with run info + 'scenes' list + 'credits_by_provider' dict.
    """
    with get_session() as session:
        run = session.query(models.VideoRun).filter_by(id=run_id).first()
        if not run:
            return None

        scenes = session.query(models.Scene).filter_by(run_id=run_id)\
            .order_by(models.Scene.scene_index).all()

        # Aggregate credits by provider from api_calls
        api_calls = session.query(models.APICall).filter_by(run_id=run_id).all()
        credits_by_provider: Dict[str, int] = {}
        for call in api_calls:
            credits_by_provider[call.provider] = \
                credits_by_provider.get(call.provider, 0) + call.cost

        # Collect error messages from scenes
        errors = [
            {"scene_index": s.scene_index, "message": s.error_message}
            for s in scenes if s.error_message
        ]

        return {
            **_video_run_to_dict(run),
            "scenes": [_scene_to_dict(s) for s in scenes],
            "credits_by_provider": {
                p: cents / 100 for p, cents in credits_by_provider.items()
            },
            "errors": errors,
            "api_calls_count": len(api_calls),
        }


def _video_run_to_dict(r: models.VideoRun) -> Dict:
    return {
        "id": r.id,
        "project_id": r.project_id,
        "run_dir": r.run_dir,
        "config_snapshot": r.config_snapshot,
        "status": r.status,
        "total_scenes": r.total_scenes,
        "completed_scenes": r.completed_scenes,
        "total_cost": r.total_cost,
        "output_video": r.output_video,
        "caption": r.caption,
        "started_at": r.started_at,
        "completed_at": r.completed_at,
    }


# ─── Scene Operations ────────────────────────────────────────────────

def create_scene(run_id: int, scene_index: int, script: str = None,
                 characters: list = None, background: str = None) -> int:
    with get_session() as session:
        scene = models.Scene(
            run_id=run_id,
            scene_index=scene_index,
            script=script,
            characters=characters,
            background=background,
            status="pending",
        )
        session.add(scene)
        session.flush()
        return scene.id


def update_scene(scene_id: int, **kwargs):
    """Update scene fields. Allowed: status, tts_audio, image_path, lipsync_video, cost, error_message, completed_at."""
    allowed = ["status", "tts_audio", "image_path", "lipsync_video", "cost",
               "error_message", "completed_at"]
    with get_session() as session:
        scene = session.query(models.Scene).filter_by(id=scene_id).first()
        if not scene:
            return
        for k, v in kwargs.items():
            if k in allowed:
                setattr(scene, k, v)


def get_scene(scene_id: int) -> Optional[Dict]:
    with get_session() as session:
        scene = session.query(models.Scene).filter_by(id=scene_id).first()
        return _scene_to_dict(scene) if scene else None


def get_scenes_by_run(run_id: int) -> List[Dict]:
    with get_session() as session:
        scenes = session.query(models.Scene).filter_by(run_id=run_id)\
            .order_by(models.Scene.scene_index).all()
        return [_scene_to_dict(s) for s in scenes]


def _scene_to_dict(s: models.Scene) -> Dict:
    return {
        "id": s.id,
        "run_id": s.run_id,
        "scene_index": s.scene_index,
        "script": s.script,
        "characters": s.characters,
        "background": s.background,
        "tts_audio": s.tts_audio,
        "tts_voice": s.tts_voice,
        "image_path": s.image_path,
        "image_prompt": s.image_prompt,
        "lipsync_video": s.lipsync_video,
        "status": s.status,
        "error_message": s.error_message,
        "cost": s.cost,
        "created_at": s.created_at,
        "completed_at": s.completed_at,
    }


# ─── Scene Checkpoint Operations ───────────────────────────────────

# Step constants matching SceneCheckpoint model
CHECKPOINT_STEPS = {
    "tts": 1,
    "image": 2,
    "lipsync": 3,
    "crop": 4,
    "done": 5,
}
STEP_NAMES = {v: k for k, v in CHECKPOINT_STEPS.items()}


def save_checkpoint(scene_id: str, step: int, output_path: str = None) -> None:
    """Save (upsert) a checkpoint for a scene step.

    Args:
        scene_id: Unique scene identifier, e.g. "run_42_scene_3"
        step: Step number (1=tts, 2=image, 3=lipsync, 4=crop, 5=done)
        output_path: Absolute path to the step's output file
    """
    with get_session() as session:
        existing = session.query(models.SceneCheckpoint).filter_by(
            scene_id=scene_id, step=step
        ).first()
        if existing:
            existing.output_path = output_path
            existing.completed_at = datetime.now(timezone.utc)
        else:
            cp = models.SceneCheckpoint(
                scene_id=scene_id,
                step=step,
                output_path=output_path,
            )
            session.add(cp)


def load_checkpoint(scene_id: str) -> Optional[Dict]:
    """Load the highest completed checkpoint for a scene.

    Returns:
        Dict with keys {step, output_path, completed_at} for the highest completed step,
        or None if no checkpoint exists.
    """
    with get_session() as session:
        row = session.query(models.SceneCheckpoint).filter_by(scene_id=scene_id)\
            .order_by(models.SceneCheckpoint.step.desc()).first()
        if not row:
            return None
        return {
            "step": row.step,
            "output_path": row.output_path,
            "completed_at": row.completed_at,
        }


def get_checkpoint_for_step(scene_id: str, step: int) -> Optional[Dict]:
    """Check if a specific step has a completed checkpoint."""
    with get_session() as session:
        row = session.query(models.SceneCheckpoint).filter_by(
            scene_id=scene_id, step=step
        ).first()
        if not row:
            return None
        return {
            "step": row.step,
            "output_path": row.output_path,
            "completed_at": row.completed_at,
        }


def clear_checkpoints(scene_id: str) -> None:
    """Delete all checkpoints for a scene (used when forcing a full re-run)."""
    with get_session() as session:
        session.query(models.SceneCheckpoint).filter_by(scene_id=scene_id).delete()


def get_next_incomplete_step(scene_id: str) -> int:
    """Return the next step number that needs to run (1-based), or 1 if no checkpoints exist.

    This is the main resume helper: call after a crash to know where to continue.
    """
    cp = load_checkpoint(scene_id)
    if cp is None:
        return 1
    # If completed step is "done" (5), scene is fully complete — return 99 to skip
    if cp["step"] >= 5:
        return 99
    return cp["step"] + 1


# ─── API Call Operations ─────────────────────────────────────────────

def log_api_call(run_id: int, scene_id: int, provider: str,
                 request_payload: dict = None, response_payload: dict = None,
                 status_code: int = None, cost: float = 0, duration_ms: int = None,
                 error: str = None) -> int:
    with get_session() as session:
        call = models.APICall(
            run_id=run_id,
            scene_id=scene_id,
            provider=provider,
            request_payload=request_payload,
            response_payload=response_payload,
            status_code=status_code,
            cost=int(cost * 100) if cost else 0,
            duration_ms=duration_ms,
            error=error,
        )
        session.add(call)
        session.flush()
        return call.id


def get_api_calls_by_run(run_id: int) -> List[Dict]:
    with get_session() as session:
        calls = session.query(models.APICall).filter_by(run_id=run_id)\
            .order_by(models.APICall.created_at).all()
        return [_api_call_to_dict(c) for c in calls]


def _api_call_to_dict(c: models.APICall) -> Dict:
    return {
        "id": c.id,
        "run_id": c.run_id,
        "scene_id": c.scene_id,
        "provider": c.provider,
        "endpoint": c.endpoint,
        "request_payload": c.request_payload,
        "response_payload": c.response_payload,
        "status_code": c.status_code,
        "cost": c.cost,
        "duration_ms": c.duration_ms,
        "error": c.error,
        "created_at": c.created_at,
    }


# ─── Credits Operations ─────────────────────────────────────────────

def log_credit(provider: str, amount: float, balance_after: float = None,
               reason: str = None, api_call_id: int = None):
    with get_session() as session:
        entry = models.CreditsLog(
            provider=provider,
            amount=int(amount * 100),
            balance_after=int(balance_after * 100) if balance_after else None,
            reason=reason,
            api_call_id=api_call_id,
        )
        session.add(entry)


def get_credit_balance(provider: str) -> float:
    """
    Get the most recent known credit balance for a provider from DB.
    Convenience alias for get_credits_balance().
    """
    return get_credits_balance(provider)


def get_credits_balance(provider: str) -> float:
    with get_session() as session:
        entry = session.query(models.CreditsLog)\
            .filter_by(provider=provider)\
            .order_by(models.CreditsLog.created_at.desc()).first()
        return entry.balance_after / 100 if entry and entry.balance_after else 0.0


def get_credits_log(provider: str = None, limit: int = 50) -> List[Dict]:
    with get_session() as session:
        query = session.query(models.CreditsLog)
        if provider:
            query = query.filter_by(provider=provider)
        entries = query.order_by(models.CreditsLog.created_at.desc()).limit(limit).all()
        return [_credits_log_to_dict(e) for e in entries]


def _credits_log_to_dict(e: models.CreditsLog) -> Dict:
    return {
        "id": e.id,
        "provider": e.provider,
        "amount": e.amount,
        "balance_after": e.balance_after,
        "reason": e.reason,
        "api_call_id": e.api_call_id,
        "created_at": e.created_at,
    }


def get_run_cost_breakdown(run_id: int) -> Dict:
    """Get cost aggregation for a run from CostLog.

    Args:
        run_id: The video run ID.

    Returns:
        Dict with total_cost (float USD) and breakdowns by_operation and by_provider.
    """
    with get_session() as session:
        cost_entries = session.query(models.CostLog).filter_by(run_id=run_id).all()
        total_cents = 0
        by_operation: Dict[str, float] = {}
        by_provider: Dict[str, float] = {}

        for entry in cost_entries:
            cents = entry.cost_usd or 0
            total_cents += cents
            op = entry.operation or "unknown"
            prov = entry.provider or "unknown"
            by_operation[op] = by_operation.get(op, 0) + cents
            by_provider[prov] = by_provider.get(prov, 0) + cents

        return {
            "total_cost": total_cents / 100.0,
            "breakdown": {
                "by_operation": {k: v / 100.0 for k, v in by_operation.items()},
                "by_provider": {k: v / 100.0 for k, v in by_provider.items()},
            },
        }


# ─── Social Post Operations ─────────────────────────────────────────

def create_social_post(run_id: int, platform: str, video_path: str = None,
                       caption: str = None, srt_path: str = None) -> int:
    with get_session() as session:
        post = models.SocialPost(
            run_id=run_id,
            platform=platform,
            video_path=video_path,
            caption=caption,
            srt_path=srt_path,
            status="pending",
        )
        session.add(post)
        session.flush()
        return post.id


def update_social_post(post_id: int, **kwargs):
    """Update social post. Allowed: status, post_id, post_url, error, posted_at."""
    allowed = ["status", "post_id", "post_url", "error", "posted_at"]
    with get_session() as session:
        post = session.query(models.SocialPost).filter_by(id=post_id).first()
        if not post:
            return
        for k, v in kwargs.items():
            if k in allowed:
                setattr(post, k, v)


def get_social_posts_by_run(run_id: int) -> List[Dict]:
    with get_session() as session:
        posts = session.query(models.SocialPost).filter_by(run_id=run_id)\
            .order_by(models.SocialPost.created_at).all()
        return [_social_post_to_dict(p) for p in posts]


def get_pending_social_posts() -> List[Dict]:
    with get_session() as session:
        posts = session.query(models.SocialPost).filter_by(status="pending")\
            .order_by(models.SocialPost.created_at).all()
        return [_social_post_to_dict(p) for p in posts]


def upsert_social_post_metrics(
    post_id: str,
    platform: str,
    metrics: dict,
    posted_at=None,
) -> int:
    """Insert or update social post metrics.

    Args:
        post_id: Platform post ID (from social_posts.post_id)
        platform: 'facebook' or 'tiktok'
        metrics: Dict with any of: reach, impressions, engagement, clicks,
                 video_views, likes, comments, shares
        posted_at: Optional datetime when the post went live

    Returns:
        social_post_metrics.id
    """
    with get_session() as session:
        existing = session.query(models.SocialPostMetric).filter_by(post_id=post_id).first()
        now = datetime.now(timezone.utc)
        if existing:
            existing.fetched_at = now
            existing.metrics_json = metrics
            for key in ["reach", "impressions", "engagement", "clicks",
                        "video_views", "likes", "comments", "shares"]:
                if key in metrics:
                    setattr(existing, key, metrics[key])
            return existing.id
        else:
            record = models.SocialPostMetric(
                post_id=post_id,
                platform=platform,
                posted_at=posted_at,
                fetched_at=now,
                metrics_json=metrics,
                reach=metrics.get("reach"),
                impressions=metrics.get("impressions"),
                engagement=metrics.get("engagement"),
                clicks=metrics.get("clicks"),
                video_views=metrics.get("video_views"),
                likes=metrics.get("likes"),
                comments=metrics.get("comments"),
                shares=metrics.get("shares"),
            )
            session.add(record)
            session.flush()
            return record.id


def get_social_post_metrics(post_id: str) -> Optional[Dict]:
    """Get the latest metrics record for a post."""
    with get_session() as session:
        row = session.query(models.SocialPostMetric).filter_by(post_id=post_id)\
            .order_by(models.SocialPostMetric.fetched_at.desc()).first()
        if not row:
            return None
        return _social_post_metric_to_dict(row)


def get_posts_needing_insights(hours_old: int = 1, min_polling_interval_minutes: int = 30) -> List[Dict]:
    """Get posts that need insights polling.

    Posts must be: posted (posted_at not null), older than hours_old,
    and not polled in the last min_polling_interval_minutes.
    """
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    polling_cutoff = datetime.now(timezone.utc) - timedelta(minutes=min_polling_interval_minutes)
    with get_session() as session:
        # Subquery: latest fetch time per post_id
        from sqlalchemy import func
        latest_subq = session.query(
            models.SocialPostMetric.post_id,
            func.max(models.SocialPostMetric.fetched_at).label("last_fetch")
        ).group_by(models.SocialPostMetric.post_id).subquery()


        posts = session.query(models.SocialPost).join(
            latest_subq,
            models.SocialPost.post_id == latest_subq.c.post_id,
            isouter=True,
        ).filter(
            models.SocialPost.post_id.isnot(None),
            models.SocialPost.posted_at.isnot(None),
            models.SocialPost.posted_at < cutoff,
        ).filter(
            # Either never fetched (last_fetch is NULL) or polled before cutoff
            (latest_subq.c.last_fetch < polling_cutoff) | (latest_subq.c.last_fetch.is_(None))
        ).all()
        return [_social_post_to_dict(p) for p in posts]


def _social_post_metric_to_dict(m: models.SocialPostMetric) -> Dict:
    return {
        "id": m.id,
        "post_id": m.post_id,
        "platform": m.platform,
        "posted_at": m.posted_at,
        "fetched_at": m.fetched_at,
        "metrics_json": m.metrics_json,
        "reach": m.reach,
        "impressions": m.impressions,
        "engagement": m.engagement,
        "clicks": m.clicks,
        "video_views": m.video_views,
        "likes": m.likes,
        "comments": m.comments,
        "shares": m.shares,
        "created_at": m.created_at,
    }


def _social_post_to_dict(p: models.SocialPost) -> Dict:
    return {
        "id": p.id,
        "run_id": p.run_id,
        "platform": p.platform,
        "post_id": p.post_id,
        "post_url": p.post_url,
        "caption": p.caption,
        "video_path": p.video_path,
        "srt_path": p.srt_path,
        "status": p.status,
        "error": p.error,
        "posted_at": p.posted_at,
        "created_at": p.created_at,
    }


# ─── Credentials Operations ─────────────────────────────────────────

def save_credential(platform: str, credential_name: str, credential_value: str):
    """Save or update a credential (upsert)."""
    with get_session() as session:
        existing = session.query(models.Credential)\
            .filter_by(platform=platform, credential_name=credential_name).first()
        if existing:
            existing.credential_value = credential_value
            existing.updated_at = datetime.now(timezone.utc)
        else:
            cred = models.Credential(
                platform=platform,
                credential_name=credential_name,
                credential_value=credential_value,
            )
            session.add(cred)


def get_credential(platform: str, credential_name: str = None) -> Optional[str]:
    with get_session() as session:
        if credential_name:
            cred = session.query(models.Credential)\
                .filter_by(platform=platform, credential_name=credential_name).first()
        else:
            cred = session.query(models.Credential)\
                .filter_by(platform=platform).first()
        return cred.credential_value if cred else None


def get_all_credentials(platform: str) -> Dict[str, str]:
    with get_session() as session:
        creds = session.query(models.Credential).filter_by(platform=platform).all()
        return {c.credential_name: c.credential_value for c in creds}


def delete_credential(platform: str, credential_name: str) -> bool:
    with get_session() as session:
        cred = session.query(models.Credential)\
            .filter_by(platform=platform, credential_name=credential_name).first()
        if cred:
            session.delete(cred)
            return True
        return False


# ─── Content Idea Operations ────────────────────────────────────────

def save_content_ideas(project_id: int, ideas: List[Dict], source_id: int = None) -> List[int]:
    """Save multiple content ideas, return list of idea ids."""
    ids = []
    with get_session() as session:
        for idea in ideas:
            kw = idea.get("topic_keywords", [])
            if isinstance(kw, str):
                # Already a string, use as-is
                pass
            else:
                # Convert list to JSON string for JSONB column
                import json
                kw = json.dumps(kw) if kw else "[]"
            content_idea = models.ContentIdea(
                project_id=project_id,
                title=idea.get("title"),
                topic_keywords=kw,
                script_json=idea.get("script_json"),
                platform=idea.get("target_platform", "both"),
                status="raw",
            )
            session.add(content_idea)
            session.flush()
            ids.append(content_idea.id)
    return ids


def update_idea_script(idea_id: int, script_json: Dict):
    """Update idea with generated script, set status to 'script_ready'."""
    with get_session() as session:
        idea = session.query(models.ContentIdea).filter_by(id=idea_id).first()
        if idea:
            idea.script_json = script_json
            idea.status = "script_ready"
            idea.updated_at = datetime.now(timezone.utc)


def get_ideas_by_status(project_id: int, status: str = "raw", limit: int = 10) -> List[Dict]:
    with get_session() as session:
        ideas = session.query(models.ContentIdea)\
            .filter_by(project_id=project_id, status=status)\
            .order_by(models.ContentIdea.created_at.desc())\
            .limit(limit).all()
        return [_content_idea_to_dict(i) for i in ideas]


def get_content_idea(idea_id: int) -> Optional[Dict]:
    with get_session() as session:
        idea = session.query(models.ContentIdea).filter_by(id=idea_id).first()
        return _content_idea_to_dict(idea) if idea else None


def _content_idea_to_dict(i: models.ContentIdea) -> Dict:
    return {
        "id": i.id,
        "project_id": i.project_id,
        "title": i.title,
        "topic_keywords": i.topic_keywords,
        "script_json": i.script_json,
        "platform": i.platform,
        "status": i.status,
        "created_at": i.created_at,
        "updated_at": i.updated_at,
    }


# ─── Content Calendar Operations ────────────────────────────────────

def schedule_content_idea(idea_id: int, platform: str,
                          scheduled_date, scheduled_time,
                          priority: str = "medium", notes: str = None) -> int:
    """Schedule a content idea. Returns calendar entry id."""
    with get_session() as session:
        entry = models.ContentCalendar(
            idea_id=idea_id,
            platform=platform,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            priority=priority,
            notes=notes,
            status="scheduled",
        )
        session.add(entry)
        session.flush()
        return entry.id


def get_due_calendar_items(as_of_date, platform: str = None) -> List[Dict]:
    """Get calendar items that are due (scheduled_date <= as_of_date) with JOIN to content_ideas."""
    with get_session() as session:
        query = session.query(models.ContentCalendar, models.ContentIdea.title, models.ContentIdea.topic_keywords)\
            .join(models.ContentIdea, models.ContentCalendar.idea_id == models.ContentIdea.id)\
            .filter(
                models.ContentCalendar.status == "scheduled",
                models.ContentCalendar.scheduled_date <= as_of_date,
            )
        if platform:
            query = query.filter(models.ContentCalendar.platform == platform)
        rows = query.order_by(models.ContentCalendar.scheduled_date, models.ContentCalendar.scheduled_time).all()
        return [_calendar_row_to_dict(r) for r in rows]


def get_upcoming_calendar_items(start_date, end_date, platform: str = None) -> List[Dict]:
    """Get calendar items scheduled between start_date and end_date."""
    with get_session() as session:
        query = session.query(models.ContentCalendar, models.ContentIdea.title, models.ContentIdea.topic_keywords)\
            .join(models.ContentIdea, models.ContentCalendar.idea_id == models.ContentIdea.id)\
            .filter(
                models.ContentCalendar.status == "scheduled",
                models.ContentCalendar.scheduled_date >= start_date,
                models.ContentCalendar.scheduled_date <= end_date,
            )
        if platform:
            query = query.filter(models.ContentCalendar.platform == platform)
        rows = query.order_by(models.ContentCalendar.scheduled_date, models.ContentCalendar.scheduled_time).all()
        return [_calendar_row_to_dict(r) for r in rows]


def update_calendar_status(calendar_id: int, status: str,
                            video_run_id: int = None, notes: str = None):
    """Update calendar item status."""
    with get_session() as session:
        entry = session.query(models.ContentCalendar).filter_by(id=calendar_id).first()
        if entry:
            entry.status = status
            if video_run_id is not None:
                entry.video_run_id = video_run_id
            if notes:
                entry.notes = (entry.notes or "") + f" | {notes}" if entry.notes else notes
            entry.updated_at = datetime.now(timezone.utc)


def get_calendar_view(start_date, end_date) -> Dict[str, List[Dict]]:
    """Get calendar organized by date string."""
    with get_session() as session:
        rows = session.query(models.ContentCalendar, models.ContentIdea.title, models.ContentIdea.topic_keywords)\
            .join(models.ContentIdea, models.ContentCalendar.idea_id == models.ContentIdea.id)\
            .filter(
                models.ContentCalendar.scheduled_date >= start_date,
                models.ContentCalendar.scheduled_date <= end_date,
            )\
            .order_by(models.ContentCalendar.scheduled_date, models.ContentCalendar.scheduled_time, models.ContentCalendar.platform)\
            .all()

        calendar: Dict[str, List[Dict]] = {}
        for row in rows:
            cal_entry = row[0]
            date_str = str(cal_entry.scheduled_date)
            if date_str not in calendar:
                calendar[date_str] = []
            calendar[date_str].append(_calendar_entry_to_dict(cal_entry, row[1], row[2]))
        return calendar


def get_calendar_stats() -> Dict:
    """Get calendar statistics."""
    with get_session() as session:
        from sqlalchemy import func
        status_counts = dict(
            session.query(models.ContentCalendar.status, func.count(models.ContentCalendar.id))
            .group_by(models.ContentCalendar.status).all()
        )
        platform_counts = dict(
            session.query(models.ContentCalendar.platform, func.count(models.ContentCalendar.id))
            .filter(models.ContentCalendar.status == "scheduled")
            .group_by(models.ContentCalendar.platform).all()
        )
        today = date.today()
        due_today_count = session.query(func.count(models.ContentCalendar.id))\
            .filter(
                models.ContentCalendar.status == "scheduled",
                models.ContentCalendar.scheduled_date <= today,
            ).scalar()
        return {
            "total": sum(status_counts.values()),
            "by_status": status_counts,
            "scheduled_by_platform": platform_counts,
            "due_today": due_today_count,
        }


def _calendar_row_to_dict(row) -> Dict:
    cal, title, topic_keywords = row
    return {
        "id": cal.id,
        "idea_id": cal.idea_id,
        "platform": cal.platform,
        "scheduled_date": cal.scheduled_date,
        "scheduled_time": cal.scheduled_time,
        "status": cal.status,
        "priority": cal.priority,
        "notes": cal.notes,
        "video_run_id": cal.video_run_id,
        "created_at": cal.created_at,
        "title": title,
        "topic_keywords": topic_keywords,
    }


def _calendar_entry_to_dict(cal, title, topic_keywords) -> Dict:
    return {
        "id": cal.id,
        "idea_id": cal.idea_id,
        "platform": cal.platform,
        "scheduled_date": cal.scheduled_date,
        "scheduled_time": cal.scheduled_time,
        "status": cal.status,
        "priority": cal.priority,
        "notes": cal.notes,
        "video_run_id": cal.video_run_id,
        "created_at": cal.created_at,
        "title": title,
        "topic_keywords": topic_keywords,
    }


# ─── Topic Sources Operations ────────────────────────────────────────

def save_topic_sources(source_type: str, source_query: str, topics: List[Dict]) -> int:
    """Save topic sources, return source id."""
    with get_session() as session:
        source = models.TopicSource(
            source_type=source_type,
            source_query=source_query,
            topics=topics,
        )
        session.add(source)
        session.flush()
        return source.id


def get_recent_topic_titles(days: int = 30) -> set:
    """Lấy titles của topics đã research trong N ngày gần đây, chỉ topics chưa completed."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with get_session() as session:
        rows = session.query(models.TopicSource).filter(
            models.TopicSource.created_at >= cutoff,
            models.TopicSource.status != "completed"
        ).all()
        titles = set()
        for r in rows:
            for t in r.topics or []:
                if t.get("title"):
                    titles.add(t["title"])
        return titles


def mark_topic_source_completed(source_id: int):
    """Mark a topic source as completed after script YAML is saved."""
    with get_session() as session:
        row = session.query(models.TopicSource).filter_by(id=source_id).first()
        if row:
            row.status = "completed"
            session.flush()


def get_pending_topic_sources(limit: int = 3) -> List[Dict]:
    """Lấy topic_sources đang ở trạng thái pending, kèm topics của chúng."""
    with get_session() as session:
        rows = session.query(models.TopicSource).filter(
            models.TopicSource.status == "pending"
        ).order_by(models.TopicSource.created_at.asc()).limit(limit).all()
        result = []
        for r in rows:
            result.append({
                "id": r.id,
                "source_query": r.source_query,
                "topics": r.topics or [],
                "status": r.status,
                "created_at": r.created_at,
            })
        return result


# ─── Keyword Pool Operations ─────────────────────────────────

def save_keyword(keyword: str, source_topic_id: int = None) -> int:
    """Save an extracted keyword to the pool. Returns keyword id."""
    with get_session() as session:
        kw = models.ContentKeywordPool(keyword=keyword, source_topic_id=source_topic_id)
        session.add(kw)
        session.flush()
        return kw.id


def get_keywords_for_research(limit: int = 20, days_old: int = None) -> List[Dict]:
    """Get distinct keywords for research, ordered by newest first."""
    if days_old is None:
        days_old = 90
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_old)
    with get_session() as session:
        # Subquery: rank rows by created_at descending within each keyword
        subq = session.query(
            models.ContentKeywordPool.keyword,
            models.ContentKeywordPool.source_topic_id,
            func.row_number().over(
                partition_by=models.ContentKeywordPool.keyword,
                order_by=models.ContentKeywordPool.created_at.desc()
            ).label("rn")
        ).filter(
            models.ContentKeywordPool.created_at >= cutoff
        ).subquery()
        rows = session.query(
            subq.c.keyword,
            subq.c.source_topic_id,
        ).filter(subq.c.rn == 1).limit(limit).all()
        return [{"keyword": r.keyword, "source_topic_id": r.source_topic_id} for r in rows]


def delete_expired_keywords(ttl_days: int = 30) -> int:
    """Delete keywords older than ttl_days. Returns count deleted."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    with get_session() as session:
        deleted = session.query(models.ContentKeywordPool).filter(
            models.ContentKeywordPool.created_at < cutoff
        ).delete()
        session.commit()
        return deleted


# ─── Pipeline Lock Operations ─────────────────────────────────

def acquire_research_lock(owner_run_id: str, timeout_seconds: int = 300) -> bool:
    """Atomically acquire research lock. Returns True if acquired, False if held."""
    from datetime import timedelta
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
    with get_session() as session:
        # Clean up any expired locks first
        session.query(models.PipelineLock).filter(
            models.PipelineLock.expires_at < datetime.now(timezone.utc)
        ).delete()
        existing = session.query(models.PipelineLock).filter_by(lock_name="research").first()
        if existing:
            return False
        lock = models.PipelineLock(
            lock_name="research",
            owner_run_id=owner_run_id,
            acquired_at=datetime.now(timezone.utc),
            expires_at=expires_at,
        )
        session.add(lock)
        session.flush()
        return True


def release_research_lock(owner_run_id: str) -> None:
    """Release research lock only if owned by owner_run_id."""
    with get_session() as session:
        session.query(models.PipelineLock).filter(
            models.PipelineLock.lock_name == "research",
            models.PipelineLock.owner_run_id == owner_run_id,
        ).delete()
        session.commit()


def is_research_locked() -> bool:
    """Check if research lock is currently held (and not expired)."""
    with get_session() as session:
        lock = session.query(models.PipelineLock).filter(
            models.PipelineLock.lock_name == "research",
            models.PipelineLock.expires_at >= datetime.now(timezone.utc)
        ).first()
        return lock is not None


# ─── Idea Embedding Operations ───────────────────────────────────────

def get_all_idea_embeddings(project_id: int) -> List[Dict]:
    """Get all idea embeddings for a project. Used for similarity search."""
    with get_session() as session:
        rows = session.query(models.IdeaEmbedding, models.ContentIdea).join(
            models.ContentIdea,
            models.IdeaEmbedding.content_idea_id == models.ContentIdea.id
        ).filter(
            models.ContentIdea.project_id == project_id
        ).all()
        result = []
        for emb, idea in rows:
            result.append({
                "idea_id": idea.id,
                "idea_title": idea.title,
                "title_vi": emb.title_vi,
                "title_en": emb.title_en,
                "embedding": emb.embedding.tolist() if hasattr(emb.embedding, 'tolist') else list(emb.embedding),
            })
        return result


# ─── A/B Caption Test Operations ─────────────────────────────────────

def create_ab_caption_test(
    calendar_item_id: int,
    platform: str,
    variant_a: str,
    variant_b: str,
    post_id: str = None,
) -> int:
    """Create a new A/B caption test record. Returns test id."""
    with get_session() as session:
        test = models.ABCaptionTest(
            calendar_item_id=calendar_item_id,
            platform=platform,
            post_id=post_id,
            variant_a=variant_a,
            variant_b=variant_b,
            status="pending",
        )
        session.add(test)
        session.flush()
        return test.id


def update_ab_caption_test(test_id: int, **kwargs):
    """Update ab_caption_test fields. Allowed: post_id, ctr_a, ctr_b, winner, status, posted_at."""
    allowed = ["post_id", "ctr_a", "ctr_b", "winner", "status", "posted_at"]
    with get_session() as session:
        test = session.query(models.ABCaptionTest).filter_by(id=test_id).first()
        if not test:
            return
        for k, v in kwargs.items():
            if k in allowed:
                setattr(test, k, v)
        test.updated_at = datetime.now(timezone.utc)


def get_ab_caption_test(test_id: int) -> Optional[Dict]:
    """Get a single A/B test by id."""
    with get_session() as session:
        t = session.query(models.ABCaptionTest).filter_by(id=test_id).first()
        return _ab_caption_test_to_dict(t) if t else None


def get_ab_caption_tests_pending(platform: str = None, limit: int = 50) -> List[Dict]:
    """Get A/B tests still in 'pending' status (variant-A posted, waiting for CTR check)."""
    with get_session() as session:
        query = session.query(models.ABCaptionTest).filter(
            models.ABCaptionTest.status.in_(["pending", "results_collected"])
        )
        if platform:
            query = query.filter(models.ABCaptionTest.platform == platform)
        rows = query.order_by(models.ABCaptionTest.posted_at.asc()).limit(limit).all()
        return [_ab_caption_test_to_dict(r) for r in rows]


def get_ab_caption_tests_by_calendar(calendar_item_id: int) -> List[Dict]:
    """Get all A/B tests for a calendar item."""
    with get_session() as session:
        rows = session.query(models.ABCaptionTest).filter_by(
            calendar_item_id=calendar_item_id
        ).order_by(models.ABCaptionTest.created_at.desc()).all()
        return [_ab_caption_test_to_dict(r) for r in rows]


def _ab_caption_test_to_dict(t: models.ABCaptionTest) -> Dict:
    return {
        "id": t.id,
        "calendar_item_id": t.calendar_item_id,
        "platform": t.platform,
        "post_id": t.post_id,
        "variant_a": t.variant_a,
        "variant_b": t.variant_b,
        "winner": t.winner,
        "posted_at": t.posted_at,
        "ctr_a": t.ctr_a,
        "ctr_b": t.ctr_b,
        "status": t.status,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


# ─── Cost Log Operations ────────────────────────────────────────────

def log_cost(run_id: int = None, provider: str = None, operation: str = None,
             units: int = 1, cost_usd: float = 0.0) -> int:
    """Write a cost log entry. Returns cost_log id.

    Args:
        run_id: video run id (optional, for aggregation)
        provider: provider name e.g. 'minimax_tts', 'kieai_lipsync'
        operation: operation type 'tts', 'image_gen', 'lipsync', 'music_gen'
        units: number of units (default 1)
        cost_usd: cost in USD (stored as cents internally)
    """
    if not provider or not operation:
        return 0
    with get_session() as session:
        entry = models.CostLog(
            run_id=run_id,
            provider=provider,
            operation=operation,
            units=units,
            cost_usd=int(cost_usd * 100),
        )
        session.add(entry)
        session.flush()
        return entry.id


def get_cost_log(run_id: int = None, provider: str = None,
                 start_date: datetime = None, end_date: datetime = None,
                 limit: int = 500) -> List[Dict]:
    """Query cost_log entries with optional filters."""
    with get_session() as session:
        q = session.query(models.CostLog)
        if run_id is not None:
            q = q.filter_by(run_id=run_id)
        if provider:
            q = q.filter_by(provider=provider)
        if start_date:
            q = q.filter(models.CostLog.created_at >= start_date)
        if end_date:
            q = q.filter(models.CostLog.created_at <= end_date)
        rows = q.order_by(models.CostLog.created_at.desc()).limit(limit).all()
        return [_cost_log_to_dict(r) for r in rows]


def _cost_log_to_dict(e: models.CostLog) -> Dict:
    return {
        "id": e.id,
        "run_id": e.run_id,
        "provider": e.provider,
        "operation": e.operation,
        "units": e.units,
        "cost_usd": e.cost_usd / 100.0 if e.cost_usd else 0.0,
        "created_at": e.created_at,
    }


def per_video_cost(run_id: int) -> Dict:
    """Aggregated cost for a single video run.

    Returns:
        {'total_usd': float, 'by_provider': {provider: float}, 'by_operation': {op: float}}
    """
    with get_session() as session:
        rows = session.query(models.CostLog).filter_by(run_id=run_id).all()
        total = sum(r.cost_usd for r in rows) / 100.0
        by_provider: Dict[str, float] = {}
        by_operation: Dict[str, float] = {}
        for r in rows:
            p = r.provider
            o = r.operation
            c = r.cost_usd / 100.0
            by_provider[p] = by_provider.get(p, 0.0) + c
            by_operation[o] = by_operation.get(o, 0.0) + c
        return {"run_id": run_id, "total_usd": round(total, 4), "by_provider": by_provider, "by_operation": by_operation}


def per_provider_cost(start_date: date = None, end_date: date = None) -> Dict:
    """Cost breakdown by provider within a date range.

    Args:
        start_date, end_date: date objects (inclusive). Defaults to last 30 days.
    """
    from datetime import timedelta
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    with get_session() as session:
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())
        from sqlalchemy import func
        rows = session.query(
            models.CostLog.provider,
            models.CostLog.operation,
            func.count(models.CostLog.id).label("count"),
            func.sum(models.CostLog.cost_usd).label("total_cents"),
        ).filter(
            models.CostLog.created_at >= start_dt,
            models.CostLog.created_at <= end_dt,
        ).group_by(
            models.CostLog.provider,
            models.CostLog.operation,
        ).all()

        result = {"period": {"start": str(start_date), "end": str(end_date)}, "providers": {}}
        total = 0.0
        for provider, operation, count, total_cents in rows:
            cost = (total_cents or 0) / 100.0
            total += cost
            if provider not in result["providers"]:
                result["providers"][provider] = {"total_usd": 0.0, "operations": {}, "count": 0}
            result["providers"][provider]["total_usd"] = round(result["providers"][provider]["total_usd"] + cost, 4)
            result["providers"][provider]["operations"][operation] = {"count": count, "cost_usd": round(cost, 4)}
            result["providers"][provider]["count"] = result["providers"][provider].get("count", 0) + count
        result["total_usd"] = round(total, 4)
        return result


def per_platform_cost() -> Dict:
    """Facebook vs TikTok spend from social_posts joined with video_runs cost.

    Returns breakdown of total spent per platform based on social posts linked to runs.
    """
    with get_session() as session:
        from sqlalchemy import func
        rows = session.query(
            models.SocialPost.platform,
            func.count(models.SocialPost.id).label("post_count"),
            func.sum(models.VideoRun.total_cost).label("total_cost_cents"),
        ).join(
            models.VideoRun, models.SocialPost.run_id == models.VideoRun.id
        ).group_by(
            models.SocialPost.platform
        ).all()

        result = {"platforms": {}}
        total = 0.0
        for platform, post_count, total_cost_cents in rows:
            cost = (total_cost_cents or 0) / 100.0
            total += cost
            result["platforms"][platform] = {
                "post_count": post_count,
                "total_usd": round(cost, 4),
            }
        result["total_usd"] = round(total, 4)
        return result


def ab_ctr_correlation(days: int = 30) -> dict:
    """Correlate cost spend with A/B caption CTR results.

    Returns dict with per-platform CTR stats, cost-per-click estimates,
    and cost-per-impression from cost_log for the period.
    """
    with get_session() as session:
        from datetime import datetime, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        tests = session.query(models.ABCaptionTest).filter(
            models.ABCaptionTest.status.in_(["results_collected", "winner_decided"]),
            models.ABCaptionTest.posted_at >= cutoff,
        ).all()

        by_platform = {}
        for t in tests:
            plat = t.platform.lower()
            pd = by_platform.setdefault(plat, {
                "tests": 0, "ctr_a_avg": 0.0, "ctr_b_avg": 0.0,
                "ctr_a_sum": 0.0, "ctr_b_sum": 0.0,
                "impressions_a_total": 0, "clicks_a_total": 0,
            })
            pd["tests"] += 1
            if t.ctr_a:
                ctr_val = t.ctr_a.get("ctr", 0) if isinstance(t.ctr_a, dict) else float(t.ctr_a or 0)
                pd["ctr_a_sum"] += ctr_val
                pd["impressions_a_total"] += t.ctr_a.get("impressions", 0) if isinstance(t.ctr_a, dict) else 0
                pd["clicks_a_total"] += t.ctr_a.get("clicks", 0) if isinstance(t.ctr_a, dict) else 0
            if t.ctr_b:
                ctr_val = t.ctr_b.get("ctr", 0) if isinstance(t.ctr_b, dict) else float(t.ctr_b or 0)
                pd["ctr_b_sum"] += ctr_val

        for plat, pd in by_platform.items():
            n = pd["tests"]
            pd["ctr_a_avg"] = round(pd["ctr_a_sum"] / n, 4) if n else 0.0
            pd["ctr_b_avg"] = round(pd["ctr_b_sum"] / n, 4) if n else 0.0

        # cost spend by platform over same period
        cost_by_platform = {}
        start_dt = datetime.combine((datetime.now(timezone.utc) - timedelta(days=days)).date(), datetime.min.time())
        cost_rows = session.query(models.CostLog).filter(
            models.CostLog.created_at >= start_dt,
            models.CostLog.run_id.isnot(None),
        ).all()
        for row in cost_rows:
            cost = (row.cost_usd or 0) / 100.0
            post = session.query(models.SocialPost).filter_by(run_id=row.run_id).first()
            if post:
                plat = post.platform.lower()
                cost_by_platform.setdefault(plat, 0.0)
                cost_by_platform[plat] += cost

        result = {
            "period_days": days,
            "platforms": by_platform,
            "cost_by_platform": cost_by_platform,
        }
        # cost per test
        for plat in by_platform:
            total_cost = cost_by_platform.get(plat, 0.0)
            n = by_platform[plat]["tests"]
            result[plat]["cost_per_test"] = round(total_cost / n, 4) if n else 0.0
        return result


# ─── Failed Step Operations ────────────────────────────────────────────

def create_failed_step(run_id: int, step_name: str, scene_index: int = None,
                       last_error: str = None, next_retry_at: datetime = None) -> int:
    """Create a new failed step entry in the queue. Returns failed_step id."""
    with get_session() as session:
        entry = models.FailedStep(
            run_id=run_id,
            scene_index=scene_index,
            step_name=step_name,
            attempts=1,
            last_error=last_error,
            next_retry_at=next_retry_at,
            status="pending",
        )
        session.add(entry)
        session.flush()
        return entry.id


def update_failed_step(failed_step_id: int, attempts: int = None,
                       last_error: str = None, next_retry_at: datetime = None,
                       status: str = None):
    """Update a failed step entry. Only provided fields are updated."""
    allowed = ["attempts", "last_error", "next_retry_at", "status"]
    with get_session() as session:
        entry = session.query(models.FailedStep).filter_by(id=failed_step_id).first()
        if not entry:
            return
        if attempts is not None:
            entry.attempts = attempts
        if last_error is not None:
            entry.last_error = last_error
        if next_retry_at is not None:
            entry.next_retry_at = next_retry_at
        if status is not None:
            entry.status = status
        entry.updated_at = datetime.now(timezone.utc)


def resolve_failed_step(failed_step_id: int):
    """Mark a failed step as resolved (resolved_at = now, status = 'resolved')."""
    with get_session() as session:
        entry = session.query(models.FailedStep).filter_by(id=failed_step_id).first()
        if entry:
            entry.resolved_at = datetime.now(timezone.utc)
            entry.status = "resolved"
            entry.updated_at = datetime.now(timezone.utc)


def get_pending_failed_steps(run_id: int = None, status: str = None) -> List[Dict]:
    """Get unresolved failed steps (resolved_at IS NULL).

    Args:
        run_id: filter by specific run, or None for all runs
        status: filter by status ('pending', 'retrying', 'exhausted'), or None for all unresolved
    """
    with get_session() as session:
        query = session.query(models.FailedStep).filter(
            models.FailedStep.resolved_at.is_(None)
        )
        if run_id is not None:
            query = query.filter_by(run_id=run_id)
        if status:
            query = query.filter_by(status=status)
        rows = query.order_by(models.FailedStep.next_retry_at.asc()).all()
        return [_failed_step_to_dict(r) for r in rows]


def get_failed_step_by_run_scene(run_id: int, scene_index: int = None,
                                 step_name: str = None) -> Optional[Dict]:
    """Get an existing unresolved failed step entry for a run+scene+step combination."""
    with get_session() as session:
        query = session.query(models.FailedStep).filter(
            models.FailedStep.run_id == run_id,
            models.FailedStep.resolved_at.is_(None),
        )
        if scene_index is not None:
            query = query.filter_by(scene_index=scene_index)
        if step_name is not None:
            query = query.filter_by(step_name=step_name)
        row = query.order_by(models.FailedStep.created_at.desc()).first()
        return _failed_step_to_dict(row) if row else None


def _failed_step_to_dict(e: models.FailedStep) -> Dict:
    return {
        "id": e.id,
        "run_id": e.run_id,
        "scene_index": e.scene_index,
        "step_name": e.step_name,
        "attempts": e.attempts,
        "last_error": e.last_error,
        "next_retry_at": e.next_retry_at,
        "resolved_at": e.resolved_at,
        "status": e.status,
        "created_at": e.created_at,
        "updated_at": e.updated_at,
    }


# ─── Scheduled Post Operations ──────────────────────────────────────

def schedule_video_post(
    video_id: int,
    platform: str,
    scheduled_at: datetime,
    caption: str = None,
    video_path: str = None,
) -> int:
    """Create a scheduled post entry. Returns scheduled_posts.id."""
    with get_session() as session:
        post = models.ScheduledPost(
            video_id=video_id,
            platform=platform,
            scheduled_at=scheduled_at,
            caption=caption,
            video_path=video_path,
            status="pending",
        )
        session.add(post)
        session.flush()
        return post.id


def get_due_scheduled_posts(now: datetime = None) -> List[Dict]:
    """Get scheduled_posts where scheduled_at <= now and status = 'pending'."""
    if now is None:
        now = datetime.now(timezone.utc)
    with get_session() as session:
        rows = session.query(
            models.ScheduledPost,
            models.VideoRun.output_video,
            models.VideoRun.caption,
        ).join(
            models.VideoRun,
            models.ScheduledPost.video_id == models.VideoRun.id,
        ).filter(
            models.ScheduledPost.status == "pending",
            models.ScheduledPost.scheduled_at <= now,
        ).order_by(models.ScheduledPost.scheduled_at).all()
        result = []
        for row in rows:
            post = row[0]
            result.append({
                "id": post.id,
                "video_id": post.video_id,
                "platform": post.platform,
                "scheduled_at": post.scheduled_at,
                "caption": post.caption,
                "video_path": post.video_path,
                "status": post.status,
                "output_video": row[1],
                "run_caption": row[2],
            })
        return result


def update_scheduled_post_status(
    schedule_id: int,
    status: str,
    error: str = None,
    posted_at: datetime = None,
) -> None:
    """Update status/error/posted_at for a scheduled post."""
    with get_session() as session:
        post = session.query(models.ScheduledPost).filter_by(id=schedule_id).first()
        if not post:
            return
        post.status = status
        if error is not None:
            post.error = error
        if posted_at is not None:
            post.posted_at = posted_at


# ─── Content Pipeline Run Operations (replaces .content_pipeline_checkpoint.json) ──

def upsert_content_pipeline_run(
    project_id: int,
    channel_id: str,
    last_processed_idea_index: int = -1,
    source_id: int = None,
    idea_ids_processed: list = None,
    status: str = "running",
) -> int:
    """Upsert a content pipeline run checkpoint.

    Returns the content_pipeline_run id.
    """
    now = datetime.now(timezone.utc)
    with get_session() as session:
        existing = session.query(models.ContentPipelineRun).filter_by(
            project_id=project_id,
            channel_id=channel_id,
        ).first()
        if existing:
            existing.last_processed_idea_index = last_processed_idea_index
            existing.source_id = source_id
            existing.idea_ids_processed = idea_ids_processed or []
            existing.status = status
            existing.updated_at = now
            if status == "completed":
                existing.completed_at = now
            session.flush()
            return existing.id
        else:
            run = models.ContentPipelineRun(
                project_id=project_id,
                channel_id=channel_id,
                last_processed_idea_index=last_processed_idea_index,
                source_id=source_id,
                idea_ids_processed=idea_ids_processed or [],
                status=status,
            )
            session.add(run)
            session.flush()
            return run.id


def get_content_pipeline_run(project_id: int, channel_id: str) -> Optional[Dict]:
    """Get the current content pipeline run for a project+channel, or None."""
    with get_session() as session:
        row = session.query(models.ContentPipelineRun).filter_by(
            project_id=project_id,
            channel_id=channel_id,
        ).first()
        if not row:
            return None
        return _content_pipeline_run_to_dict(row)


def clear_content_pipeline_run(project_id: int, channel_id: str) -> bool:
    """Delete the content pipeline run row (clears the checkpoint)."""
    with get_session() as session:
        deleted = session.query(models.ContentPipelineRun).filter_by(
            project_id=project_id,
            channel_id=channel_id,
        ).delete()
        session.commit()
        return deleted > 0


def _content_pipeline_run_to_dict(r: models.ContentPipelineRun) -> Dict:
    return {
        "id": r.id,
        "project_id": r.project_id,
        "channel_id": r.channel_id,
        "last_processed_idea_index": r.last_processed_idea_index,
        "source_id": r.source_id,
        "idea_ids_processed": r.idea_ids_processed or [],
        "status": r.status,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
        "completed_at": r.completed_at,
    }


if __name__ == "__main__":
    init_db()
    print("Database initialized OK")