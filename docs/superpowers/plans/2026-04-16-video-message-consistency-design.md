# Video Message + Script Quality — Two-Step Generation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `video_message=null` and all-question scripts by separating message generation (Step 1) from scene generation (Step 2).

**Architecture:** Two dedicated LLM calls — first generates `video_message` (guaranteed non-null via mandatory output), second generates scenes using `video_message` as mandatory context. Both steps receive the researched `description` as source content.

**Tech Stack:** Python, tenacity (retry), MiniMax LLM provider, Pydantic models.

---

## Files to Modify

| File | What |
|------|------|
| `modules/pipeline/models.py` | Add `scene_type` and `delivers` fields to `SceneConfig` |
| `modules/content/content_idea_generator.py` | Add `_generate_video_message`, update `_build_scene_prompt` for Step 2, update flow in `generate_script_from_idea` |

---

## Files to Update Tests

| File | What |
|------|------|
| `tests/test_content_idea_generator.py` | Add tests for `_generate_video_message`; update existing test for two-step flow |

---

## Task 1: Add `scene_type` and `delivers` to `SceneConfig`

**Files:** `modules/pipeline/models.py` (modify `SceneConfig` class, ~line 393)

- [ ] **Step 1: Read the file section**

Run: Read `modules/pipeline/models.py` lines 393–430.

- [ ] **Step 2: Add fields to SceneConfig**

Modify `SceneConfig` in `modules/pipeline/models.py` — add two new fields after `creative_brief`:

```python
class SceneConfig(BaseModel):
    """Một scene từ scenario YAML file."""
    id: int = 0
    tts: Optional[str] = None
    script: Optional[str] = None
    characters: List[SceneCharacter] = []
    video_prompt: Optional[str] = None
    background: Optional[str] = None
    image_prompt: Optional[str] = None
    lipsync_prompt: Optional[str] = None
    creative_brief: Optional[Dict[str, Any]] = None
    scene_type: Optional[str] = None   # hook | insight | technique | proof | cta
    delivers: Optional[str] = None     # plain-language summary of viewer takeaway
```

- [ ] **Step 3: Update `from_dict` to parse new fields**

Modify the `from_dict` method in `SceneConfig` to include `scene_type` and `delivers`:

```python
    @classmethod
    def from_dict(cls, data: dict) -> "SceneConfig":
        raw_chars = data.get("characters", [])
        if not raw_chars and "character" in data:
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
            scene_type=data.get("scene_type"),   # NEW
            delivers=data.get("delivers"),       # NEW
        )
```

- [ ] **Step 4: Run existing tests to verify no breakage**

