"""modules/pipeline/exceptions.py — Pipeline exceptions."""


class MissingConfigError(Exception):
    """Raised when a required configuration key is missing."""
    pass


class ConfigMissingKeyError(Exception):
    """Raised when required config key is missing (strict mode)."""
    def __init__(self, key_path: str, provider: str = None):
        self.key_path = key_path
        self.provider = provider
        msg = f"Required config key missing: '{key_path}'"
        if provider:
            msg += f" (required by {provider})"
        super().__init__(msg)


class SceneDurationError(Exception):
    """Raised when scene TTS duration is outside allowed bounds.
    
    Attributes:
        scene_id: ID of the scene
        actual_duration: Actual TTS duration in seconds
        min_duration: Minimum allowed duration
        max_duration: Maximum allowed duration
        script: The script text that was used
    """

    def __init__(self, scene_id: int, actual_duration: float,
                 min_duration: float, max_duration: float, script: str = ""):
        self.scene_id = scene_id
        self.actual_duration = actual_duration
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.script = script
        
        if actual_duration < min_duration:
            msg = (f"Scene {scene_id} TTS too short: {actual_duration:.1f}s "
                   f"(min: {min_duration:.1f}s)")
        else:
            msg = (f"Scene {scene_id} TTS too long: {actual_duration:.1f}s "
                   f"(max: {max_duration:.1f}s)")
        super().__init__(msg)
