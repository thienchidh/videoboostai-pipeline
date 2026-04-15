"""
db/helpers.py - Database helper functions.
"""
import db_models as models
from datetime import datetime, date, timezone
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

# Re-export get_session from config for internal use
from db.config import get_session


# ─── init_db helpers (also in config, referenced here for completeness) ───────────

# init_db, init_pgvector, init_db_full are in db/config.py


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


def list_recent_runs(limit: int = 20, status: str = None) -> List[Dict]:
    """List recent video runs across all projects."""
    with get_session() as session:
        query = session.query(models.VideoRun)
        if status:
            query = query.filter_by(status=status)
        runs = query.order_by(models.VideoRun.started_at.desc()).limit(limit).all()
        return [_video_run_to_dict(r) for r in runs]


def get_run_details(run_id: int) -> Optional[Dict]:
    """Get detailed run info including scenes, cost breakdown, and API call summary."""
    with get_session() as session:
        run = session.query(models.VideoRun).filter_by(id=run_id).first()
        if not run:
            return None
        scenes = session.query(models.Scene).filter_by(run_id=run_id)\
            .order_by(models.Scene.scene_index).all()
        api_calls = session.query(models.APICall).filter_by(run_id=run_id).all()
        credits_by_provider: Dict[str, int] = {}
        for call in api_calls:
            credits_by_provider[call.provider] = \
                credits_by_provider.get(call.provider, 0) + call.cost
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

CHECKPOINT_STEPS = {
    "tts": 1,
    "image": 2,
    "lipsync": 3,
    "crop": 4,
    "done": 5,
}
STEP_NAMES = {v: k for k, v in CHECKPOINT_STEPS.items()}


def save_checkpoint(scene_id: str, step: int, output_path: str = None) -> None:
    """Save (upsert) a checkpoint for a scene step."""
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
    """Load the highest completed checkpoint for a scene."""
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
    """Delete all checkpoints for a scene."""
    with get_session() as session:
        session.query(models.SceneCheckpoint).filter_by(scene_id=scene_id).delete()


def get_next_incomplete_step(scene_id: str) -> int:
    """Return the next step number that needs to run (1-based), or 1 if no checkpoints exist."""
    cp = load_checkpoint(scene_id)
    if cp is None:
        return 1
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
    """Get the most recent known credit balance for a provider from DB."""
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


def get_social_post(post_id: int) -> Optional[Dict]:
    with get_session() as session:
        post = session.query(models.SocialPost).filter_by(id=post_id).first()
        if post:
            return _social_post_to_dict(post)
        return None


def get_social_posts_by_run(run_id: int) -> List[Dict]:
    with get_session() as session:
        posts = session.query(models.SocialPost).filter_by(run_id=run_id)\
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

def save_content_idea(project_id: int, title: str, title_en: str = "",
                      source: str = None, script_json: dict = None,
                      status: str = "raw") -> int:
    with get_session() as session:
        idea = models.ContentIdea(
            project_id=project_id,
            title=title,
            title_en=title_en,
            source=source,
            script_json=script_json,
            status=status,
        )
        session.add(idea)
        session.flush()
        return idea.id


def update_idea_status(idea_id: int, status: str, script_json: dict = None):
    with get_session() as session:
        idea = session.query(models.ContentIdea).filter_by(id=idea_id).first()
        if idea:
            idea.status = status
            if script_json is not None:
                idea.script_json = script_json


def get_content_idea(idea_id: int) -> Optional[Dict]:
    with get_session() as session:
        idea = session.query(models.ContentIdea).filter_by(id=idea_id).first()
        if idea:
            return _content_idea_to_dict(idea)
        return None


def get_content_ideas_by_project(project_id: int, status: str = None) -> List[Dict]:
    with get_session() as session:
        q = session.query(models.ContentIdea).filter_by(project_id=project_id)
        if status:
            q = q.filter_by(status=status)
        ideas = q.order_by(models.ContentIdea.created_at.desc()).all()
        return [_content_idea_to_dict(i) for i in ideas]


