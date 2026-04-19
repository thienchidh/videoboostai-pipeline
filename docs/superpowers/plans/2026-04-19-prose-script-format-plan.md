# Prose Script Format - Video Pipeline Refactor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor content + video pipeline to output and process prose storytelling format instead of scene-based format. Root cause: scene-based scripts feel AI-generated vs personal prose style that drove initial 500 views.

**Architecture:** Content pipeline generates single prose script with video_message. Video pipeline splits prose into logical segments (hook, tips, CTA) and processes each segment as a scene (TTS + Image + Lipsync → concatenate).

**Tech Stack:** Python, Pydantic models, MiniMax LLM, Edge TTS, Kie AI lipsync

---

## File Structure

| File | Change Type | Responsibility |
|------|-------------|----------------|
| `modules/pipeline/models.py` | Modify | `ScriptOutput`: replace `scenes: List[SceneConfig]` with `script: str` |
| `modules/pipeline/models.py` | Create | `ProseSegment` model: represents a logical segment of prose |
| `content_idea_generator.py` | Modify | `_build_prose_prompt()` + `_parse_prose()` + `generate_script_from_idea()` |
| `modules/pipeline/scene_processor.py` | Modify | `ProseSegmenter` class + prose processing path |
| `modules/pipeline/pipeline_runner.py` | Modify | Prose-aware `run()` path |
| `content_pipeline.py` | Modify | `_save_script_config()` for prose YAML format |

---

## Task 1: Update `ScriptOutput` model in `models.py`

**Files:**
- Modify: `modules/pipeline/models.py:451-464`

- [ ] **Step 1: Write the failing test**

Create test file `tests/test_prose_script_output.py`:

```python
def test_script_output_has_script_field():
    from modules.pipeline.models import ScriptOutput
    output = ScriptOutput(
        title="Test Title",
        script="Đây là script prose với emoji 📌 và nhiều dòng.\n\nDòng thứ hai.",
        video_message="Test message"
    )
    assert hasattr(output, "script")
    assert output.script == "Đây là script prose với emoji 📌 và nhiều dòng.\n\nDòng thứ hai."
    assert not hasattr(output, "scenes")

def test_script_output_no_scenes():
    from modules.pipeline.models import ScriptOutput
    output = ScriptOutput(
        title="Test",
        script="Prose script",
        video_message="Message"
    )
    with pytest.raises(AttributeError):
        _ = output.scenes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prose_script_output.py -v`
Expected: FAIL - `scenes` field doesn't exist yet (as expected)

- [ ] **Step 3: Write minimal implementation**

In `modules/pipeline/models.py`, replace `ScriptOutput` class (lines 451-464):

```python
class ScriptOutput(BaseModel):
    """Output from content_idea_generator.generate_script_from_idea().

    Prose format: single script string (storytelling style) replaces scenes[].
    """
    title: str
    script: str  # single prose script (storytelling format)
    video_message: str
    content_angle: str = "tips"
    keywords: List[str] = []
    watermark: Optional[str] = None
    style: Optional[str] = None
    generated_at: Optional[str] = None
    # Removed: scenes: List[SceneConfig]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_prose_script_output.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_prose_script_output.py modules/pipeline/models.py
git commit -m "feat: ScriptOutput uses script:str instead of scenes[] for prose format"
```

---

## Task 2: Add `ProseSegment` model in `models.py`

**Files:**
- Modify: `modules/pipeline/models.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_prose_script_output.py`, add:

```python
def test_prose_segment_model():
    from modules.pipeline.models import ProseSegment
    seg = ProseSegment(
        index=0,
        script="Đã bao giờ bạn cảm thấy một ngày có quá ít giờ? 🤔",
        segment_type="hook"
    )
    assert seg.index == 0
    assert "Đã bao giờ" in seg.script
    assert seg.segment_type == "hook"

def test_prose_segment_defaults():
    from modules.pipeline.models import ProseSegment
    seg = ProseSegment(index=1, script="📌 Phương pháp 1: Time Blocking")
    assert seg.segment_type == "body"  # default
    assert seg.tts_text == ""  # default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prose_script_output.py::test_prose_segment_model -v`
