#!/usr/bin/env python3
"""
db.py - PostgreSQL database module for video pipeline state management
Uses psycopg2 with connection pooling
"""
import atexit
import os
import json
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, Json
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

# Database connection config (updated by configure() or env fallback)
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "database": os.environ.get("DB_NAME", "videopipeline"),
    "user": os.environ.get("DB_USER", "videopipeline"),
    "password": os.environ.get("DB_PASSWORD", "videopipeline123"),
}


def configure(config: dict = None):
    """Update DB_CONFIG from a config dict. Call before get_pool()."""
    if config is None:
        return
    DB_CONFIG.update({
        "host": config.get("host", DB_CONFIG["host"]),
        "port": config.get("port", DB_CONFIG["port"]),
        "database": config.get("name", DB_CONFIG["database"]),
        "user": config.get("user", DB_CONFIG["user"]),
        "password": config.get("password", DB_CONFIG["password"]),
    })

# Connection pool
_connection_pool: Optional[pool.ThreadedConnectionPool] = None


def get_pool():
    """Get or create connection pool."""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            **DB_CONFIG
        )
        atexit.register(close_pool)
    return _connection_pool


def close_pool():
    """Close the connection pool at exit."""
    global _connection_pool
    if _connection_pool is not None:
        _connection_pool.closeall()
        _connection_pool = None


