"""
modules/pipeline/models.py — Pydantic models for configuration validation.

Provides validated config models for:
- TechnicalConfig: API keys, URLs, generation params
- ChannelConfig: per-channel settings, content research
- ScenarioConfig: scenes and title from scenario files
"""
from pydantic import BaseModel, field_validator
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
    retry_attempts: int = 3
    retry_backoff_max: int = 10


class GenerationTTS(BaseModel):
    model: str = "speech-2.1-hd"
    sample_rate: int = 32000
    timeout: int = 60
    max_duration: float = 15.0
    min_duration: float = 5.0
    words_per_second: float = 2.5
    bitrate: int = 128000
    format: str = "mp3"
    channel: int = 1
    word_timestamp_timeout: int = 120


class GenerationLipsync(BaseModel):
    provider: str = "kieai"
    prompt: str = "A person talking"
    resolution: str = "480p"
    max_wait: int = 7200   # 120 minutes — align with YAML config
    poll_interval: int = 10
    retries: int = 2
    seed: Optional[int] = None


class GenerationImage(BaseModel):
    provider: str = "minimax"
    fallback_providers: list[str] = []
    aspect_ratio: str = "9:16"
    timeout: int = 300
    model: str = "image-01"
    poll_interval: int = 5
    max_polls: int = 24


class GenerationSeeds(BaseModel):
    image: int = 42
    video: int = 12345


class GenerationPipeline(BaseModel):
    max_retries: int = 3


class ParallelSceneConfig(BaseModel):
    enabled: bool = True
    max_workers: int = 3


class GenerationContent(BaseModel):
    scene_count: int = 3
    checkpoint_path: str = ".content_pipeline_checkpoint.json"


class ResearchConfig(BaseModel):
    schedule_hour: int = 9
    schedule_minute: int = 0


class VideoUpscaleConfig(BaseModel):
    enabled: bool = False
    crf: int = 18
    preset: str = "slow"
    fps: int = 60
    use_gpu: bool = True  # use NVIDIA NVENC GPU encoding if available


class GenerationConfig(BaseModel):
    llm: GenerationLLM
    image: GenerationImage
    tts: GenerationTTS
    lipsync: GenerationLipsync
    seeds: GenerationSeeds
    parallel_scene_processing: ParallelSceneConfig = ParallelSceneConfig()
    content: GenerationContent = GenerationContent()
    research: ResearchConfig = ResearchConfig()
    pipeline: GenerationPipeline = GenerationPipeline()
    video_upscale: Optional[VideoUpscaleConfig] = None


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
    output_dir: str = "output"
    temp_dir: Optional[str] = None
    s3: S3Config
    database: DatabaseConfig


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s %(levelname)s %(message)s"


class ObserverConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8765
    enabled: bool = False


class EmbeddingConfig(BaseModel):
    model: str = "distiluse-base-multilingual-cased-v2"
    similarity_threshold: float = 0.75
    translation_max_tokens: int = 200


class TechnicalConfig(BaseModel):
    api_keys: APIKeys
    api_urls: APIURLs
    models: GenerationModels
    generation: GenerationConfig
    storage: StorageConfig
    logging: LoggingConfig = LoggingConfig()
    observer: Optional[ObserverConfig] = None
    embedding: EmbeddingConfig = EmbeddingConfig()

    def get(self, key: str, default=None):
        """Dict-like access for backward compatibility with code using config.get('a.b.c').

        Translates YAML-style paths to Pydantic attribute paths:
        - 'api.urls.minimax_tts' -> api_urls.minimax_tts (api -> api_urls, drop 'urls')
        - 'api.keys.minimax' -> api_keys.minimax
        - 'generation.tts.model' -> generation.tts.model (direct Pydantic attrs)
        - 'storage.temp_dir' -> storage.temp_dir
        """
        parts = key.split('.')

        # Handle 'api.urls.X' -> 'api_urls.X' (drop 'urls', combine first and last)
        if len(parts) >= 3 and parts[0] == 'api' and parts[1] == 'urls':
            # 'api.urls.minimax_tts' -> 'api_urls.minimax_tts'
            parts = ['api_urls', parts[2]]
        elif parts[0] == 'api_keys':
            # 'api_keys.minimax' -> 'api_keys.minimax' (no change needed)
            pass
        elif parts[0] == 'api':
            # 'api.keys.X' -> 'api_keys.X'
            parts = ['api_keys'] + parts[2:]

        obj = self
        for part in parts:
            if obj is None:
                return default
            if hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                return default
        return obj

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
        if 'embedding' in data:
            restructured['embedding'] = data['embedding']
        return cls(**restructured)


# ─── Channel Config ─────────────────────────────────────────