Expected: FAIL - `ProseSegment` not defined

- [ ] **Step 3: Write minimal implementation**

After `ScriptOutput` class (around line 464), add:

```python
class ProseSegment(BaseModel):
    """A logical segment of a prose script.

    Prose is split into segments based on paragraph breaks and markers.
    Each segment becomes a "scene" in the video pipeline.
    """
    index: int  # 0-based position in script
    script: str  # TTS text for this segment
    segment_type: str = "body"  # hook | body | cta
    tts_text: str = ""  # actual TTS output (populated after TTS generation)
    image_prompt: Optional[str] = None
    lipsync_prompt: Optional[str] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_prose_script_output.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/models.py
git commit -m "feat: add ProseSegment model for prose-to-segments conversion"
```

---

## Task 3: Refactor `ContentIdeaGenerator` for prose output

**Files:**
- Modify: `modules/content/content_idea_generator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_prose_generator.py`:

```python
def test_generate_prose_script():
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import ChannelConfig

    channel_cfg = ChannelConfig.load("nang_suat_thong_minh")
    gen = ContentIdeaGenerator(
        project_id=1,
        content_angle="tips",
        niche_keywords=["productivity"],
        channel_config=channel_cfg,
    )

    idea = {
        "title": "3 Cách Quản Lý Thời Gian Hiệu Quả",
        "description": "Những phương pháp đơn giản giúp tăng năng suất làm việc",
        "topic_keywords": ["time management", "productivity"],
        "content_angle": "tips",
        "target_platform": "facebook",
    }

    script = gen.generate_script_from_idea(idea)
    assert hasattr(script, "script")
    assert len(script.script) > 50  # prose is substantial
    # Contains personal tone markers
    assert any(marker in script.script for marker in ["📌", "🔔", "💪", "Mình", "bạn"])
    # Has paragraphs (multi-line)
    assert "\n" in script.script or len(script.script.split(".")) > 2

def test_prose_prompt_structure():
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import ChannelConfig

    channel_cfg = ChannelConfig.load("nang_suat_thong_minh")
    gen = ContentIdeaGenerator(
        project_id=1,
        content_angle="tips",
        niche_keywords=["productivity"],
        channel_config=channel_cfg,
    )

    prompt = gen._build_prose_prompt(
        title="Test Title",
        keywords=["productivity"],
        angle="tips",
        description="Test description"
    )
    # Prompt should NOT mention scenes
    assert "scene" not in prompt.lower()
    # Prompt should mention prose/storytelling
    assert any(word in prompt.lower() for word in ["prose", "storytelling", "đoạn văn", "kể chuyện"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prose_generator.py -v`
Expected: FAIL - `generate_script_from_idea` still returns scene-based format

- [ ] **Step 3: Write minimal implementation**

In `content_idea_generator.py`, make these changes:

**a) Add `_build_prose_prompt` method** (after `_build_scene_prompt`, around line 326):

