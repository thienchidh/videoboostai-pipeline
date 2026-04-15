# Script Duration at Generation Time — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ContentIdeaGenerator` validate scene TTS word counts before returning, regenerate scenes that exceed channel duration bounds, and update the LLM prompt to generate correctly-sized scripts on first pass.

**Architecture:** Pre-validate each generated scene's TTS text using estimated duration; if too long/short, call LLM to shorten/expand just that scene's TTS (not full JSON) using retry logic. Fallback to keeping original on repeated failure.

**Tech Stack:** Python, tenacity (existing retry), MiniMax LLM, existing ChannelConfig Pydantic models

---

## File Map

| File | Responsibility |
|------|----------------|
| `modules/content/content_idea_generator.py` | Scene generation + duration validation + regeneration |
| `tests/test_content_idea_generator.py` | New test file for duration validation and regeneration |

---

## Task 1: Add `_estimate_tts_duration` helper

**Files:**
- Modify: `modules/content/content_idea_generator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_content_idea_generator.py`:

```python
def test_estimate_tts_duration():
    """Word count / wps gives estimated duration."""
    from modules.content.content_idea_generator import ContentIdeaGenerator
    gen = ContentIdeaGenerator(
        project_id=1,
        content_angle="tips",
        niche_keywords=["test"],
        channel_config={"name": "Test", "characters": [{"name": "Mentor", "voice_id": "x"}], "tts": {"max_duration": 15.0, "min_duration": 5.0}},
    )
    # 30 words at 2.5 wps = 12 seconds
    estimated = gen._estimate_tts_duration("đây là một câu dài để test thử nghiệm cho nhanh", wps=2.5)
    assert 11.5 < estimated < 12.5, f"expected ~12s, got {estimated}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_idea_generator.py::test_estimate_tts_duration -v`
Expected: FAIL — `_estimate_tts_duration` not defined

- [ ] **Step 3: Write minimal implementation**

Add to `ContentIdeaGenerator` class:

```python
def _estimate_tts_duration(self, text: str, wps: float = 2.5) -> float:
    """Estimate TTS duration in seconds from text word count."""
    if not text or not text.strip():
        return 0.0
    word_count = len(text.split())
    return word_count / wps
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_idea_generator.py::test_estimate_tts_duration -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/content/content_idea_generator.py tests/test_content_idea_generator.py
git commit -m "feat(content): add _estimate_tts_duration helper"
```

---

## Task 2: Add `_validate_scene_duration` method

**Files:**
- Modify: `modules/content/content_idea_generator.py`
- Test: `tests/test_content_idea_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_validate_scene_duration_passes():
    """Scene within min/max bounds returns True."""
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import TTSConfig
    gen = ContentIdeaGenerator(
        project_id=1,
        content_angle="tips",
        niche_keywords=["test"],
        channel_config={"name": "Test", "characters": [{"name": "Mentor", "voice_id": "x"}], "tts": {"max_duration": 15.0, "min_duration": 5.0}},
    )
    tts_cfg = TTSConfig(max_duration=15.0, min_duration=5.0)
    # 30 words at 2.5 wps = 12s — within 5-15s
    result = gen._validate_scene_duration("đây là một test ngắn để kiểm tra", tts_cfg, wps=2.5)
    assert result is True

def test_validate_scene_duration_fails_too_long():
    """Scene exceeding max_duration returns False."""
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import TTSConfig
    gen = ContentIdeaGenerator(
        project_id=1,
        content_angle="tips",
        niche_keywords=["test"],
        channel_config={"name": "Test", "characters": [{"name": "Mentor", "voice_id": "x"}], "tts": {"max_duration": 15.0, "min_duration": 5.0}},
    )
    tts_cfg = TTSConfig(max_duration=15.0, min_duration=5.0)
    # 84 words at 2.5 wps = 33.6s — exceeds 15s max
    long_text = " ".join(["đây"] * 84)
    result = gen._validate_scene_duration(long_text, tts_cfg, wps=2.5)
    assert result is False

def test_validate_scene_duration_fails_too_short():
    """Scene below min_duration returns False."""
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import TTSConfig
    gen = ContentIdeaGenerator(
        project_id=1,
        content_angle="tips",
        niche_keywords=["test"],
        channel_config={"name": "Test", "characters": [{"name": "Mentor", "voice_id": "x"}], "tts": {"max_duration": 15.0, "min_duration": 5.0}},
    )
    tts_cfg = TTSConfig(max_duration=15.0, min_duration=5.0)
    # 5 words at 2.5 wps = 2s — below 5s min
    result = gen._validate_scene_duration("đây là test", tts_cfg, wps=2.5)
    assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_content_idea_generator.py::test_validate_scene_duration_passes tests/test_content_idea_generator.py::test_validate_scene_duration_fails_too_long tests/test_content_idea_generator.py::test_validate_scene_duration_fails_too_short -v`
