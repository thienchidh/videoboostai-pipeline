"""
db_models.py — SQLAlchemy declarative models for all database tables.
Replaces raw SQL CREATE TABLE statements from the old db.py init_db().
"""
import datetime
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, Time,
    ForeignKey, Index, UniqueConstraint, JSON
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    config_file = Column(String(500))
    description = Column(Text)
    status = Column(String(50), default="active")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    runs = relationship("VideoRun", back_populates="project", cascade="all, delete-orphan")


class VideoRun(Base):
    __tablename__ = "video_runs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_dir = Column(String(500))
    config_snapshot = Column(JSON)
    status = Column(String(50), default="running")
    total_scenes = Column(Integer)
    completed_scenes = Column(Integer, default=0)
    total_cost = Column(Integer, default=0)  # stored as int (cents) to avoid float issues
    output_video = Column(String(500))
    caption = Column(Text)
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime)

    project = relationship("Project", back_populates="runs")
    scenes = relationship("Scene", back_populates="run", cascade="all, delete-orphan")
    api_calls = relationship("APICall", back_populates="run", cascade="all, delete-orphan")
    social_posts = relationship("SocialPost", back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_runs_project", "project_id"),
    )


class Scene(Base):
    __tablename__ = "scenes"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("video_runs.id", ondelete="CASCADE"), nullable=False)
    scene_index = Column(Integer, nullable=False)
    script = Column(Text)
    characters = Column(JSON)  # list of character names
    background = Column(String(100))
    tts_audio = Column(String(500))
    tts_voice = Column(String(100))
    image_path = Column(String(500))
    image_prompt = Column(Text)
    lipsync_video = Column(String(500))
    status = Column(String(50), default="pending")
    error_message = Column(Text)
    cost = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime)

    run = relationship("VideoRun", back_populates="scenes")
    api_calls = relationship("APICall", back_populates="scene")

    __table_args__ = (
        Index("idx_scenes_run", "run_id"),
    )


class APICall(Base):
    __tablename__ = "api_calls"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("video_runs.id", ondelete="CASCADE"), nullable=False)
    scene_id = Column(Integer, ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True)
    provider = Column(String(50), nullable=False)
    endpoint = Column(String(200))
    request_payload = Column(JSON)
    response_payload = Column(JSON)
    status_code = Column(Integer)
    cost = Column(Integer, default=0)
    duration_ms = Column(Integer)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    run = relationship("VideoRun", back_populates="api_calls")
    scene = relationship("Scene", back_populates="api_calls")
    credits_log_entries = relationship("CreditsLog", back_populates="api_call")

    __table_args__ = (
        Index("idx_api_calls_run", "run_id"),
    )


class CreditsLog(Base):
    __tablename__ = "credits_log"

    id = Column(Integer, primary_key=True)
    provider = Column(String(50), nullable=False)
    amount = Column(Integer, nullable=False)  # stored as int (cents)
    balance_after = Column(Integer)
    reason = Column(String(200))
    api_call_id = Column(Integer, ForeignKey("api_calls.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    api_call = relationship("APICall", back_populates="credits_log_entries")

    __table_args__ = (
        Index("idx_credits_provider", "provider"),
    )


class SocialPost(Base):
    __tablename__ = "social_posts"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("video_runs.id", ondelete="CASCADE"), nullable=False)
    platform = Column(String(50), nullable=False)
    post_id = Column(String(200))
    post_url = Column(String(500))
    caption = Column(Text)
    video_path = Column(String(500))
    srt_path = Column(String(500))
    status = Column(String(50), default="pending")
    error = Column(Text)
    posted_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    run = relationship("VideoRun", back_populates="social_posts")

    __table_args__ = (
        Index("idx_social_posts_run", "run_id"),
    )


class Credential(Base):
    __tablename__ = "credentials"
    __table_args__ = (
        UniqueConstraint("platform", "credential_name", name="uq_credentials_platform_name"),
    )

    id = Column(Integer, primary_key=True)
    platform = Column(String(50), nullable=False)
    credential_name = Column(String(100), nullable=False)
    credential_value = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class ContentIdea(Base):
    __tablename__ = "content_ideas"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(500))
    topic_keywords = Column(Text)
    script_json = Column(JSON)
    platform = Column(String(50))
    status = Column(String(50), default="idea")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    project = relationship("Project")
    calendar_entries = relationship("ContentCalendar", back_populates="idea")

    __table_args__ = (
        Index("idx_content_ideas_project", "project_id"),
    )


class ContentCalendar(Base):
    __tablename__ = "content_calendar"

    id = Column(Integer, primary_key=True)
    idea_id = Column(Integer, ForeignKey("content_ideas.id", ondelete="CASCADE"), nullable=False)
    platform = Column(String(50))
    scheduled_date = Column(Date)
    scheduled_time = Column(Time)
    status = Column(String(50), default="scheduled")
    priority = Column(String(20), default="medium")
    notes = Column(Text)
    video_run_id = Column(Integer, ForeignKey("video_runs.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    idea = relationship("ContentIdea", back_populates="calendar_entries")
    video_run = relationship("VideoRun")

    __table_args__ = (
        Index("idx_content_calendar_idea", "idea_id"),
        Index("idx_content_calendar_status", "status"),
        Index("idx_content_calendar_scheduled", "scheduled_date"),
    )


class TopicSource(Base):
    __tablename__ = "topic_sources"

    id = Column(Integer, primary_key=True)
    source_type = Column(String(50))
    source_query = Column(Text)
    topics = Column(JSON)  # list of topic dicts
    created_at = Column(DateTime, default=datetime.datetime.utcnow)