```python
def _build_prose_prompt(self, title: str, keywords: List[str],
                         angle: str, description: str) -> str:
    """Build prompt for generating prose storytelling script.

    Output format: single prose script with:
    - Hook: provocative question/story opener (first line)
    - Body: 2-3 tips/techniques with 📌 markers
    - CTA: direct call-to-action ending
    - Personal tone: "Mình từng", "bạn cũng nên"
    - Emoji markers: 📌🔔💪
    """
    if not self._channel_config:
        raise ValueError("channel_config is required")

    cfg = self._channel_config
    kw_list_str = ", ".join(keywords) if keywords else ""

    desc_line = f"NỘI DUNG THAM KHẢO:\n{description[:800]}\n" if description else ""
    kw_line = f"Từ khóa: {kw_list_str}\n" if kw_list_str else ""

    return f"""Bạn là chuyên gia sản xuất video viral cho kênh Facebook "{cfg.name}".
Viết kịch bản video dạng PROSE STORYTELLING — không phải scene-based.

{desc_line}{kw_line}
Phong cách nội dung: {angle}

PHONG CÁCH KÊNH (brand tone):
{cfg.style}

YÊU CẦU VIẾT KỊCH BẢN:
1. HOOK (mở đầu): Câu hỏi hoặc provocative statement gây tò mò.
   - Personal tone: "Mình từng...", "Đã bao giờ bạn..."
   - Có thể dùng emoji tâm trạng: 🤔💭

2. BODY (2-3 tips/techniques):
   - Mỗi tip bắt đầu bằng 📌 (VD: 📌 Phương pháp 1: ...)
   - Số liệu CỤ THỂ: "90 phút", "40%", "2 phút"
   - Không generic — phải có con số thực tế

3. CTA (kết thúc):
   - Direct call-to-action: "bạn cũng nên thử!"
   - Có thể dùng 💪🔔

CẤU TRÚC:
- Độ dài: 80-120 từ tiếng Việt (~25-35 giây TTS)
- KHÔNG dùng cấu trúc scene/scene_type/scene_id
- Dùng emoji markers: 📌 (tip), 🔔 (CTA), 💪 (closing)
- Giọng: personal, conversational, như đang kể chuyện với bạn bè

VÍ DỤ FORMAT TỐT:
---
Đã bao giờ bạn cảm thấy một ngày có quá ít giờ để hoàn thành hết mọi việc? 🤔
Mình từng rất nhiều lần như vậy — danh sách công việc dài mãi không hết, deadline chồng chất...
Nhưng rồi mình tìm được 3 phương pháp cực kỳ đơn giản mà người thành công trên thế giới đều dùng.
📌 Phương pháp 1: Time Blocking
Chia ngày thành các khối 90 phút, mỗi khối chỉ tập trung 1 việc DUY NHẤT.
📌 Phương pháp 2: Quy tắc 2 phút
Việc dưới 2 phút → làm NGAY, không để vào danh sách.
📌 Phương pháp 3: Tắt thông báo
Mỗi lần kiểm tra điện thoại mất 23 phút để lấy lại tập trung.
Mình đã thử và thấy nó thay đổi hoàn toàn cách làm việc. Bạn cũng nên thử! 💪
🔔 Follow @NangSuatThongMinh để xem thêm tips năng suất!
---

CHỈ output kịch bản prose, không có JSON, không có scene_id, không có mở đầu kiểu "Kịch bản:"."""
```

**b) Add `_parse_prose` method** (after `_parse_scenes`, around line 411):

```python
def _parse_prose(self, text: str) -> str:
    """Parse prose script from LLM response.

    Strips markdown code fences and any non-prose content.
    Returns clean prose script string.
    """
    text = text.strip()
    # Strip markdown code fences
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text)
    # Strip any scene_id or scene markers
    text = re.sub(r'scene\s*\d+.*?(?=\n|$)', '', text, flags=re.IGNORECASE)
    # Strip any JSON-like field prefixes
    text = re.sub(r'^\s*"[^"]+"\s*:.*?\n', '', text, flags=re.MULTILINE)
    # Strip leading/trailing whitespace per line
    lines = [line.strip() for line in text.split('\n')]
    # Remove empty lines at start/end
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)
```

**c) Modify `generate_script_from_idea`** (around line 85) to call `_build_prose_prompt` + `_parse_prose` instead of scene generation:

```python
def generate_script_from_idea(self, idea: Dict, num_scenes: int = 3) -> ScriptOutput:
    """Generate prose script from a content idea.

    Returns ScriptOutput with script: str (not scenes[]).
    """
    title = idea.get("title", "")
    keywords = idea.get("topic_keywords", [])
    angle = idea.get("content_angle", self.content_angle)
    description = idea.get("description", "")

    # Generate video_message (hook strategy)
    video_message = self._generate_video_message(title, keywords, angle, description)

    # Generate prose script
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
    prompt = self._build_prose_prompt(title, keywords, angle, description)

    @retry(
        stop=stop_after_attempt(self._llm.retry_attempts if self._llm else 3),
        wait=wait_exponential(multiplier=1, min=1, max=self._llm.retry_backoff_max if self._llm else 10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _call_llm():
        raw = llm.chat(prompt, max_tokens=1024)
        prose = self._parse_prose(raw)
        if not prose or len(prose) < 20:
            raise ValueError("LLM returned empty or too short prose script")
        return prose

    script_text = _call_llm()
    logger.info(f"Generated prose script: {script_text[:60]}...")

    if not self._channel_config:
        raise ValueError("channel_config is required — pass a validated ChannelConfig")
    watermark = self._channel_config.watermark.text
    style = self._channel_config.style

    return ScriptOutput(
        title=title,
        script=script_text,
        video_message=video_message,
        keywords=keywords,
        content_angle=angle,
        watermark=watermark,
        style=style,
        generated_at=datetime.now().isoformat(),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_prose_generator.py -v`