@contextmanager
def get_db():
    """Context manager for database connections."""
    p = get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def init_db():
    """Initialize database schema."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Projects table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    config_file VARCHAR(500),
                    description TEXT,
                    status VARCHAR(50) DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Video runs table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS video_runs (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                    run_dir VARCHAR(500),
                    config_snapshot JSONB,
                    status VARCHAR(50) DEFAULT 'running',
                    total_scenes INTEGER,
                    completed_scenes INTEGER DEFAULT 0,
                    total_cost DECIMAL(10, 6) DEFAULT 0,
                    output_video VARCHAR(500),
                    caption TEXT,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
            """)

            # Scenes table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scenes (
                    id SERIAL PRIMARY KEY,
                    run_id INTEGER REFERENCES video_runs(id) ON DELETE CASCADE,
                    scene_index INTEGER NOT NULL,
                    script TEXT,
                    characters JSONB,
                    background VARCHAR(100),
                    tts_audio VARCHAR(500),
                    tts_voice VARCHAR(100),
                    image_path VARCHAR(500),
                    image_prompt TEXT,
                    lipsync_video VARCHAR(500),
                    status VARCHAR(50) DEFAULT 'pending',
                    error_message TEXT,
                    cost DECIMAL(10, 6) DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
            """)

            # API calls log
            cur.execute("""
                CREATE TABLE IF NOT EXISTS api_calls (
                    id SERIAL PRIMARY KEY,
                    run_id INTEGER REFERENCES video_runs(id) ON DELETE CASCADE,
                    scene_id INTEGER REFERENCES scenes(id) ON DELETE SET NULL,
                    provider VARCHAR(50) NOT NULL,
                    endpoint VARCHAR(200),
                    request_payload JSONB,
                    response_payload JSONB,
                    status_code INTEGER,
                    cost DECIMAL(10, 6) DEFAULT 0,
                    duration_ms INTEGER,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Credits log
            cur.execute("""
                CREATE TABLE IF NOT EXISTS credits_log (
                    id SERIAL PRIMARY KEY,
                    provider VARCHAR(50) NOT NULL,
                    amount DECIMAL(10, 4) NOT NULL,
                    balance_after DECIMAL(10, 4),
                    reason VARCHAR(200),
                    api_call_id INTEGER REFERENCES api_calls(id) ON DELETE SET NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Social posts table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS social_posts (
                    id SERIAL PRIMARY KEY,
                    run_id INTEGER REFERENCES video_runs(id) ON DELETE CASCADE,
                    platform VARCHAR(50) NOT NULL,
                    post_id VARCHAR(200),
                    post_url VARCHAR(500),
                    caption TEXT,
                    video_path VARCHAR(500),
                    srt_path VARCHAR(500),
                    status VARCHAR(50) DEFAULT 'pending',
                    error TEXT,
                    posted_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Credentials table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS credentials (
                    id SERIAL PRIMARY KEY,
                    platform VARCHAR(50) NOT NULL,
                    credential_name VARCHAR(100) NOT NULL,
                    UNIQUE (platform, credential_name),
                    credential_value TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_runs_project ON video_runs(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scenes_run ON scenes(run_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_api_calls_run ON api_calls(run_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_social_posts_run ON social_posts(run_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_credits_provider ON credits_log(provider)")

            # Content ideas table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS content_ideas (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                    title VARCHAR(500),
                    topic_keywords TEXT,
                    script_json JSONB,
                    platform VARCHAR(50),
                    status VARCHAR(50) DEFAULT 'idea',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Content calendar table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS content_calendar (
                    id SERIAL PRIMARY KEY,
                    idea_id INTEGER REFERENCES content_ideas(id) ON DELETE CASCADE,
                    platform VARCHAR(50),
                    scheduled_date DATE,
                    scheduled_time TIME,
                    status VARCHAR(50) DEFAULT 'scheduled',
                    priority VARCHAR(20) DEFAULT 'medium',
                    notes TEXT,
                    video_run_id INTEGER REFERENCES video_runs(id) ON DELETE SET NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Topic sources table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS topic_sources (
                    id SERIAL PRIMARY KEY,
                    source_type VARCHAR(50),
                    source_query TEXT,
                    topics JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Indexes for content tables
            cur.execute("CREATE INDEX IF NOT EXISTS idx_content_ideas_project ON content_ideas(project_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_content_calendar_idea ON content_calendar(idea_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_content_calendar_status ON content_calendar(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_content_calendar_scheduled ON content_calendar(scheduled_date)")


# ─── Project Operations ─────────────────────────────────────────────

def create_project(name: str, config_file: str = None, description: str = None) -> int:
    """Create a new project, return project id."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO projects (name, config_file, description) VALUES (%s, %s, %s) RETURNING id",
                (name, config_file, description)
            )
            return cur.fetchone()["id"]


def get_or_create_project(name: str, config_file: str = None) -> int:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM projects WHERE name = %s", (name,))
            row = cur.fetchone()
            if row:
                return row["id"]
            cur.execute(
                "INSERT INTO projects (name, config_file) VALUES (%s, %s) RETURNING id",
                (name, config_file)
            )
            return cur.fetchone()["id"]


def start_video_run(project_id: int, config_name: str) -> int:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO video_runs (project_id, config_snapshot, status, total_scenes)
                   VALUES (%s, %s, 'running', 0) RETURNING id""",
                (project_id, None)
            )
            return cur.fetchone()["id"]


def complete_video_run(run_id: int, status: str = 'completed'):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "UPDATE video_runs SET status = %s, completed_at = CURRENT_TIMESTAMP WHERE id = %s",
                (status, run_id)
            )


def fail_video_run(run_id: int, error: str):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "UPDATE video_runs SET status = 'failed', completed_at = CURRENT_TIMESTAMP WHERE id = %s",
                (run_id,)
            )

# ─── Video Run Operations ──────────────────────────────────────────

def create_video_run(project_id: int, run_dir: str, config_snapshot: dict = None,
                    total_scenes: int = 0) -> int:
    """Create a new video run."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO video_runs (project_id, run_dir, config_snapshot, total_scenes, status)
                   VALUES (%s, %s, %s, %s, 'running') RETURNING id""",
                (project_id, run_dir, Json(config_snapshot) if config_snapshot else None, total_scenes)
            )
            return cur.fetchone()["id"]


def update_video_run(run_id: int, **kwargs):
    """Update video run fields."""
    allowed = ["status", "completed_scenes", "total_cost", "output_video", "caption", "completed_at"]
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k} = %s")
            vals.append(v)
    if not sets:
        return
    vals.append(run_id)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE video_runs SET {', '.join(sets)} WHERE id = %s", vals)


def get_video_run(run_id: int) -> Optional[Dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM video_runs WHERE id = %s", (run_id,))
            return cur.fetchone()


def get_runs_by_project(project_id: int) -> List[Dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM video_runs WHERE project_id = %s ORDER BY started_at DESC",
                (project_id,)
            )
            return cur.fetchall()


# ─── Scene Operations ──────────────────────────────────────────────

def create_scene(run_id: int, scene_index: int, script: str = None,
                 characters: list = None, background: str = None) -> int:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO scenes (run_id, scene_index, script, characters, background, status)
                   VALUES (%s, %s, %s, %s, %s, 'pending') RETURNING id""",
                (run_id, scene_index, script, Json(characters) if characters else None, background)
            )
            return cur.fetchone()["id"]


def update_scene(scene_id: int, **kwargs):
    allowed = ["status", "tts_audio", "image_path", "lipsync_video", "cost",
               "error_message", "completed_at"]
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k} = %s")
            vals.append(v)
    if not sets:
        return
    vals.append(scene_id)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE scenes SET {', '.join(sets)} WHERE id = %s", vals)


