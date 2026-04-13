"""
modules/pipeline/models.py — Pydantic models for configuration validation.

Provides validated config models for:
- TechnicalConfig: API keys, URLs, generation params
- ChannelConfig: per-channel settings, content research
- PipelineConfig: merged pipeline config
"""
from pydantic import BaseModel
from typing import Optional


# ─── Technical Config ───────────────────────────────────────

class APIKeys(BaseModel):
    wavespeed: str
    minimax: str
    kie_ai: str
    you_search: str


class APIURLs(BaseModel):
    wavespeed: str
    minimax_tts: str
    minimax_image: str
    kie_ai: str
    tiktok: str
    facebook_graph: str


class GenerationModels(BaseModel):
    tts: str = "edge"
    image: str = "minimax"
    video: str = "kieai"


class GenerationLLM(BaseModel):
    provider: str = "minimax"
    model: str = "MiniMax-M2.7"
    max_tokens: int = 1536
    timeout: int = 60


class GenerationTTS(BaseModel):
    max_duration: float = 15.0
    min_duration: float = 5.0
    words_per_second: float = 2.5


class GenerationLipsync(BaseModel):
    provider: str = "kieai"
    prompt: str = "A person talking"
    resolution: str = "480p"
    max_wait: int = 300


class GenerationImage(BaseModel):
    provider: str = "minimax"
    fallback_providers: list[str] = []
    aspect_ratio: str = "9:16"
    timeout: int = 120


class GenerationSeeds(BaseModel):
    image: int = 42
    video: int = 12345


class GenerationConfig(BaseModel):
    llm: GenerationLLM
    image: GenerationImage
    tts: GenerationTTS
    lipsync: GenerationLipsync
    seeds: GenerationSeeds


class S3Config(BaseModel):
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    region: str = "us-east-1"
    public_url_base: str


class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str = "videopipeline"
    user: str = "videopipeline"
    password: str = "videopipeline123"


class StorageConfig(BaseModel):
    s3: S3Config
    database: DatabaseConfig


class TechnicalConfig(BaseModel):
    api_keys: APIKeys
    api_urls: APIURLs
    models: GenerationModels
    generation: GenerationConfig
    storage: StorageConfig


# ─── Channel Config ─────────────────────────────────────────

class ContentResearch(BaseModel):
    niche_keywords: list[str]
    content_angle: str = "tips"
    target_platform: str = "both"
    research_interval_hours: int = 24


class CharacterConfig(BaseModel):
    name: str
    voice_id: str


class VoiceConfig(BaseModel):
    id: str
    name: str
    gender: str
    providers: list[dict]


class TTSConfig(BaseModel):
    max_duration: float
    min_duration: float
    words_per_second: float


class WatermarkConfig(BaseModel):
    enable: bool = True
    text: str
    font_size: int = 30
    opacity: float = 0.15
    motion: str = "bounce"
    bounce_speed: int = 80
    bounce_padding: int = 20
    velocity_x: float = 1.2
    velocity_y: float = 0.8
    margin: int = 8


class ImageStyle(BaseModel):
    lighting: str = "warm"
    camera: str = "eye-level"
    art_style: str = "3D render"
    environment: str = "modern office"
    composition: str = "professional"


class LLMConfig(BaseModel):
    provider: str = "minimax"
    model: str = "MiniMax-M2.7"
    max_tokens: int = 2048


class SocialConfig(BaseModel):
    facebook: Optional[dict] = None
    tiktok: Optional[dict] = None


class ChannelConfig(BaseModel):
    channel_id: str
    name: str
    characters: list[dict]
    tts: TTSConfig
    watermark: WatermarkConfig
    style: str
    research: ContentResearch
    voices: Optional[list[dict]] = None
    video: Optional[dict] = None
    fonts: Optional[dict] = None
    generation: Optional[dict] = None
    subtitle: Optional[dict] = None
    background_music: Optional[dict] = None
    image_style: Optional[ImageStyle] = None
    default_models: Optional[dict] = None
    lipsync: Optional[dict] = None
    llm: Optional[LLMConfig] = None
    social: Optional[SocialConfig] = None


# ─── Pipeline Config ────────────────────────────────────────

class PipelineConfigData(BaseModel):
    """Merged data dict from all config sources."""
    data: dict
    # Resolved API keys
    wavespeed_key: str
    wavespeed_base: str
    minimax_key: str
    kieai_key: str
    # Provider preference
    lipsync_provider: str
    # S3 config
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    s3_region: str
    s3_public_url_base: str
    # Paths (stored as strings, converted by callers as needed)
    output_dir: str
    avatars_dir: str
    # Run metadata
    timestamp: int = 0
    run_id: str = ""
    run_dir: str = "."
    media_dir: str = "."

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def get_nested(self, *keys, default=None):
        val = self.data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
        return val if val is not None else default


# Re-export for backward compatibility
# (existing code uses PipelineConfig from config_loader, not this Pydantic model)
# When ConfigLoader is fully Pydantic-ified, this will replace the dataclass.
PipelineConfig = PipelineConfigData
