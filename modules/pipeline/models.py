"""
modules/pipeline/models.py — Pydantic models for configuration validation.

Provides validated config models for:
- TechnicalConfig: API keys, URLs, generation params
- ChannelConfig: per-channel settings, content research
- ScenarioConfig: scenes and title from scenario files
"""
from pydantic import BaseModel
from typing import Optional, Any, List, Dict
import yaml
from pathlib import Path

from core.paths import PROJECT_ROOT


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


class ParallelSceneConfig(BaseModel):
    enabled: bool = True
    max_workers: int = 3


class GenerationConfig(BaseModel):
    llm: GenerationLLM
    image: GenerationImage
    tts: GenerationTTS
    lipsync: GenerationLipsync
    seeds: GenerationSeeds
    parallel_scene_processing: ParallelSceneConfig = ParallelSceneConfig()


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


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s %(levelname)s %(message)s"


class ObserverConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8765
    enabled: bool = False


class TechnicalConfig(BaseModel):
    api_keys: APIKeys
    api_urls: APIURLs
    models: GenerationModels
    generation: GenerationConfig
    storage: StorageConfig
    logging: LoggingConfig = LoggingConfig()
    observer: Optional[ObserverConfig] = None

    @classmethod
    def load(cls) -> "TechnicalConfig":
        path = PROJECT_ROOT / "configs" / "technical" / "config_technical.yaml"
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        restructured = {
            'api_keys': data.get('api', {}).get('keys', {}),
            'api_urls': data.get('api', {}).get('urls', {}),
            'models': data.get('api', {}).get('models', {}),
            'generation': data.get('generation', {}),
            'storage': data.get('storage', {}),
            'logging': data.get('logging', {}),
        }
        if 'observer' in data:
            restructured['observer'] = data['observer']
        return cls(**restructured)


# ─── Channel Config ─────────────────────────────────────────

class ContentResearch(BaseModel):
    niche_keywords: list[str]
    content_angle: str = "tips"
    target_platform: str = "both"
    research_interval_hours: int = 24


class CharacterConfig(BaseModel):
    name: str
    voice_id: str


class VoiceProvider(BaseModel):
    provider: str
    model: str
    speed: float = 1.0
    voice: Optional[str] = None  # openai uses 'voice' instead of 'model'


class VoiceConfig(BaseModel):
    id: str
    name: str
    gender: str
    providers: list[VoiceProvider]


class VideoSettings(BaseModel):
    aspect_ratio: str = "9:16"
    resolution: str = "480p"


class FontConfig(BaseModel):
    watermark: str


class GenerationSettings(BaseModel):
    models: GenerationModels
    lipsync: GenerationLipsync


class SubtitleConfig(BaseModel):
    font_size: int = 60


class BackgroundMusicConfig(BaseModel):
    enable: bool = True
    file: str = "random"
    volume: float = 0.15
    fade_duration: int = 2


class ImageStyleConfig(BaseModel):
    lighting: str = "warm"
    camera: str = "eye-level"
    art_style: str = "3D render"
    environment: str = "modern office"
    composition: str = "professional"


class DefaultModelsConfig(BaseModel):
    tts: str = "edge"
    image: str = "minimax"
    video: str = "kieai"


class LipsyncSettings(BaseModel):
    provider: str = "kieai"
    resolution: str = "480p"
    max_wait: int = 300


class LLMConfig(BaseModel):
    provider: str = "minimax"
    model: str = "MiniMax-M2.7"
    max_tokens: int = 2048


class SocialPlatformConfig(BaseModel):
    page_name: Optional[str] = None
    account_name: Optional[str] = None
    auto_publish: bool = False
    # Auth fields loaded from config file or secrets manager
    page_id: Optional[str] = None
    access_token: Optional[str] = None
    advertiser_id: Optional[str] = None
    account_id: Optional[str] = None


class SocialConfig(BaseModel):
    facebook: SocialPlatformConfig
    tiktok: SocialPlatformConfig

    @classmethod
    def load(cls, path: str | Path) -> "SocialConfig":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Social config not found: {path}")
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(**data)