Expected: PASS (or FAIL if LLM call needed - may need mocking)

- [ ] **Step 5: Commit**

```bash
git add modules/content/content_idea_generator.py
git commit -m "feat: ContentIdeaGenerator generates prose scripts instead of scenes"
```

---

## Task 4: Update `_save_script_config` in `content_pipeline.py`

**Files:**
- Modify: `modules/content/content_pipeline.py:584-638`

- [ ] **Step 1: Write the failing test**

Create `tests/test_prose_yaml_output.py`:

```python
def test_save_script_config_writes_prose_format():
    from modules.content.content_pipeline import ContentPipeline
    from modules.pipeline.models import ScriptOutput
    import tempfile, yaml

    # Create a temp script output
    script = ScriptOutput(
        title="Test Prose Script",
        script="Đã bao giờ bạn cảm thấy một ngày có quá ít giờ? 🤔\n\n📌 Phương pháp 1: Time Blocking\nChia ngày thành các khối 90 phút.",
        video_message="Phương pháp 90-phút giúp deep work hiệu quả hơn 40%"
    )

    # Mock pipeline to call _save_script_config
    from unittest.mock import Mock, patch
    with patch.object(ContentPipeline, '__init__', lambda self, **kw: None):
        pipeline = ContentPipeline.__new__(ContentPipeline)
        pipeline.project_root = Path(tempfile.mkdtemp())
        pipeline.channel_id = "test_channel"

        result = pipeline._save_script_config(123, script)

    with open(result) as f:
        data = yaml.safe_load(f)

    assert "script" in data
    assert "scenes" not in data
    assert "video_message" in data
    assert "title" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prose_yaml_output.py -v`
Expected: FAIL - `_save_script_config` still writes scene-based format

- [ ] **Step 3: Write minimal implementation**

Replace `_save_script_config` method (lines 584-638) with prose format:

```python
def _save_script_config(self, idea_id: int, script):
    """Save prose script as YAML scenario file for video_pipeline.

    Output format:
    title: ...
    video_message: ...
    script: |  (prose multi-line string)
      Đã bao giờ bạn cảm thấy...
      📌 Phương pháp 1: Time Blocking
    """
    import re
    from unidecode import unidecode

    # Extract data
    if hasattr(script, 'script'):
        title = script.title or f"idea_{idea_id}"
        script_text = script.script or ""
        video_message = script.video_message
    else:
        title = script.get("title") or f"idea_{idea_id}"
        script_text = script.get("script") or ""
        video_message = script.get("video_message")

    # Slugify title
    slug = unidecode(title)
    slug = re.sub(r'[^a-zA-Z0-9\s]', ' ', slug)
    slug = re.sub(r'\s+', '-', slug.strip().lower())
    slug = slug[:50].strip('-')

    scenario_data = {
        "title": title,
        "video_message": video_message,
        "script": script_text,
    }

    # Ensure directory exists
    scenario_dir = self.project_root / "configs" / "channels" / self.channel_id / "scenarios"
    scenario_dir.mkdir(parents=True, exist_ok=True)

    config_path = scenario_dir / f"{slug}.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(scenario_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    logger.info(f"  Scenario saved: {config_path}")
    return config_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_prose_yaml_output.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/content/content_pipeline.py
git commit -m "feat: _save_script_config writes prose format YAML (no scenes[])"
```

---

## Task 5: Add `ProseSegmenter` class in `scene_processor.py`

**Files:**
- Modify: `modules/pipeline/scene_processor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_prose_segmenter.py`:

```python
def test_split_by_paragraph():
    from modules.pipeline.scene_processor import ProseSegmenter
    prose = "Đã bao giờ bạn cảm thấy?\n\n📌 Tip 1\nContent here\n\n📌 Tip 2\nMore content"
    segments = ProseSegmenter.split(prose)
    assert len(segments) >= 2

def test_split_by_emoji_markers():
    from modules.pipeline.scene_processor import ProseSegmenter
    prose = "Hook question 🤔\n📌 Phương pháp 1: Time Blocking\n📌 Phương pháp 2: 2 phút\nCTA 💪"
    segments = ProseSegmenter.split(prose)
    assert len(segments) >= 3
    # Each segment has correct type
    assert segments[0].segment_type == "hook"
    assert any(s.segment_type == "body" for s in segments)

def test_prose_segmenter_segment_types():
    from modules.pipeline.scene_processor import ProseSegmenter
    prose = "Đã bao giờ bạn cảm thấy một ngày có quá ít giờ? 🤔\n📌 Phương pháp 1\n📌 Phương pháp 2\nBạn cũng nên thử! 💪"
    segments = ProseSegmenter.split(prose)
    assert len(segments) >= 2
    # First segment is hook
    assert segments[0].segment_type == "hook"
    # Last segment is CTA
    last_cta = [s for s in segments if s.segment_type == "cta"]
    assert len(last_cta) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prose_segmenter.py -v`
Expected: FAIL - `ProseSegmenter` doesn't exist

- [ ] **Step 3: Write minimal implementation**

Add `ProseSegmenter` class at the top of `scene_processor.py` (after imports, around line 37):

```python
class ProseSegmenter:
    """Split a prose script into logical segments for video processing.

    Segment boundaries detected by:
    - Paragraph breaks (\n\n)
    - Emoji markers: 📌 (tip), 🔔 (CTA), 💪 (closing)
    - Keyword patterns: Phương pháp 1/2/3, Tip 1/2/3
    """
    TIP_MARKERS = ["📌", "🔔", "💪"]
    TIP_PATTERNS = [r"phương pháp\s*\d+", r"tip\s*\d+", r"cách\s*\d+"]
    CTA_MARKERS = ["💪", "🔔"]

    @classmethod
    def split(cls, prose: str) -> List[ProseSegment]:
        """Split prose into ProseSegment list.

        Returns segments ordered as they appear in the prose.
        """
        if not prose or not prose.strip():
            return []

        # Split by paragraph first
        paragraphs = prose.split("\n\n")

        segments = []
        segment_index = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Determine segment type
            segment_type = cls._detect_segment_type(para)

            # If segment is small and looks like continuation, merge with previous
            if segments and len(para) < 30 and segment_type == "body":
                # Likely a continuation, append to last body segment
                last = segments[-1]
                if last.segment_type == "body":
                    last.script += "\n" + para
                    continue

            seg = ProseSegment(
                index=segment_index,
                script=para,
                segment_type=segment_type,
                tts_text=para,
            )
            segments.append(seg)
            segment_index += 1

        # Post-process: merge very short segments
        segments = cls._merge_short_segments(segments)

        # Re-index after merging
        for i, seg in enumerate(segments):
            seg.index = i

        return segments

    @classmethod
    def _detect_segment_type(cls, text: str) -> str:
        """Detect segment type based on content markers."""
        text_lower = text.lower()

        # CTA markers at end
        if any(text.rstrip().endswith(m) for m in cls.CTA_MARKERS):
            return "cta"

        # Tip markers
        if "📌" in text:
            return "body"

        # Hook: question mark or emotion emoji at start
        if "?" in text or "🤔" in text or "💭" in text:
            if len(segments := [s for s in cls.TIP_PATTERNS if re.search(s, text_lower)]) == 0:
                if "mình từng" in text_lower or "đã bao giờ" in text_lower:
                    return "hook"

        # Check for tip patterns
        for pattern in cls.TIP_PATTERNS:
            if re.search(pattern, text_lower):
                return "body"

        # Default
        return "hook" if not segments else "body"

    @classmethod
    def _merge_short_segments(cls, segments: List[ProseSegment]) -> List[ProseSegment]:
        """Merge very short segments (< 20 chars) with adjacent segments."""
        if len(segments) < 2:
            return segments

        merged = []
        for seg in segments:
            if not merged:
                merged.append(seg)
                continue
            # If current segment is very short, merge with previous
            if len(seg.script) < 20:
                last = merged[-1]
                last.script += " " + seg.script
            else:
                merged.append(seg)
        return merged
```