def _content_idea_to_dict(i: models.ContentIdea) -> Dict:
    return {
        "id": i.id,
        "project_id": i.project_id,
        "title": i.title,
        "title_en": i.title_en,
        "source": i.source,
        "script_json": i.script_json,
        "status": i.status,
        "created_at": i.created_at,
        "updated_at": i.updated_at,
    }


def save_idea_embedding(idea_id: int, title_vi: str, title_en: str = "",
                       embedding=None) -> None:
    with get_session() as session:
        existing = session.query(models.IdeaEmbedding).filter_by(idea_id=idea_id).first()
        if existing:
            existing.embedding = embedding
        else:
            emb = models.IdeaEmbedding(
                idea_id=idea_id,
                title_vi=title_vi,
                title_en=title_en,
                embedding=embedding,
            )
            session.add(emb)


# ─── Content Calendar Operations ────────────────────────────────────

def create_calendar_item(
    project_id: int,
    idea_id: int,
    platform: str,
    scheduled_at: datetime,
    status: str = "pending",
    title: str = None,
    script: str = None,
    caption: str = None,
    video_path: str = None,
) -> int:
    with get_session() as session:
        item = models.CalendarItem(
            project_id=project_id,
            idea_id=idea_id,
            platform=platform,
            scheduled_at=scheduled_at,
            status=status,
            title=title,
            script=script,
            caption=caption,
            video_path=video_path,
        )
        session.add(item)
        session.flush()
        return item.id


def update_calendar_item(item_id: int, **kwargs):
    with get_session() as session:
        item = session.query(models.CalendarItem).filter_by(id=item_id).first()
        if item:
            for k, v in kwargs.items():
                setattr(item, k, v)


def get_calendar_items(project_id: int, platform: str = None,
                      status: str = None) -> List[Dict]:
    with get_session() as session:
        q = session.query(models.CalendarItem).filter_by(project_id=project_id)
        if platform:
            q = q.filter_by(platform=platform)
        if status:
            q = q.filter_by(status=status)
        items = q.order_by(models.CalendarItem.scheduled_at.asc()).all()
        return [_calendar_row_to_dict(i) for i in items]


def get_calendar_stats() -> Dict:
    with get_session() as session:
        total = session.query(models.CalendarItem).count()
        pending = session.query(models.CalendarItem).filter_by(status="pending").count()
        published = session.query(models.CalendarItem).filter_by(status="published").count()
        failed = session.query(models.CalendarItem).filter_by(status="failed").count()
        return {
            "total": total,
            "pending": pending,
            "published": published,
            "failed": failed,
        }


def _calendar_row_to_dict(row) -> Dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "idea_id": row.idea_id,
        "platform": row.platform,
        "scheduled_at": row.scheduled_at,
        "status": row.status,
        "title": row.title,
        "caption": row.caption,
        "video_path": row.video_path,
        "error": getattr(row, "error", None),
        "published_at": getattr(row, "published_at", None),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _calendar_entry_to_dict(cal, title, topic_keywords) -> Dict:
    return {
        "id": cal.id,
        "project_id": cal.project_id,
        "idea_id": cal.idea_id,
        "platform": cal.platform,
        "scheduled_at": cal.scheduled_at,
        "status": cal.status,
        "title": title or cal.title,
        "caption": cal.caption,
        "video_path": cal.video_path,
        "topic_keywords": topic_keywords,
        "published_at": getattr(cal, "published_at", None),
        "created_at": cal.created_at,
    }


# ─── Topic Sources Operations ────────────────────────────────────────

def save_topic_sources(source_type: str, source_query: str, topics: List[Dict]) -> int:
    with get_session() as session:
        entry = models.TopicSource(
            source_type=source_type,
            source_query=source_query,
            topics=topics,
        )
        session.add(entry)
        session.flush()
        return entry.id


def get_recent_topic_titles(days: int = 30) -> set:
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with get_session() as session:
        sources = session.query(models.TopicSource).filter(
            models.TopicSource.created_at >= cutoff
        ).all()
        titles = set()
        for s in sources:
            for t in s.topics or []:
                if t.get("title"):
                    titles.add(t["title"])
        return titles