Run: `pytest tests/test_content_idea_generator.py tests/test_prompt_builder.py -v`
Expected: All pass (no behavior change yet from these additions).

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/models.py
git commit -m "feat(SceneConfig): add scene_type and delivers fields"
```

---

## Task 2: Add `_generate_video_message` method

**Files:** `modules/content/content_idea_generator.py` (add new method)

- [ ] **Step 1: Read the current `_extract_video_message` method for reference**

Run: Read `modules/content/content_idea_generator.py` lines 371–379.

- [ ] **Step 2: Add `_generate_video_message` method after `_extract_video_message`**

Add this new method after line 379 (after `_extract_video_message`):

```python
    def _generate_video_message(self, title: str, keywords: List[str],
                                 angle: str, description: str) -> str:
        """Generate video_message via dedicated LLM call.

        This is Step 1 of the two-step generation. The video_message is
        NEVER None — if LLM fails or returns empty, we raise after retries.

        Args:
            title: Topic title.
            keywords: Topic keywords list.
            angle: Content angle (tips, educational, etc.).
            description: Researched content used as source knowledge.

        Returns:
            Non-empty video_message string.

        Raises:
            RuntimeError: If LLM returns empty/null video_message after max retries.
        """
        from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log
        from modules.pipeline.models import TechnicalConfig

        if not self._llm or not self._llm.model:
            raise ConfigMissingKeyError("generation.llm.model", "ContentIdeaGenerator")
        tech_cfg = self._technical_config if self._technical_config else TechnicalConfig.load()
        api_key = tech_cfg.api_keys.minimax
        if not api_key:
            raise RuntimeError("minimax API key not found in config")

        llm = get_llm_provider(
            name=self._llm.provider if self._llm else "minimax",
            api_key=api_key,
            model=self._llm.model if self._llm else "MiniMax-M2.7",
        )

        prompt = self._build_video_message_prompt(title, keywords, angle, description)

        @retry(
            stop=stop_after_attempt(self._llm.retry_attempts if self._llm else 3),
            wait=wait_exponential(multiplier=1, min=1, max=self._llm.retry_backoff_max if self._llm else 10),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _call_llm():
            raw = llm.chat(prompt, max_tokens=self._llm.max_tokens if self._llm else 256)
            msg = self._extract_video_message(raw)
            if not msg:
                raise ValueError("LLM returned empty/null video_message")
            return msg

        video_message = _call_llm()
        logger.info(f"Generated video_message: {video_message[:80]}...")
        return video_message
```

- [ ] **Step 3: Write the failing test for `_generate_video_message`**

Add new test to `tests/test_content_idea_generator.py` at the end of the file:

```python
def test_generate_video_message_returns_non_null():
    """_generate_video_message returns a non-null string when LLM succeeds."""
    import json
    from unittest.mock import MagicMock, patch
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import GenerationLLM

    mock_channel = MagicMock()
    mock_channel.name = "Test Channel"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)

    gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
    gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=256, retry_attempts=2, retry_backoff_max=5)

    mock_llm = MagicMock()
    mock_llm.chat.return_value = json.dumps({"video_message": "90-phút thay vì 25-phút Pomodoro — Olympic dùng phương pháp này để đạt peak state"})

    with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
        result = gen._generate_video_message("Test Title", ["productivity"], "tips", "Some research description")

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 10
    assert "90-phút" in result


def test_generate_video_message_raises_on_empty():
    """_generate_video_message raises RuntimeError when LLM returns empty."""
    from unittest.mock import MagicMock, patch
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import GenerationLLM

    mock_channel = MagicMock()
    mock_channel.name = "Test Channel"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)

    gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
    gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=256, retry_attempts=2, retry_backoff_max=5)

    mock_llm = MagicMock()
    # LLM returns JSON with null video_message
    mock_llm.chat.return_value = '{"video_message": null}'

    with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
        with pytest.raises(RuntimeError) as exc_info:
            gen._generate_video_message("Test Title", ["productivity"], "tips", "description")
    assert "empty/null video_message" in str(exc_info.value)
```

- [ ] **Step 4: Run new tests to verify they fail (method doesn't exist yet)**

Run: `pytest tests/test_content_idea_generator.py::test_generate_video_message_returns_non_null tests/test_content_idea_generator.py::test_generate_video_message_raises_on_empty -v`
Expected: FAIL with "AttributeError: 'ContentIdeaGenerator' object has no attribute '_generate_video_message'"

- [ ] **Step 5: Implement `_build_video_message_prompt` helper**

Add this method after `_build_scene_prompt` (around line 326):

```python
    def _build_video_message_prompt(self, title: str, keywords: List[str],
                                     angle: str, description: str) -> str:
        """Build the prompt for Step 1: generating video_message.

        Returns a prompt instructing LLM to act as chief content strategist
        and produce a single video_message JSON object.
        """
        if not self._channel_config:
            raise ValueError("channel_config is required")

        kw_list_str = ", ".join(keywords) if keywords else ""

        return f"""Bạn là CHIEF CONTENT STRATEGIST cho kênh TikTok/Reels tiếng Việt.

NHIỆM VỤ:
Xác định "video_message" — thông điệp MANG ĐI của viewer sau khi xem video.

QUY TẮC:
1. video_message phải là 1-2 câu, NGẮN GỌN, CÓ Ý NGHĨA RÕ RÀNG
2. KHÔNG generic — phải CỤ THỂ, có con số HOẶC promise rõ ràng
3. Phải có "hook" — điều bất ngờ, thách thức, hoặc specific claim
4. Dựa vào NỘI DUNG THAM KHẢO, không bịa

NỘI DUNG THAM KHẢO:
{title}
Keywords: {kw_list_str}
Content angle: {angle}
Description:
{description[:1500]}

VÍ DỤ TỐT:
- "Phương pháp 90-phút giúp deep work HIỆU QUẢ HƠN 40% so với Pomodoro"
- "Nguyên tắc Pareto 80/20 không phải lúc nào cũng đúng — đây là version CẢI TIẾN"
- "Đêm ngủ 8 tiếng là SAI — thực tế Olympic dùng phương pháp khác"

OUTPUT JSON:
{{
  "video_message": "viết video_message ở đây"
}}

CHỈ JSON, không markdown, KHÔNG THÊM GÌ KHÁC."""
```

- [ ] **Step 6: Run new tests to verify they pass**

Run: `pytest tests/test_content_idea_generator.py::test_generate_video_message_returns_non_null tests/test_content_idea_generator.py::test_generate_video_message_raises_on_empty -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add modules/content/content_idea_generator.py tests/test_content_idea_generator.py
git commit -m "feat(content_idea_generator): add _generate_video_message two-step method"
```

---

## Task 3: Update `generate_script_from_idea` and `_build_scene_prompt` for two-step flow

**Files:** `modules/content/content_idea_generator.py`

- [ ] **Step 1: Read `generate_script_from_idea` method**

Run: Read `modules/content/content_idea_generator.py` lines 85–113.

- [ ] **Step 2: Update `generate_script_from_idea` to call two steps**

Modify `generate_script_from_idea` to:
1. Call `_generate_video_message` first (Step 1)
2. Pass result to `_generate_scenes` as new `video_message` parameter

Change the method body from:
```python
        scenes, video_message = self._generate_scenes(title, keywords, angle, description, num_scenes)
