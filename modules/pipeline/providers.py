"""
modules/pipeline/providers.py
Explicit provider registration — replaces implicit import side-effects.
Import this module (or call register_all()) before using any provider via PluginRegistry.
"""
from modules.media.tts import register_tts_providers
from modules.media.image_gen import register_image_providers
from modules.media.lipsync import register_lipsync_providers
from modules.media.music_gen import register_music_providers


def register_all():
    """Register all providers with PluginRegistry."""
    register_tts_providers()
    register_image_providers()
    register_lipsync_providers()
    register_music_providers()


register_all()
