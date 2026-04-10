"""
core/plugins.py — Plugin registry for video pipeline providers

Provides a registry for swappable provider implementations:
- TTSProvider: MiniMax, Edge, mock
- ImageProvider: MiniMax, WaveSpeed, mock
- LipsyncProvider: WaveSpeed/LTX, mock
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Type

logger = logging.getLogger(__name__)

# ==================== Provider Base Classes ====================


class TTSProvider(ABC):
    """Abstract base for text-to-speech providers."""

    @abstractmethod
    def generate(self, text: str, voice: str = "female_voice", speed: float = 1.0,
                 output_path: Optional[str] = None) -> Optional[str]:
        """Generate TTS audio file. Returns path to audio file or None."""
        ...

    def get_word_timestamps(self, text: str, voice: str,
                            speed: float) -> Optional[List[Dict[str, Any]]]:
        """Optional: return word timestamps for karaoke subtitles."""
        return None


class ImageProvider(ABC):
    """Abstract base for image generation providers."""

    @abstractmethod
    def generate(self, prompt: str, output_path: str,
                 aspect_ratio: str = "9:16") -> Optional[str]:
        """Generate image. Returns path to image file or None."""
        ...


class LipsyncProvider(ABC):
    """Abstract base for video lipsync providers."""

    @abstractmethod
    def generate(self, image_path: str, audio_path: str,
                 output_path: str, config: Optional[Dict] = None) -> Optional[str]:
        """Generate lipsync video. Returns path to video file or None."""
        ...


# ==================== Plugin Registry ====================

class PluginRegistry:
    """Central registry for provider plugins."""

    def __init__(self):
        self._tts: Dict[str, Type[TTSProvider]] = {}
        self._image: Dict[str, Type[ImageProvider]] = {}
        self._lipsync: Dict[str, Type[LipsyncProvider]] = {}

    def register_tts(self, name: str, provider_class: Type[TTSProvider]) -> None:
        self._tts[name] = provider_class
        logger.debug(f"Registered TTS provider: {name}")

    def register_image(self, name: str, provider_class: Type[ImageProvider]) -> None:
        self._image[name] = provider_class
        logger.debug(f"Registered image provider: {name}")

    def register_lipsync(self, name: str, provider_class: Type[LipsyncProvider]) -> None:
        self._lipsync[name] = provider_class
        logger.debug(f"Registered lipsync provider: {name}")

    def get_tts(self, name: str) -> Optional[Type[TTSProvider]]:
        return self._tts.get(name)

    def get_image(self, name: str) -> Optional[Type[ImageProvider]]:
        return self._image.get(name)

    def get_lipsync(self, name: str) -> Optional[Type[LipsyncProvider]]:
        return self._lipsync.get(name)

    def list_tts(self) -> List[str]:
        return list(self._tts.keys())

    def list_image(self) -> List[str]:
        return list(self._image.keys())

    def list_lipsync(self) -> List[str]:
        return list(self._lipsync.keys())


# Global registry instance
_registry = PluginRegistry()


def register_provider(category: str, name: str, cls: Type) -> None:
    """Register a provider: register_provider('tts', 'minimax', MiniMaxTTSProvider)"""
    if category == "tts":
        _registry.register_tts(name, cls)
    elif category == "image":
        _registry.register_image(name, cls)
    elif category == "lipsync":
        _registry.register_lipsync(name, cls)
    else:
        raise ValueError(f"Unknown provider category: {category}")


def get_provider(category: str, name: str) -> Optional[Type]:
    """Get a provider class by category and name."""
    if category == "tts":
        return _registry.get_tts(name)
    elif category == "image":
        return _registry.get_image(name)
    elif category == "lipsync":
        return _registry.get_lipsync(name)
    return None


def list_providers(category: str) -> List[str]:
    """List all registered providers for a category."""
    if category == "tts":
        return _registry.list_tts()
    elif category == "image":
        return _registry.list_image()
    elif category == "lipsync":
        return _registry.list_lipsync()
    return []