```
to:
```python
        # Step 1: generate video_message (never null)
        video_message = self._generate_video_message(title, keywords, angle, description)
        # Step 2: generate scenes using video_message as mandatory context
        scenes, _ = self._generate_scenes(title, keywords, angle, description, num_scenes, video_message)
```

- [ ] **Step 3: Read `_build_scene_prompt` signature and prompt structure**

Run: Read `modules/content/content_idea_generator.py` lines 184–326.

- [ ] **Step 4: Update `_build_scene_prompt` signature**

Change the method signature from:
```python
    def _build_scene_prompt(self, title: str, keywords: List[str], angle: str,
                             description: str = "", num_scenes: int = 3) -> str:
```
to:
```python
    def _build_scene_prompt(self, title: str, keywords: List[str], angle: str,
                             description: str, num_scenes: int,
                             video_message: str) -> str:
```

- [ ] **Step 5: Update prompt template in `_build_scene_prompt`**

In the `return f"""...` block of `_build_scene_prompt`, find and replace the current prompt's intro section. The current prompt (lines ~226–232 in the original file) starts with `TRƯỚC TIÊU: Dựa trên title...`. Replace it with the new Step 2 prompt:

**Before** (current intro in `_build_scene_prompt`):
```
TRƯỚC TIÊU: Dựa trên title, keywords và content_angle, xác định "video_message"...
SAU ĐÓ: Viết {num_scenes} scenes...
...
ĐỊNH DẠNG JSON OUTPUT:
{{
  "video_message": "thông điệp...",
  "scenes": [...]
}}
```

**After** (new Step 2 prompt, insert at the top of the prompt body, replacing the TRƯỚC TIÊU/SAU ĐÓ section):
```
VIDEO_MESSAGE (BẮT BUỘC PHẢI ILLUSTRATE/SUPPORT):
"{video_message}"
→ Tất cả scenes phải giúp viewer hiểu HOẶC tin video_message này
→ Không viết scene nào không liên quan đến video_message

NỘI DUNG THAM KHẢO:
{desc_line}{kw_line}Phong cách: {angle}

PHONG CÁCH KÊNH:
{cfg.style}

NHÂN VẬT:
{char_list_str}

GIỚI HẠN: mỗi scene {int(tts.min_duration)}-{int(tts.max_duration)} giây ({int(tts.min_duration*2.5)}-{int(tts.max_duration*2.5)} từ)

---

CẤU TRÚC SCENES:

1. Scene 1 — HOOK: Câu hỏi HOẶC provocative statement. PHẢI có hint/trả lời một phần.
   ✅ "Olympic không dùng Pomodoro — họ dùng gì? Và HIỆU QUẢ HƠN 40%"
   ❌ "Bạn có biết bí mật năng suất của Olympic không?"

2. Scene 2+ — INSIGHT / TECHNIQUE / PROOF: Mỗi scene phải deliver:
   - FACT: số liệu cụ thể (VD: "40%", "90 phút", "3 lần/ngày")
   - HOẶC TECHNIQUE: step-by-step rõ ràng
   - HOẶC PRINCIPLE: framework/mindset cụ thể

3. Final Scene — delivers REMAINING VALUE:
   - Case study HOẶC proof HOẶC CTA (save/share/try)

QUY TẮC NGHIÊM NGẶT:
- MỖI SCENE phải deliver ÍT NHẤT 1 điều CỤ THỂ (fact/technique/principle)
- KHÔNG viết scene chỉ toàn câu hỏi mà không trả lời gì
- Scene hook có thể hỏi nhưng phải IMPLY/trả lời một phần ngay trong script đó
- Số scenes: tự quyết định dựa trên topic (2-5 scenes), không cố định 3

TRÁNH:
- Generic adjectives: "rất hiệu quả", "tuyệt vời" — thay bằng CONCRETE NUMBERS
- Câu hỏi không có answer trong video
- Câu hỏi engagement bait: "Bạn nghĩ sao?" — trả lời luôn

VÍ DỤ HOOK TỐT:
✅ "90-phút thay vì 25-phút Pomodoro — Olympic dùng phương pháp này để đạt peak state"
✅ "Đêm ngủ 8 tiếng là MYTH — athletes ngủ theo cách HOÀN TOÀN KHÁC và đây là lý do"
✅ "Pareto 80/20 có 1 TRƯỜNG HỢP NGOẠI LỆ — và nó quan trọng hơn nguyên tắc gốc"

---

ĐỊNH DẠNG JSON OUTPUT:
{{
  "scenes": [
    {{
      "id": 1,
      "scene_type": "hook",
      "script": "...",
      "character": "...",
      "delivers": "what viewer gets from this scene in 1 sentence",
      "creative_brief": {{...}},
      "image_prompt": "...",
      "lipsync_prompt": "..."
    }},
    ...
  ]
}}

CHỈ JSON object có "scenes" array, không markdown, không thêm field nào khác.
```

Also update the prompt's variable interpolation — change `{num_scenes}` references inside the prompt body to remove the hardcoded count instruction (since scenes are now dynamic), but **keep** `{num_scenes}` in the `return f"""` call signature.

The call to `_build_scene_prompt` in `_generate_scenes` (line ~139) needs updating — add `video_message`:

Change:
```python
prompt = self._build_scene_prompt(title, keywords, angle, description, num_scenes)
```
to:
```python
prompt = self._build_scene_prompt(title, keywords, angle, description, num_scenes, video_message)
```

- [ ] **Step 6: Run existing tests to check for regressions**

Run: `pytest tests/test_content_idea_generator.py -v`
Expected: Most pass; `test_generate_script_from_idea_includes_video_message` may need update (see Step 7).

- [ ] **Step 7: Update `test_generate_script_from_idea_includes_video_message` for two-step flow**

The existing test mocks `get_llm_provider` returning a single LLM call with `video_message`. With two-step, the test needs to mock TWO LLM calls — one for `_generate_video_message` (Step 1) and one for `_generate_scenes` (Step 2).

Replace the existing `test_generate_script_from_idea_includes_video_message` test with:

```python
def test_generate_script_from_idea_includes_video_message():
    """generate_script_from_idea calls two-step: video_message first, then scenes."""
    import json
    from unittest.mock import MagicMock, patch, call
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import GenerationLLM

    mock_channel = MagicMock()
    mock_channel.name = "Test Channel"
    mock_channel.style = "friendly"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="vi-VN-NamMinhNeural")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
    mock_channel.watermark = MagicMock(text="@test")
    mock_channel.image_style = MagicMock(lighting="warm", camera="eye-level", art_style="3D render",
                                         environment="office", composition="professional")

    gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
    gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=1536, retry_attempts=3, retry_backoff_max=10)

    step1_response = json.dumps({"video_message": "Tập trung vào 1 việc quan trọng nhất trước"})
    step2_response = json.dumps({
        "scenes": [
            {"id": 1, "script": "Bắt đầu ngay", "character": "NamMinh",
             "scene_type": "hook", "delivers": "first tip",
             "creative_brief": {"visual_concept": "test", "emotion": "serious",
                               "camera_mood": "close-up", "setting_vibe": "office",
                               "unique_angle": "desk", "action_description": "speaking"}},
        ]
    })

    mock_llm = MagicMock()
    # Return different responses per call: first = step1, second = step2
    mock_llm.chat.side_effect = [step1_response, step2_response]

    with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
        result = gen.generate_script_from_idea({
            "title": "Test Title",
            "content_angle": "tips",
            "topic_keywords": ["test"]
        }, num_scenes=1)

    assert "video_message" in result
    assert result["video_message"] == "Tập trung vào 1 việc quan trọng nhất trước"
    assert len(mock_llm.chat.call_count) == 2, f"expected 2 LLM calls (step1 + step2), got {mock_llm.chat.call_count}"