class TTSConfig(BaseModel):
    max_duration: float
    min_duration: float


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


class ChannelConfig(BaseModel):
    channel_id: str
    name: str
    characters: list[CharacterConfig]
    tts: TTSConfig
    watermark: WatermarkConfig
    style: str
    research: ContentResearch
    voices: Optional[list[VoiceConfig]] = None
    video: Optional[VideoSettings] = None
    fonts: Optional[FontConfig] = None
    generation: Optional[GenerationSettings] = None
    subtitle: Optional[SubtitleConfig] = None
    background_music: Optional[BackgroundMusicConfig] = None
    image_style: Optional[ImageStyleConfig] = None
    default_models: Optional[DefaultModelsConfig] = None
    lipsync: Optional[LipsyncSettings] = None
    llm: Optional[LLMConfig] = None
    social: Optional[SocialConfig] = None

    @classmethod
    def load(cls, channel_id: str) -> "ChannelConfig":
        path = PROJECT_ROOT / "configs" / "channels" / channel_id / "config.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Channel config not found: {path}")
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(**data)


# ─── Scenario Config ────────────────────────────────────────

class SceneCharacter(BaseModel):
    """Character trong scene — hỗ trợ cả string (name) và dict với overrides."""
    name: str
    tts: Optional[str] = None
    speed: Optional[float] = None

    @classmethod
    def from_yaml(cls, data: "str | dict") -> "SceneCharacter":
        """Parse từ YAML — chấp nhận string (name) hoặc dict."""
        if isinstance(data, str):
            return cls(name=data)
        return cls(**data)


class SceneConfig(BaseModel):
    """Một scene từ scenario YAML file."""
    id: int = 0
    tts: Optional[str] = None
    script: Optional[str] = None  # alternative to tts
    characters: List["SceneCharacter | str"] = []
    video_prompt: Optional[str] = None
    background: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "SceneConfig":
        """Parse scene từ dict — convert characters list.

        Supports both 'character' (singular string, our normalized format)
        and 'characters' (plural array) from older formats.
        """
        # Support both 'character' (singular string) and 'characters' (array)
        raw_chars = data.get("characters", [])
        if not raw_chars and "character" in data:
            # Normalize singular 'character' to list format
            raw_chars = [data["character"]]

        parsed_chars = [SceneCharacter.from_yaml(c) for c in raw_chars]
        return cls(
            id=data.get("id", 0),
            tts=data.get("tts"),
            script=data.get("script"),
            characters=parsed_chars,
            video_prompt=data.get("video_prompt"),
            background=data.get("background"),
        )


class ScenarioConfig(BaseModel):
    """Scenes and title from scenario YAML files."""
    scenes: List[SceneConfig]
    title: str = ""
    slug: Optional[str] = None

    @classmethod
    def load(cls, path: str | Path) -> "ScenarioConfig":
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        scenes = [SceneConfig.from_dict(s) for s in data.get("scenes", [])]
        slug = path.stem
        instance = cls(scenes=scenes, title=data.get("title", ""))
        instance.slug = slug
        return instance


class ContentPipelineConfig(BaseModel):
    """Business config for content pipeline - social pages and content settings."""
    page: Dict[str, Dict[str, Any]]
    content: Dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "ContentPipelineConfig":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Content pipeline config not found: {path}")
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(**data)

    @classmethod
    def load_or_default(cls, path: str | Path) -> "ContentPipelineConfig":
        """Load config, or return sensible defaults if file not found."""
        try:
            return cls.load(path)
        except FileNotFoundError:
            return cls(**{
                "page": {
                    "facebook": {"page_id": "YOUR_PAGE_ID", "page_name": "NangSuatThongMinh"},
                    "tiktok": {"account_id": "YOUR_TIKTOK_ACCOUNT_ID", "account_name": "@NangSuatThongMinh"}
                },
                "content": {
                    "auto_schedule": True
                }
            })