def get_scene(scene_id: int) -> Optional[Dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM scenes WHERE id = %s", (scene_id,))
            return cur.fetchone()


def get_scenes_by_run(run_id: int) -> List[Dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM scenes WHERE run_id = %s ORDER BY scene_index", (run_id,))
            return cur.fetchall()


# ─── API Call Operations ────────────────────────────────────────────

def log_api_call(run_id: int, scene_id: int, provider: str,
                 request_payload: dict = None, response_payload: dict = None,
                 status_code: int = None, cost: float = 0, duration_ms: int = None,
                 error: str = None) -> int:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO api_calls
                   (run_id, scene_id, provider, request_payload, response_payload,
                    status_code, cost, duration_ms, error)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (run_id, scene_id, provider,
                 Json(request_payload) if request_payload else None,
                 Json(response_payload) if response_payload else None,
                 status_code, cost, duration_ms, error)
            )
            return cur.fetchone()["id"]


def get_api_calls_by_run(run_id: int) -> List[Dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM api_calls WHERE run_id = %s ORDER BY created_at", (run_id,))
            return cur.fetchall()


# ─── Credits Operations ─────────────────────────────────────────────

def log_credit(provider: str, amount: float, balance_after: float = None,
               reason: str = None, api_call_id: int = None):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO credits_log (provider, amount, balance_after, reason, api_call_id)
                   VALUES (%s, %s, %s, %s, %s)""",
                (provider, amount, balance_after, reason, api_call_id)
            )


def get_credits_balance(provider: str) -> float:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT balance_after FROM credits_log WHERE provider = %s ORDER BY created_at DESC LIMIT 1",
                (provider,)
            )
            row = cur.fetchone()
            return row["balance_after"] if row else 0.0


def get_credits_log(provider: str = None, limit: int = 50) -> List[Dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if provider:
                cur.execute(
                    "SELECT * FROM credits_log WHERE provider = %s ORDER BY created_at DESC LIMIT %s",
                    (provider, limit)
                )
            else:
                cur.execute("SELECT * FROM credits_log ORDER BY created_at DESC LIMIT %s", (limit,))
            return cur.fetchall()


# ─── Social Post Operations ────────────────────────────────────────

def create_social_post(run_id: int, platform: str, video_path: str = None,
                       caption: str = None, srt_path: str = None) -> int:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO social_posts (run_id, platform, video_path, caption, srt_path, status)
                   VALUES (%s, %s, %s, %s, %s, 'pending') RETURNING id""",
                (run_id, platform, video_path, caption, srt_path)
            )
            return cur.fetchone()["id"]


def update_social_post(post_id: int, **kwargs):
    allowed = ["status", "post_id", "post_url", "error", "posted_at"]
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k} = %s")
            vals.append(v)
    if not sets:
        return
    vals.append(post_id)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE social_posts SET {', '.join(sets)} WHERE id = %s", vals)


def get_social_posts_by_run(run_id: int) -> List[Dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM social_posts WHERE run_id = %s ORDER BY created_at", (run_id,))
            return cur.fetchall()


def get_pending_social_posts() -> List[Dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM social_posts WHERE status = 'pending' ORDER BY created_at")
            return cur.fetchall()


# ─── Credentials Operations ──────────────────────────────────────────

def save_credential(platform: str, credential_name: str, credential_value: str):
    """Save or update a credential."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO credentials (platform, credential_name, credential_value, updated_at)
                   VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                   ON CONFLICT (platform, credential_name) DO UPDATE
                   SET credential_value = EXCLUDED.credential_value,
                       updated_at = CURRENT_TIMESTAMP""",
                (platform, credential_name, credential_value)
            )


def get_credential(platform: str, credential_name: str = None) -> Optional[str]:
    with get_db() as conn:
        with conn.cursor() as cur:
            if credential_name:
                cur.execute(
                    "SELECT credential_value FROM credentials WHERE platform = %s AND credential_name = %s",
                    (platform, credential_name)
                )
            else:
                cur.execute(
                    "SELECT credential_value FROM credentials WHERE platform = %s LIMIT 1",
                    (platform,)
                )
            row = cur.fetchone()
            return row["credential_value"] if row else None


def get_all_credentials(platform: str) -> Dict[str, str]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT credential_name, credential_value FROM credentials WHERE platform = %s",
                (platform,)
            )
            return {row["credential_name"]: row["credential_value"] for row in cur.fetchall()}


def delete_credential(platform: str, credential_name: str) -> bool:
    """Delete a credential by platform and name. Returns True if a row was deleted."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM credentials WHERE platform = %s AND credential_name = %s",
                (platform, credential_name)
            )
            return cur.rowcount > 0

if __name__ == "__main__":
    init_db()
    print("Database initialized OK")