class ContentResearch(BaseModel):
    niche_keywords: list[str]
    content_angle: str = "tips"
    target_platform: str = "both"
    research_interval_hours: int = 24
    schedule: Optional[str] = "2h"           # "2h" = twice daily
    threshold: int = 3                        # trigger research if pending pool < 3
    pending_pool_size: int = 5               # min ideas in pool before skip research


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
    max_wait: int = 7200


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
    tts: Optional[TTSConfig] = None
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
    characters: List[SceneCharacter] = []
    video_prompt: Optional[str] = None   # legacy fallback for YAML scenes
    background: Optional[str] = None     # legacy fallback for YAML scenes
    image_prompt: Optional[str] = None   # LLM-generated, ready to use
    lipsync_prompt: Optional[str] = None # LLM-generated, ready to use
    creative_brief: Optional[Dict[str, Any]] = None
    scene_type: Optional[str] = None   # hook | insight | technique | proof | cta
    delivers: Optional[str] = None     # plain-language summary of viewer takeaway

    @field_validator("characters", mode="before")
    @classmethod
    def _convert_characters(cls, v):
        """Accept both ["char_name"] strings and [SceneCharacter/dict] items."""
        if not isinstance(v, list):
            return v
        result = []
        for item in v:
            if isinstance(item, str):
                result.append(SceneCharacter(name=item))
            elif isinstance(item, dict):
                result.append(SceneCharacter(**item))
            else:
                result.append(item)
        return result

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
            image_prompt=data.get("image_prompt"),
            lipsync_prompt=data.get("lipsync_prompt"),
            creative_brief=data.get("creative_brief"),
            scene_type=data.get("scene_type"),
            delivers=data.get("delivers"),
        )


class ScenarioConfig(BaseModel):
    """Scenes and title from scenario YAML files."""
    scenes: List[SceneConfig]
    title: str = ""
    slug: Optional[str] = None
    video_message: Optional[str] = None

    @classmethod
    def load(cls, path: str | Path) -> "ScenarioConfig":
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        scenes = [SceneConfig.from_dict(s) for s in data.get("scenes", [])]
        slug = path.stem
        instance = cls(scenes=scenes, title=data.get("title", ""), video_message=data.get("video_message"))
        instance.slug = slug
        return instance


class ScriptOutput(BaseModel):
    """Output từ content_idea_generator.generate_script_from_idea().

    Dùng Pydantic model thay vì Dict để có direct attribute access.
    """
    title: str
    scenes: List[SceneConfig]
    video_message: str
    content_angle: str = "tips"
    keywords: List[str] = []
    watermark: Optional[str] = None
    style: Optional[str] = None
    generated_at: Optional[str] = None


class PagePlatformConfig(BaseModel):
    page_id: Optional[str] = None
    page_name: Optional[str] = None
    account_name: Optional[str] = None
    account_id: Optional[str] = None
    auto_publish: bool = False
    access_token: Optional[str] = None


class PageConfig(BaseModel):
    facebook: PagePlatformConfig = PagePlatformConfig()
    tiktok: PagePlatformConfig = PagePlatformConfig()


class ContentSettings(BaseModel):
    auto_schedule: bool = True
    niche_keywords: list[str] = []
    content_angle: str = "tips"
    target_platform: str = "both"
    research_interval_hours: int = 24
    schedule: str = "2h"
    threshold: int = 3
    pending_pool_size: int = 5


class CheckpointData(BaseModel):
    last_processed_idea_index: int = -1
    source_id: Optional[int] = None
    idea_ids_processed: list[int] = []
    timestamp: Optional[str] = None


class LipsyncRequest(BaseModel):
    left_audio: Optional[str] = None
    right_audio: Optional[str] = None
    config: Optional["GenerationLipsync"] = None


class CTRData(BaseModel):
    ctr: float = 0.0
    impressions: int = 0
    clicks: int = 0


class ContentPipelineConfig(BaseModel):
    """Business config for content pipeline - social pages and content settings."""
    page: PageConfig = PageConfig()
    content: ContentSettings = ContentSettings()

    @classmethod
    def load(cls, path: str | Path) -> "ContentPipelineConfig":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Content pipeline config not found: {path}")
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        # Build sub-models from flat dict structure
        page_data = data.get("page", {})
        facebook_data = page_data.get("facebook", {})
        tiktok_data = page_data.get("tiktok", {})
        content_data = data.get("content", {})
        return cls(
            page=PageConfig(
                facebook=PagePlatformConfig(**facebook_data) if facebook_data else PagePlatformConfig(),
                tiktok=PagePlatformConfig(**tiktok_data) if tiktok_data else PagePlatformConfig(),
            ),
            content=ContentSettings(**content_data) if content_data else ContentSettings(),
        )

    @classmethod
    def load_or_default(cls, path: str | Path) -> "ContentPipelineConfig":
        """Load config, or return sensible defaults if file not found."""
        try:
            return cls.load(path)
        except FileNotFoundError:
            return cls(
                page=PageConfig(
                    facebook=PagePlatformConfig(
                        page_id="YOUR_PAGE_ID",
                        page_name="NangSuatThongMinh"
                    ),
                    tiktok=PagePlatformConfig(
                        account_id="YOUR_TIKTOK_ACCOUNT_ID",
                        account_name="@NangSuatThongMinh"
                    ),
                ),
                content=ContentSettings(auto_schedule=True),
            )