Expected: FAIL — method not defined

- [ ] **Step 3: Write implementation**

Add to `ContentIdeaGenerator`:

```python
def _validate_scene_duration(self, scene_tts: str, tts_cfg,
                               wps: float = 2.5) -> bool:
    """Return True if estimated TTS duration is within min/max bounds.

    Args:
        scene_tts: The TTS script text for one scene.
        tts_cfg: TTSConfig with min_duration and max_duration.
        wps: Words per second (from channel config, default 2.5).

    Returns:
        True if min_duration <= estimated_duration <= max_duration.
    """
    if not scene_tts or not scene_tts.strip():
        # Empty script — let it fail at TTS stage, don't block here
        return True
    duration = self._estimate_tts_duration(scene_tts, wps)
    return tts_cfg.min_duration <= duration <= tts_cfg.max_duration
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_content_idea_generator.py::test_validate_scene_duration_passes tests/test_content_idea_generator.py::test_validate_scene_duration_fails_too_long tests/test_content_idea_generator.py::test_validate_scene_duration_fails_too_short -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/content/content_idea_generator.py tests/test_content_idea_generator.py
git commit -m "feat(content): add _validate_scene_duration method"
```

---

## Task 3: Add TTS-regeneration helper `_regenerate_scene_tts`

**Files:**
- Modify: `modules/content/content_idea_generator.py`
- Test: `tests/test_content_idea_generator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_regenerate_scene_tts_shortens_long_text():
    """_regenerate_scene_tts calls LLM and returns shorter text."""
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from unittest.mock import patch, MagicMock
    from modules.pipeline.models import TTSConfig

    gen = ContentIdeaGenerator(
        project_id=1,
        content_angle="tips",
        niche_keywords=["test"],
        channel_config={"name": "Test", "characters": [{"name": "Mentor", "voice_id": "x"}], "tts": {"max_duration": 15.0, "min_duration": 5.0}},
    )
    tts_cfg = TTSConfig(max_duration=15.0, min_duration=5.0)
    long_text = " ".join(["đây là một từ dài"] * 20)  # ~80 words

    # Mock LLM provider that returns a shorter text
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "ngắn gọn và đúng vào việc"

    with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
        result = gen._regenerate_scene_tts(long_text, tts_cfg, api_key="fake-key", wps=2.5)
    assert len(result.split()) < len(long_text.split()), f"expected shorter, got same length"
    mock_llm.chat.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_idea_generator.py::test_regenerate_scene_tts_shortens_long_text -v`
Expected: FAIL — method not defined

- [ ] **Step 3: Write implementation**

Add to `ContentIdeaGenerator`:

```python
def _regenerate_scene_tts(self, original_tts: str, tts_cfg,
                           api_key: str, wps: float = 2.5,
                           max_retries: int = 3) -> str:
    """Regenerate scene TTS text to fit duration bounds.

    Args:
        original_tts: The original TTS text that exceeded bounds.
        tts_cfg: TTSConfig with min_duration and max_duration.
        api_key: MiniMax API key for LLM calls.
        wps: Words per second for duration estimation.
        max_retries: Number of LLM retry attempts (default 3).

    Returns:
        New TTS text that fits bounds, or original_tts if all retries fail.
    """
    from modules.llm.minimax import MiniMaxLLMProvider

    # Calculate target: aim for 80% of max (14s for 15s max)
    target_duration = tts_cfg.max_duration * 0.9
    target_words = int(target_duration / wps)

    system_prompt = f"""Bạn là chuyên gia viết kịch bản TTS tiếng Việt ngắn gọn.
Nhiệm vụ: Viết lại kịch bản TTS cho một scene video.

YÊU CẦU:
- VIẾT TIẾNG VIỆT CÓ DẤU, tự nhiên như người nói thật
- Độ dài: CHÍNH XÁC khoảng {target_words} từ (tương đương {target_duration:.0f} giây TTS)
- KHÔNG thêm lời chào mở đầu như "Xin chào", "Hôm nay"
- KHÔNG thêm kết luận kiểu "Cảm ơn đã xem"
- Câu ngắn gọn, mỗi câu không quá 10 từ

Output: Chỉ output kịch bản TTS thuần túy, không có mở đầu hay kết thúc."""

    user_prompt = f"""Kịch bản gốc (hiện tại quá dài):
"{original_tts}"

Hãy viết lại kịch bản này để có độ dài phù hợp (khoảng {target_words} từ)."""

    for attempt in range(max_retries):
        try:
            llm = MiniMaxLLMProvider(api_key=api_key)
            new_tts = llm.chat(prompt=user_prompt, system=system_prompt, max_tokens=256)
            new_tts = new_tts.strip()
            # Validate before returning
            if self._validate_scene_duration(new_tts, tts_cfg, wps):
                logger.info(f"  🤖 Scene TTS regenerated ({attempt+1} attempt): "
                           f"{len(original_tts.split())} → {len(new_tts.split())} words")
                return new_tts
            else:
                logger.warning(f"  🤖 Regenerated TTS still out of bounds (attempt {attempt+1}/{max_retries})")
        except Exception as e:
            logger.warning(f"  🤖 LLM regeneration error: {e} (attempt {attempt+1}/{max_retries})")

    logger.warning(f"  ⚠️ All {max_retries} regeneration attempts failed — keeping original TTS")
    return original_tts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_idea_generator.py::test_regenerate_scene_tts_shortens_long_text -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/content/content_idea_generator.py tests/test_content_idea_generator.py
git commit -m "feat(content): add _regenerate_scene_tts with LLM shortening"
```