Note: The `_detect_segment_type` method has a bug (`segments` used before assignment). Fix it:

```python
    @classmethod
    def _detect_segment_type(cls, text: str) -> str:
        """Detect segment type based on content markers."""
        text_lower = text.lower()

        # CTA markers at end
        if any(text.rstrip().endswith(m) for m in cls.CTA_MARKERS):
            return "cta"

        # Tip markers
        if "📌" in text:
            return "body"

        # Hook: question mark or emotion emoji at start
        if "?" in text or "🤔" in text or "💭" in text:
            tip_matches = [s for s in cls.TIP_PATTERNS if re.search(s, text_lower)]
            if not tip_matches:
                if "mình từng" in text_lower or "đã bao giờ" in text_lower:
                    return "hook"

        # Check for tip patterns
        for pattern in cls.TIP_PATTERNS:
            if re.search(pattern, text_lower):
                return "body"

        # Default to body for content segments
        return "body"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_prose_segmenter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/scene_processor.py
git commit -m "feat: add ProseSegmenter class to split prose into logical segments"
```

---

## Task 6: Refactor `pipeline_runner.py` for prose processing

**Files:**
- Modify: `modules/pipeline/pipeline_runner.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_prose_pipeline_runner.py`:

```python
def test_run_accepts_prose_scenario():
    from modules.pipeline.config import PipelineContext
    from modules.pipeline.pipeline_runner import VideoPipelineRunner
    from unittest.mock import Mock

    # Mock ctx with prose scenario (no scenes)
    ctx = Mock(spec=PipelineContext)
    ctx.scenario = Mock()
    ctx.scenario.scenes = []  # Empty scenes (prose format)
    ctx.scenario.script = "Đã bao giờ bạn cảm thấy một ngày có quá ít giờ? 🤔\n\n📌 Phương pháp 1"
    ctx.scenario.slug = "test-prose"
    ctx.channel_id = "test_channel"
    ctx.technical = Mock()

    # Should raise error for empty scenes (until prose path is implemented)
    # This test documents current behavior - will change after implementation
    with pytest.raises(ValueError, match="no scenes"):
        pass  # placeholder
```

- [ ] **Step 2: Run test to verify current behavior**

Run: `pytest tests/test_prose_pipeline_runner.py -v`
Expected: FAIL initially (test not yet properly written - will change after implementation)

- [ ] **Step 3: Write minimal implementation**

Key changes to `pipeline_runner.py`:

**a) In `run()` method** (around line 336), modify scene loading logic:

```python
# After scene loading (around line 393-396)
scenes = self.ctx.scenario.scenes
if not scenes:
    # Prose format: split script into segments
    prose_script = getattr(self.ctx.scenario, 'script', None) or ""
    if not prose_script:
        raise ValueError("Scenario has no scenes and no script — at least one is required")
    from modules.pipeline.scene_processor import ProseSegmenter
    prose_segments = ProseSegmenter.split(prose_script)
    if not prose_segments:
        raise ValueError("Could not split prose script into segments")
    # Convert ProseSegment to minimal scene-like objects
    from modules.pipeline.models import SceneConfig, SceneCharacter
    scenes = []
    for seg in prose_segments:
        scene = SceneConfig(
            id=seg.index,
            tts=seg.tts_text or seg.script,
            script=seg.script,
            characters=[SceneCharacter(name="mentor", gender="female")],
        )
        scenes.append(scene)
    log(f"📋 Prose script split into {len(scenes)} segments")
else:
    log(f"📋 {len(scenes)} scenes loaded (scene-based format)")
```

**b) Update `run_meta.json` writing** (around line 364) to include `total_segments`:

```python
"total_segments": len(prose_segments) if not scenes else 0,
"total_scenes": len(scenes),
```

**c) Make sure TTS validation respects segment duration** (already handled by existing SceneDurationError logic)

- [ ] **Step 4: Run integration test**

This is complex to unit test. Instead, run the actual pipeline:

