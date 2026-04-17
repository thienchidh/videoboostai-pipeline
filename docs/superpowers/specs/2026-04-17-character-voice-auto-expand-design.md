# Character Voice Auto-Expansion Design

## Problem Statement

LLM generates scenes with character names not in `channel.characters` (e.g., "Teacher", "Expert" instead of "Mentor", "Student"). When `get_character()` returns None, the pipeline falls back to the first voice in catalog — ignoring gender entirely. This causes wrong voice gender (male voice for female character or vice versa).

## Solution

Auto-create new characters with correct voice when LLM outputs an unknown character name with explicit gender.

## Architecture

### Data Flow

```
LLM generates scene JSON: {character: "Teacher", gender: "male", ...}
    → _validate_scenes(): captures gender field from dict
    → resolve_voice(): get_character("Teacher") → None
    → _ensure_character("Teacher", "male")
        → creates VoiceConfig(id="auto_teacher", gender="male")
        → creates CharacterConfig(name="Teacher", voice_id="auto_teacher")
        → appends to channel.voices and channel.characters
    → get_voice("auto_teacher") → found
    → returns (edge, vi-VN-NamMinhNeural, 1.0, "male")
```

### Changes

#### 1. SceneConfig model — add `gender` field

File: `modules/pipeline/models.py`

```python
class SceneConfig(BaseModel):
    ...
    character: str   # existing
    gender: Optional[str] = None  # NEW: male|female, from LLM output
```

#### 2. LLM prompt — require gender in scene JSON

File: `modules/content/content_idea_generator.py`

Add to `_build_scene_prompt()` scene structure example:

```
"character": "Teacher"
"gender": "male"
```

Prompt instruction: "Include `gender` field for each scene — must be `male` or `female`.

#### 3. `_validate_scenes()` — capture gender from parsed dict

File: `modules/content/content_idea_generator.py`

```python
def _validate_scenes(self, scenes: List[Dict]) -> List[SceneConfig]:
    ...
    for scene in scenes:
        ...
        scene["gender"] = scene.get("gender")  # capture for resolve_voice
        validated.append(scene)
    return [SceneConfig.from_dict(s) for s in validated]
```

#### 4. SceneProcessor — add `_ensure_character()` method

File: `modules/pipeline/scene_processor.py`

```python
def _ensure_character(self, char_name: str, gender: str):
    """Create CharacterConfig + VoiceConfig if character doesn't exist in channel.

    Args:
        char_name: Name from LLM output (e.g., "Teacher", "Expert")
        gender: "male" or "female" from LLM output
    """
    existing = self.get_character(char_name)
    if existing:
        return

    # Create safe voice_id from char_name
    voice_id = f"auto_{char_name.lower().replace(' ', '_')}"

    # Determine TTS model based on gender
    model = self._default_voice_model(gender)

    voice = VoiceConfig(
        id=voice_id,
        name=char_name,
        gender=gender,
        providers=[VoiceProvider(provider="edge", model=model, speed=1.0)],
    )
    char = CharacterConfig(name=char_name, voice_id=voice_id)

    self.ctx.channel.voices.append(voice)
    self.ctx.channel.characters.append(char)
    logger.info(f"Auto-created character '{char_name}' (gender={gender}, voice_id={voice_id})")


def _default_voice_model(self, gender: str) -> str:
    """Return appropriate Edge TTS model for gender."""
    if gender == "male":
        return "vi-VN-NamMinhNeural"
    return "vi-VN-HoaiMyNeural"  # female as default fallback
```

#### 5. `resolve_voice()` — use `_ensure_character()`

File: `modules/pipeline/scene_processor.py`

Modify `resolve_voice()` to call `_ensure_character()` before falling back:

```python
def resolve_voice(self, character, scene: SceneConfig) -> Tuple[str, str, float, str]:
    voice_id = character.voice_id
    voice = self.get_voice(voice_id) if voice_id else None

    if voice and voice.providers:
        primary = voice.providers[0]
        return (primary.provider, primary.model, primary.speed, voice.gender or "female")

    # Character not found — try auto-creation with gender from scene
    char_name = character.name
    gender = getattr(scene, 'gender', None) if scene else None

    if gender in ("male", "female"):
        self._ensure_character(char_name, gender)
        # Retry lookup
        voice = self.get_voice(f"auto_{char_name.lower().replace(' ', '_')}")
        if voice and voice.providers:
            primary = voice.providers[0]
            return (primary.provider, primary.model, primary.speed, gender)

    # Final fallback: first voice in catalog
    fallback_provider = self.ctx.channel.generation.models.tts if self.ctx.channel.generation else None
    fallback_voice_id = "female_voice"
    voices = self.ctx.channel.voices or []
    if voices:
        fallback_voice_id = voices[0].id
    return fallback_provider or "edge", fallback_voice_id, 1.0, "female"
```

## Edge Cases

| Case | Behavior |
|------|----------|
| No gender in LLM output | Fallback to female (safe default) |
| Duplicate auto-created characters | `_ensure_character` checks `get_character()` first — idempotent |
| Auto-created not persisted | Characters exist only in-memory per-run; no config file persistence |
| Both male and female in same scene | Each scene's character handled independently |

## Files to Modify

| File | Change |
|------|--------|
| `modules/pipeline/models.py` | Add `gender: Optional[str]` to `SceneConfig` |
| `modules/content/content_idea_generator.py` | Add gender to LLM prompt + capture in `_validate_scenes()` |
| `modules/pipeline/scene_processor.py` | Add `_ensure_character()`, `_default_voice_model()`; update `resolve_voice()` |

## Testing

1. **LLM outputs unknown character with gender** — verify auto-creation
2. **Character already exists** — verify no duplicate, uses existing
3. **No gender from LLM** — verify fallback to female
4. **Multiple scenes with different auto-characters** — verify all created correctly