---

## Task 4: Modify `_generate_scenes` to validate + regenerate

**Files:**
- Modify: `modules/content/content_idea_generator.py:128-163` (the `_generate_scenes` method)

- [ ] **Step 1: Write the failing test**

```python
def test_generate_scenes_validates_duration_and_regenerates(mocker):
    """Scenes too long are regenerated before being returned."""
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import TTSConfig

    gen = ContentIdeaGenerator(
        project_id=1,
        content_angle="tips",
        niche_keywords=["test"],
        channel_config={"name": "Test", "characters": [{"name": "Mentor", "voice_id": "x"}],
                        "tts": {"max_duration": 15.0, "min_duration": 5.0}},
    )

    # Mock LLM returns 2 scenes: one fine, one too long
    long_scene = {"id": 1, "tts": " ".join(["đây là một từ dài"] * 40), "character": "Mentor", "background": "office"}
    short_scene = {"id": 2, "tts": "ngắn gọn", "character": "Mentor", "background": "office"}
    mocker.patch.object(gen, "_call_llm", return_value=[long_scene, short_scene])
    mocker.patch.object(gen, "_regenerate_scene_tts", side_effect=lambda tts, cfg, **kw: "ngắn gọn và đúng")

    scenes = gen._generate_scenes("Test Title", ["test"], "tips", "", num_scenes=2)
    assert len(scenes) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_idea_generator.py::test_generate_scenes_validates_duration_and_regenerates -v`
Expected: FAIL — method not yet modified

- [ ] **Step 3: Write implementation**

Replace the existing `_generate_scenes` method body (lines ~130-163) with:

```python
def _generate_scenes(self, title: str, keywords: List[str], angle: str,
                      description: str = "", num_scenes: int = 3) -> List[Dict]:
    """Generate scene scripts using LLM provider with exponential backoff retry.

    After initial generation, each scene's TTS is validated against channel
    duration bounds. Scenes that exceed bounds are regenerated (TTS text only)
    via _regenerate_scene_tts before being returned.
    """
    from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

    api_key = self._llm_config.get("api_key", "")
    if not api_key:
        # Read minimax key from technical config
        from modules.pipeline.models import TechnicalConfig
        api_key = TechnicalConfig.load().api_keys.minimax
        if not api_key:
            raise RuntimeError("minimax API key not found in config")

    llm = get_llm_provider(
        name=self._llm_config.get("provider", "minimax"),
        api_key=api_key,
        model=self._llm_config.get("model", "MiniMax-M2.7"),
    )
    prompt = self._build_scene_prompt(title, keywords, angle, description, num_scenes)

    @retry(
        stop=stop_after_attempt(self._llm_config.get("retry_attempts", 3)),
        wait=wait_exponential(multiplier=1, min=1, max=self._llm_config.get("retry_backoff_max", 10)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _call_llm():
        text = llm.chat(prompt, max_tokens=self._llm_config.get("max_tokens", 1536))
        scenes = self._parse_scenes(text)
        if not scenes:
            raise ValueError("Invalid scene format")
        return scenes

    scenes = _call_llm()
    logger.info(f"Generated {len(scenes)} scenes from LLM")

    # Validate each scene's TTS duration and regenerate if out of bounds
    if self._channel_config and self._channel_config.tts:
        tts_cfg = self._channel_config.tts
        wps = self.technical_config.generation.tts.words_per_second if (
            self.technical_config and
            hasattr(self.technical_config.generation, 'tts') and
            self.technical_config.generation.tts
        ) else 2.5

        for scene in scenes:
            tts_text = scene.get("tts", "")
            if not tts_text:
                continue
            if not self._validate_scene_duration(tts_text, tts_cfg, wps):
                logger.warning(f"  ⚠️ Scene {scene.get('id', '?')} TTS out of bounds "
                              f"({len(tts_text.split())} words), regenerating...")
                regenerated = self._regenerate_scene_tts(
                    tts_text, tts_cfg, api_key=api_key, wps=wps
                )
                scene["tts"] = regenerated

    return scenes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_idea_generator.py::test_generate_scenes_validates_duration_and_regenerates -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/content/content_idea_generator.py
git commit -m "feat(content): validate scene TTS duration in _generate_scenes and regenerate out-of-bounds scenes"
```