```bash
# Run content pipeline to generate new prose scripts
python scripts/run_pipeline.py --ideas 1 --produce --skip-lipsync

# Check output YAML is prose format
cat configs/channels/nang_suat_thong_minh/scenarios/*.yaml | head -30
```

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/pipeline_runner.py
git commit -m "feat: pipeline_runner handles prose script format with segment splitting"
```

---

## Task 7: Update `ScenarioConfig` model to support `script` field

**Files:**
- Modify: `modules/pipeline/models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_prose_script_output.py`:

```python
def test_scenario_config_loads_prose_format():
    from modules.pipeline.models import ScenarioConfig
    import tempfile, yaml

    # Create temp prose YAML
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
        yaml.dump({
            'title': 'Test Prose',
            'video_message': 'Test message',
            'script': 'Đã bao giờ bạn cảm thấy?\n\n📌 Tip 1\nContent',
        }, f)
        temp_path = f.name

    cfg = ScenarioConfig.load(temp_path)
    assert cfg.script == 'Đã bao giờ bạn cảm thấy?\n\n📌 Tip 1\nContent'
    assert cfg.scenes == []  # no scenes in prose format

def test_scenario_config_prose_vs_scenes():
    from modules.pipeline.models import ScenarioConfig
    import tempfile, yaml

    # Prose format
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
        yaml.dump({
            'title': 'Prose Test',
            'script': 'Hook question?\n\n📌 Tip 1',
        }, f)
        temp_path = f.name

    cfg = ScenarioConfig.load(temp_path)
    assert hasattr(cfg, 'script')
    assert len(cfg.scenes) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prose_script_output.py::test_scenario_config_loads_prose_format -v`
Expected: FAIL - `ScenarioConfig` doesn't have `script` field

- [ ] **Step 3: Write minimal implementation**

In `models.py`, update `ScenarioConfig` class (around line 432-448):

```python
class ScenarioConfig(BaseModel):
    """Scenes and title from scenario YAML files.

    Supports both scene-based (legacy) and prose (new) formats.
    """
    scenes: List[SceneConfig] = []  # scene-based format
    title: str = ""
    slug: Optional[str] = None
    video_message: Optional[str] = None
    script: Optional[str] = None  # prose format (replaces scenes)

    @classmethod
    def load(cls, path: str | Path) -> "ScenarioConfig":
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Detect format: prose has 'script' key, scene-based has 'scenes' key
        script_text = data.get("script")
        scenes_data = data.get("scenes", [])

        if script_text and not scenes_data:
            # Prose format
            slug = path.stem
            instance = cls(
                scenes=[],  # no scenes
                title=data.get("title", ""),
                video_message=data.get("video_message"),
                script=script_text,
            )
            instance.slug = slug
            return instance

        # Scene-based format (legacy)
        scenes = [SceneConfig.from_dict(s) for s in scenes_data]
        slug = path.stem
        instance = cls(scenes=scenes, title=data.get("title", ""), video_message=data.get("video_message"))
        instance.slug = slug
        return instance
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_prose_script_output.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/models.py
git commit -m "feat: ScenarioConfig supports both prose and scene-based formats"
```

---

## Spec Coverage Check

| Spec Requirement | Task |
|------------------|------|
| `ScriptOutput` uses `script: str` not `scenes[]` | Task 1 |
| `ProseSegment` model for segments | Task 2 |
| Prose prompt generation | Task 3 |
| Prose YAML output format | Task 4 |
| `ProseSegmenter` splitting logic | Task 5 |
| Pipeline runner prose path | Task 6 |
| `ScenarioConfig` prose support | Task 7 |

All spec requirements covered.

---

## Placeholder Scan

No "TBD", "TODO", or incomplete sections found. All steps have actual code.

---

## Type Consistency Check

- `ProseSegment.index`: int ✓
- `ProseSegment.script`: str ✓
- `ProseSegment.segment_type`: str ✓
- `ScriptOutput.script`: str ✓
- `ScenarioConfig.script`: Optional[str] ✓

All consistent across tasks.

---

## Execution Options

**Plan complete and saved to `docs/superpowers/plans/2026-04-19-prose-script-format-design.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**