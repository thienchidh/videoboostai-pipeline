"""
modules/pipeline/config.py — PipelineContext for config management.

Provides a context object per pipeline run with direct access to:
- TechnicalConfig: API keys, URLs, storage
- ChannelConfig: per-channel settings (characters, voices, watermark, social, etc.)
- ScenarioConfig: scenes and title

Thread-safe: each pipeline run gets its own PipelineContext instance.
"""

from modules.pipeline.models import (
    TechnicalConfig,
    ChannelConfig,
    ScenarioConfig,
    SocialConfig,
)


class PipelineContext:
    """Config context for a single pipeline run.

    Attributes:
        channel_id: Channel identifier
        technical: Technical config (API keys, URLs, storage)
        channel: Channel config (characters, voices, watermark, social, etc.)
        scenario: Scenario config (scenes, title) - loaded on demand via use_scenario()
    """

    def __init__(self, channel_id: str, scenario_path: str = None):
        """
        Args:
            channel_id: Channel identifier (e.g., 'nang_suat_thong_minh')
            scenario_path: Optional path to scenario YAML file.
                          If None, call use_scenario() later to load.
        """
        self.channel_id = channel_id
        self.technical = TechnicalConfig.load()
        self.channel = ChannelConfig.load(channel_id)
        self._scenario: ScenarioConfig = None

        if scenario_path:
            self.use_scenario(scenario_path)

    def use_scenario(self, path: str):
        """Load scenario from a YAML file.

        Args:
            path: Path to scenario YAML file.
                  Example: 'configs/channels/nang_suat_thong_minh/scenarios/2026-04-13/scenario.yaml'
        """
        self._scenario = ScenarioConfig.load(path)

    @property
    def scenario(self) -> ScenarioConfig:
        """Get loaded scenario.

        Raises:
            RuntimeError: If no scenario has been loaded.
        """
        if self._scenario is None:
            raise RuntimeError("No scenario loaded. Call use_scenario(path) first.")
        return self._scenario

    @property
    def social(self) -> SocialConfig:
        """Direct access to social config from channel."""
        return self.channel.social