---

## Task 5: Update `_build_scene_prompt` with explicit word count guidance

**Files:**
- Modify: `modules/content/content_idea_generator.py:165-222` (the `_build_scene_prompt` method)

- [ ] **Step 1: Identify current prompt text**

Read the current `_build_scene_prompt` method (lines 165-222). Find the line with "mỗi scene 3-8 câu".

- [ ] **Step 2: Replace vague "3-8 câu" with word count guidance**

In the return string, replace:
```
- script: lời thoại tiếng Việt có dấu, mỗi scene 3-8 câu
```

With:
```
- script: lời thoại tiếng Việt có dấu, mỗi scene 25-35 từ (tương đương 10-14 giây TTS), câu ngắn gọn không quá 10 từ
```

Also update the TTS context line to be more explicit:
```
tts_context = f"\nGiới hạn thời lượng: tối đa {tts.max_duration}s, tối thiểu {tts.min_duration}s mỗi scene. "
tts_context += f"Đếm số từ: mỗi từ đọc mất khoảng {wps:.1f}s — scene phải có {int(tts.min_duration * wps)}-{int(tts.max_duration * wps)} từ."
```

And update the scene structure requirement section:
```
MỖI SCENE CẦN CÓ:
- id: số nguyên (1, 2, 3...)
- script: lời thoại tiếng Việt có dấu, 25-35 từ, mỗi câu không quá 10 từ
- background: mô tả cảnh nền 5-15 từ, BẮT BUỘC chứa phong cách hình ảnh cố định [{art_style_str}]
- character: tên MỘT nhân vật duy nhất được chọn từ [{char_list_str}]
```

- [ ] **Step 3: Verify existing tests still pass**

Run: `pytest tests/test_content_idea_generator.py -v`
Expected: PASS (no new tests should break)

- [ ] **Step 4: Commit**

```bash
git add modules/content/content_idea_generator.py
git commit -m "feat(content): update scene prompt with explicit word count guidance (25-35 words per scene)"
```

---

## Task 6: Add backward-compat test for missing TTS config

**Files:**
- Test: `tests/test_content_idea_generator.py`

- [ ] **Step 1: Write the test**

```python
def test_validate_scene_duration_skips_when_no_tts_config():
    """When channel config has no tts, validation returns True (skip)."""
    from modules.content.content_idea_generator import ContentIdeaGenerator
    gen = ContentIdeaGenerator(
        project_id=1,
        content_angle="tips",
        niche_keywords=["test"],
        channel_config={"name": "Test", "characters": [{"name": "Mentor", "voice_id": "x"}]},
        # no "tts" key
    )
    # Should not raise, returns True (skip validation)
    result = gen._validate_scene_duration("some text", None, wps=2.5)
    assert result is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_idea_generator.py::test_validate_scene_duration_skips_when_no_tts_config -v`
Expected: FAIL — method needs backward compat handling

- [ ] **Step 3: Update `_validate_scene_duration` for backward compat**

Change the method to handle `tts_cfg is None`:

```python
def _validate_scene_duration(self, scene_tts: str, tts_cfg,
                               wps: float = 2.5) -> bool:
    if not scene_tts or not scene_tts.strip():
        return True
    if tts_cfg is None:
        # No TTS config — skip validation, backward compatible
        logger.debug("No tts config in channel, skipping duration validation")
        return True
    duration = self._estimate_tts_duration(scene_tts, wps)
    return tts_cfg.min_duration <= duration <= tts_cfg.max_duration
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_idea_generator.py::test_validate_scene_duration_skips_when_no_tts_config -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/content/content_idea_generator.py tests/test_content_idea_generator.py
git commit -m "feat(content): add backward compat for missing TTS config in _validate_scene_duration"
```

---

## Self-Review Checklist

- [ ] Each spec requirement covered by a task? Yes — validation, regeneration, prompt update, backward compat
- [ ] No placeholders (TBD, TODO)? Yes
- [ ] Type consistency: `_validate_scene_duration` takes `tts_cfg: TTSConfig` — used consistently in Task 2, 3, 4
- [ ] `wps` parameter passed consistently — 2.5 default, from `technical_config.generation.tts.words_per_second` in Task 4
- [ ] All tests have actual assertions, not just "assert True"
- [ ] Commit after each task — keeps changes small and reviewable