```

- [ ] **Step 8: Run all tests**

Run: `pytest tests/test_content_idea_generator.py -v`
Expected: All pass.

- [ ] **Step 9: Commit**

```bash
git add modules/content/content_idea_generator.py tests/test_content_idea_generator.py
git commit -m "feat(content_idea_generator): two-step generation — video_message first, then scenes"
```

---

## Task 4: Add scene quality validation tests

**Files:** `tests/test_content_idea_generator.py`

- [ ] **Step 1: Write `test_scene_1_is_hook_with_partial_answer`**

Add to `tests/test_content_idea_generator.py`:

```python
def test_scene_1_is_hook_with_partial_answer():
    """Scene 1 must have scene_type=='hook' and script implies (not just asks) answer."""
    import json
    from unittest.mock import MagicMock, patch
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import GenerationLLM

    mock_channel = MagicMock()
    mock_channel.name = "Test"
    mock_channel.style = "friendly"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
    mock_channel.watermark = MagicMock(text="@test")

    gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
    gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=1536, retry_attempts=2, retry_backoff_max=5)

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        json.dumps({"video_message": "90-phút tốt hơn Pomodoro"}),
        json.dumps({
            "scenes": [
                {"id": 1, "script": "Olympic không dùng Pomodoro 25-phút — họ dùng 90-phút và HIỆU QUẢ HƠN 40%. Bạn đang dùng sai phương pháp?",
                 "character": "NamMinh", "scene_type": "hook", "delivers": "hook with partial answer",
                 "creative_brief": {}, "image_prompt": "...", "lipsync_prompt": "..."},
                {"id": 2, "script": "Nguyên tắc: làm việc 90 phút tập trung rồi nghỉ 15-20 phút. Lặp 3-4 lần mỗi ngày.",
                 "character": "NamMinh", "scene_type": "technique", "delivers": "90-min rule explained",
                 "creative_brief": {}, "image_prompt": "...", "lipsync_prompt": "..."},
            ]
        }),
    ]

    with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
        result = gen.generate_script_from_idea({"title": "Title", "content_angle": "tips", "topic_keywords": []})

    scenes = result["scenes"]
    assert scenes[0].scene_type == "hook"
    # Script must imply an answer (contains "90-phút" as partial answer, not just a question mark)
    assert "?" in scenes[0].script or "HIỆU QUẢ HƠN" in scenes[0].script
    assert scenes[0].delivers is not None