def mark_topic_source_completed(source_id: int):
    with get_session() as session:
        src = session.query(models.TopicSource).filter_by(id=source_id).first()
        if src:
            src.status = "completed"


def get_pending_topic_sources(limit: int = 3) -> List[Dict]:
    with get_session() as session:
        sources = session.query(models.TopicSource).filter_by(
            status="pending"
        ).order_by(models.TopicSource.created_at.asc()).limit(limit).all()
        return [
            {"id": s.id, "source_type": s.source_type, "source_query": s.source_query, "topics": s.topics}
            for s in sources
        ]


# ─── Idea Embedding Operations ───────────────────────────────────────

def get_all_idea_embeddings(project_id: int) -> List[Dict]:
    with get_session() as session:
        ideas = session.query(models.ContentIdea).filter_by(project_id=project_id).all()
        result = []
        for idea in ideas:
            emb = session.query(models.IdeaEmbedding).filter_by(idea_id=idea.id).first()
            if emb:
                result.append({
                    "idea_id": idea.id,
                    "title": idea.title,
                    "embedding": emb.embedding,
                })
        return result


# ─── A/B Caption Test Operations ──────────────────────────────────────

def create_ab_caption_test(
    calendar_item_id: int,
    platform: str,
    variant_a: str,
    variant_b: str,
    post_id: str = None,
) -> int:
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
    with get_session() as session:
        t = session.query(models.ABCaptionTest).filter_by(id=test_id).first()
        if t:
            return _ab_caption_test_to_dict(t)
        return None


def get_ab_caption_tests_pending(platform: str = None, limit: int = 50) -> List[Dict]:
    with get_session() as session:
        q = session.query(models.ABCaptionTest).filter(
            models.ABCaptionTest.status.in_(["pending", "results_collected"])
        )
        if platform:
            q = q.filter_by(platform=platform)
        rows = q.order_by(models.ABCaptionTest.posted_at.asc()).limit(limit).all()
        return [_ab_caption_test_to_dict(r) for r in rows]


def get_ab_caption_tests_by_calendar(calendar_item_id: int) -> List[Dict]:
    with get_session() as session:
        rows = session.query(models.ABCaptionTest).filter_by(
            calendar_item_id=calendar_item_id
        ).all()
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
    from datetime import timedelta
    with get_session() as session:
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
            })
            pd["tests"] += 1
            if t.ctr_a:
                ctr_val = t.ctr_a.get("ctr", 0) if isinstance(t.ctr_a, dict) else float(t.ctr_a or 0)
                pd["ctr_a_sum"] += ctr_val
            if t.ctr_b:
                ctr_val = t.ctr_b.get("ctr", 0) if isinstance(t.ctr_b, dict) else float(t.ctr_b or 0)
                pd["ctr_b_sum"] += ctr_val
        for plat, pd in by_platform.items():
            n = pd["tests"]
            pd["ctr_a_avg"] = round(pd["ctr_a_sum"] / n, 4) if n else 0.0
            pd["ctr_b_avg"] = round(pd["ctr_b_sum"] / n, 4) if n else 0.0
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
        for plat in by_platform:
            total_cost = cost_by_platform.get(plat, 0.0)
            n = by_platform[plat]["tests"]
            result[plat]["cost_per_test"] = round(total_cost / n, 4) if n else 0.0
        return result


# ─── Failed Step Operations ────────────────────────────────────────────

def create_failed_step(run_id: int, step_name: str, scene_index: int = None,
                       last_error: str = None, next_retry_at: datetime = None) -> int:
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
    with get_session() as session:
        entry = session.query(models.FailedStep).filter_by(id=failed_step_id).first()
        if entry:
            entry.resolved_at = datetime.now(timezone.utc)
            entry.status = "resolved"
            entry.updated_at = datetime.now(timezone.utc)


def get_pending_failed_steps(run_id: int = None, status: str = None) -> List[Dict]:
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
    with get_session() as session:
        post = session.query(models.ScheduledPost).filter_by(id=schedule_id).first()
        if not post:
            return
        post.status = status
        if error is not None:
            post.error = error
        if posted_at is not None:
            post.posted_at = posted_at
