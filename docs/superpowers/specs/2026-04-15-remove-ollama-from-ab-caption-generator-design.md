# Spec: Remove Ollama from ABCaptionGenerator

## Problem

`ABCaptionGenerator` (`modules/content/ab_caption_generator.py`) still contains Ollama code:
- `subprocess.run(["curl", ...])` to call Ollama HTTP API
- `_check_ollama()`, `_call_llm()` methods
- `ollama_host`, `model`, `use_llm` parameters

The project has removed Ollama (per prior refactor), so this code is dead — it always falls back to template generation, but carries unnecessary complexity and subprocess overhead.

## Goal

Remove all Ollama code from `ABCaptionGenerator`, making it template-only. No performance gain expected (template path was already the final fallback), but:
- Cleaner code (no dead code)
- No subprocess in this file
- Consistent with `CaptionGenerator` refactor

## Changes

### `modules/content/ab_caption_generator.py`

Remove:
- `import subprocess` (line 21)
- `_check_ollama()` method (lines 102-111)
- `_call_llm()` method (lines 138-177)
- `ollama_host`, `model`, `use_llm` from `__init__` parameters
- `self.use_llm` attribute
- `if self.use_llm:` branch in `generate_caption_variant_A/B` — always use template fallback
- Docstring references to "ollama" (line 8)

Simplify `__init__` to:
```python
def __init__(self):
    pass  # No external dependencies
```

Simplify variant methods to always use template path:
```python
def generate_caption_variant_A(self, script: str, platform: str = "tiktok") -> GeneratedCaption:
    topic = self._extract_topic(script)
    category = self._detect_category(script)
    return self._build_caption(None, "a", topic, category, platform)
```

Same for `generate_caption_variant_B`.

### `tests/test_caption_generator.py`

Update test names/docstrings to reflect they cover both `CaptionGenerator` and `ABCaptionGenerator`. Add explicit check for `ABCaptionGenerator` file content in `test_caption_generator_no_ollama_code()`.

### Verification

```bash
# Should return no results
grep -ri "ollama" modules/content/ab_caption_generator.py
grep -ri "subprocess" modules/content/ab_caption_generator.py
grep -ri "curl" modules/content/ab_caption_generator.py
grep -ri "curl" tests/test_caption_generator.py

# Should pass
pytest tests/test_caption_generator.py -v
```

## Scope

- Only `ab_caption_generator.py` and its test file
- No changes to `CaptionGenerator` (already clean)
- No changes to other files with subprocess (FFmpeg, Whisper CLI, git — all necessary external binaries)

## File list

- `modules/content/ab_caption_generator.py` — remove Ollama code
- `tests/test_caption_generator.py` — update test to cover ABCaptionGenerator