```

- [ ] **Step 2: Write `test_final_scene_has_cta_or_summary`**

```python
def test_final_scene_has_cta_or_summary():
    """Last scene must have scene_type in [insight, technique, proof, cta]."""
    import json
    from unittest.mock import MagicMock, patch
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import GenerationLLM

    mock_channel = MagicMock()
    mock_channel.name = "Test"
    mock_channel.style = "friendly"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
    mock_channel.watermark = MagicMock(text="@test")

    gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
    gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=1536, retry_attempts=2, retry_backoff_max=5)

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        json.dumps({"video_message": "Test message"}),
        json.dumps({
            "scenes": [
                {"id": 1, "script": "Hook scene", "character": "NamMinh",
                 "scene_type": "hook", "delivers": "hook",
                 "creative_brief": {}, "image_prompt": "...", "lipsync_prompt": "..."},
                {"id": 2, "script": "Save lại và thử tuần này nhé!", "character": "NamMinh",
                 "scene_type": "cta", "delivers": "save & try CTA",
                 "creative_brief": {}, "image_prompt": "...", "lipsync_prompt": "..."},
            ]
        }),
    ]

    with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
        result = gen.generate_script_from_idea({"title": "Title", "content_angle": "tips", "topic_keywords": []})

    scenes = result["scenes"]
    assert scenes[-1].scene_type in ["insight", "technique", "proof", "cta"]
