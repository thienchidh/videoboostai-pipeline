#!/usr/bin/env python3
"""
db.py - PostgreSQL database module for video pipeline state management.
Uses SQLAlchemy 2.0 with sync engine + sessionmaker.
"""
import os
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

from datetime import datetime, date, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from modules.pipeline.exceptions import MissingConfigError
import db_models as models

# Database connection config (updated by configure())
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "videopipeline",
    "user": "videopipeline",
    "password": "videopipeline123",
}

# SQLAlchemy engine + session factory (set by configure())
_engine = None
_SessionFactory = None


def configure(config: dict = None):
    """Configure database connection. Supports env var fallback.

    Config dict values take priority. Missing fields fall back to env vars
    (POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD).
    If no config dict is provided, uses env vars or defaults.
    """
    global _engine, _SessionFactory

    if config is None:
        config = {}

    host = config.get("host") or os.getenv("POSTGRES_HOST", "localhost")
    port = config.get("port") or int(os.getenv("POSTGRES_PORT", "5432"))
    database = config.get("name") or config.get("database") or os.getenv("POSTGRES_DB", "videopipeline")
    user = config.get("user") or os.getenv("POSTGRES_USER", "videopipeline")
    password = config.get("password") or os.getenv("POSTGRES_PASSWORD", "videopipeline123")

    if not all([host, database, user]):
        raise MissingConfigError("database host, name, user are required")

    DB_CONFIG.update({
        "host": host,
        "port": port,
        "database": database,
        "user": user,
        "password": password,
    })

    _engine = create_engine(
        f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}",
        pool_size=1,
        max_overflow=10,
        pool_timeout=30,
        echo=False,
    )
    _SessionFactory = sessionmaker(bind=_engine)


def _ensure_configured():
    """Ensure configure() has been called before any DB operation."""
    if _SessionFactory is None:
        configure()


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
            if isinstance(kw, list):
                kw = ", ".join(str(k) for k in kw)
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


if __name__ == "__main__":
    init_db()
    print("Database initialized OK")