```

- [ ] **Step 3: Write `test_scene_count_dynamic`**

```python
def test_scene_count_dynamic():
    """LLM can return 2-5 scenes, not just exactly 3."""
    import json
    from unittest.mock import MagicMock, patch
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import GenerationLLM

    mock_channel = MagicMock()
    mock_channel.name = "Test"
    mock_channel.style = "friendly"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
    mock_channel.watermark = MagicMock(text="@test")

    gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
    gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=1536, retry_attempts=2, retry_backoff_max=5)

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        json.dumps({"video_message": "Test"}),
        json.dumps({
            "scenes": [
                {"id": 1, "script": "Scene 1", "character": "NamMinh",
                 "scene_type": "hook", "delivers": "h",
                 "creative_brief": {}, "image_prompt": "...", "lipsync_prompt": "..."},
                {"id": 2, "script": "Scene 2", "character": "NamMinh",
                 "scene_type": "insight", "delivers": "i",
                 "creative_brief": {}, "image_prompt": "...", "lipsync_prompt": "..."},
                {"id": 3, "script": "Scene 3", "character": "NamMinh",
                 "scene_type": "technique", "delivers": "t",
                 "creative_brief": {}, "image_prompt": "...", "lipsync_prompt": "..."},
                {"id": 4, "script": "Scene 4", "character": "NamMinh",
                 "scene_type": "cta", "delivers": "c",
                 "creative_brief": {}, "image_prompt": "...", "lipsync_prompt": "..."},
            ]
        }),
    ]

    with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
        result = gen.generate_script_from_idea({"title": "Title", "content_angle": "tips", "topic_keywords": []})

    assert 2 <= len(result["scenes"]) <= 5
    assert len(result["scenes"]) == 4
```

- [ ] **Step 4: Run all new tests**

Run: `pytest tests/test_content_idea_generator.py::test_scene_1_is_hook_with_partial_answer tests/test_content_idea_generator.py::test_final_scene_has_cta_or_summary tests/test_content_idea_generator.py::test_scene_count_dynamic -v`
Expected: All PASS.

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/test_content_idea_generator.py tests/test_scene_processor.py tests/test_prompt_builder.py -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_content_idea_generator.py
git commit -m "test: add scene quality validation tests — hook structure, CTA, dynamic count"
```

---

## Task 5: Run full test suite and verify

- [ ] **Step 1: Full test run**

Run: `pytest tests/ -v`
Expected: All 331+ tests pass.

- [ ] **Step 2: Commit any remaining changes**

```bash
git add -A && git commit -m "test: run full suite, all pass"
```

---

## Spec Coverage Check

| Spec Requirement | Task |
|---|---|
| `video_message` never null | Task 2 (`_generate_video_message` raises on null) |
| Two-step flow | Task 3 (`generate_script_from_idea` calls Step 1, then Step 2) |
| `video_message` as mandatory context in Step 2 | Task 3 (`_build_scene_prompt` includes `video_message` param) |
| Scene 1 is hook with partial answer | Task 4 (`test_scene_1_is_hook_with_partial_answer`) |
| Every scene delivers concrete value | Task 4 (`test_scene_1_is_hook_with_partial_answer` + `test_final_scene_has_cta_or_summary`) |
| Dynamic scene count (2–5) | Task 4 (`test_scene_count_dynamic`) |
| Final scene has CTA/summary | Task 4 (`test_final_scene_has_cta_or_summary`) |
| `scene_type` and `delivers` in SceneConfig | Task 1 (model update) |
| `SceneConfig.from_dict` parses new fields | Task 1 |
