# Caption CoT Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cải thiện CaptionGenerator bằng chain-of-thought prompt — LLM phân tích script trước rồi mới viết caption. Strict error handling: thiếu field = fail ngay, không fallback.

**Architecture:** Single-pass CoT prompt với 6-field JSON output schema. `thought_process` và `insight` là intermediate outputs để trace/debug. Template fallback bị xóa hoàn toàn.

**Tech Stack:** Python, LLM provider qua PluginRegistry, dataclass, JSON parsing

---

## File Map

| File | Responsibility |
|------|---------------|
| `modules/pipeline/exceptions.py` | Thêm `CaptionGenerationError` |
| `modules/content/caption_generator.py` | CoT prompt, strict parse, `GeneratedCaption` mới |
| `tests/test_caption_generator.py` | Tests cho CoT caption generation |

---

## Task 1: Thêm CaptionGenerationError exception

**Files:**
- Modify: `modules/pipeline/exceptions.py` (thêm class mới vào cuối file)

- [ ] **Step 1: Thêm CaptionGenerationError vào exceptions.py**

```python
class CaptionGenerationError(PipelineError):
    """Raised when LLM caption generation fails after all retries.

    Attributes:
        reason: string describing why generation failed (e.g. 'json_parse_error', 'missing_field:insight')
        original_error: optional underlying exception
    """

    def __init__(self, reason: str, original_error: Exception = None):
        self.reason = reason
        self.original_error = original_error
        msg = f"Caption generation failed: {reason}"
        super().__init__(msg)
```

- [ ] **Step 2: Commit**

```bash
git add modules/pipeline/exceptions.py
git commit -m "feat(caption): add CaptionGenerationError exception

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Viết test trước cho caption CoT

**Files:**
- Create: `tests/test_caption_generator.py`

- [ ] **Step 1: Viết test cho GeneratedCaption dataclass fields mới**

```python
import pytest
from modules.content.caption_generator import GeneratedCaption


def test_generated_caption_has_cot_fields():
    """GeneratedCaption phải có thought_process và insight fields."""
    cap = GeneratedCaption(
        thought_process="Script nói về việc người thông minh làm ít hơn",
        insight="Người thông minh không làm nhiều hơn, họ làm khác hơn",
        headline="🔥 Bí quyết của người thông minh",
        body="Người thông minh không làm nhiều hơn, họ làm KHÁC hơn.",
        hashtags=["#nangsuat", "#thongminh"],
        cta="Bạn nghĩ sao? Comment nhé!",
        full_caption="🔥 Bí quyết của người thông minh\nNgười thông minh...",
    )
    assert cap.thought_process == "Script nói về..."
    assert cap.insight == "Người thông minh không làm nhiều hơn, họ làm khác hơn"
    assert "thongminh" in cap.insight


def test_generated_caption_to_dict():
    """to_dict() phải include thought_process và insight."""
    cap = GeneratedCaption(
        thought_process="test reasoning",
        insight="test insight",
        headline="🔥 Headline",
        body="Body text",
        hashtags=["#tag"],
        cta="CTA",
        full_caption="Full",
    )
    d = cap.to_dict()
    assert "thought_process" in d
    assert "insight" in d
    assert d["thought_process"] == "test reasoning"
    assert d["insight"] == "test insight"
```

- [ ] **Step 2: Viết test cho LLM generate fail khi thiếu field**

```python
from unittest.mock import MagicMock
from modules.content.caption_generator import CaptionGenerator
from modules.pipeline.exceptions import CaptionGenerationError


def test_caption_generator_fails_when_llm_returns_incomplete_json():
    """LLM trả thiếu field -> CaptionGenerationError raised."""
    mock_llm = MagicMock()
    # Trả đủ fields TRỪ insight
    mock_llm.chat.return_value = '{"thought_process": "x", "headline": "y", "body": "z", "cta": "w", "hashtags": ["#t"]}'

    gen = CaptionGenerator(llm_provider=mock_llm)
    with pytest.raises(CaptionGenerationError) as exc_info:
        gen.generate("test script", platform="tiktok")
    assert "missing_field" in exc_info.value.reason
    assert "insight" in exc_info.value.reason
```

- [ ] **Step 3: Viết test cho retry on JSON parse error**

```python
def test_caption_generator_retries_on_json_parse_error():
    """JSON parse fail -> retry 1 lần, sau đó fail luôn."""
    mock_llm = MagicMock()
    # Lần 1: invalid JSON, Lần 2: valid nhưng thiếu insight
    mock_llm.chat.side_effect = [
        "this is not json",
        '{"thought_process": "x", "insight": "i", "headline": "y", "body": "z", "cta": "w", "hashtags": ["#t"]}',
    ]

    gen = CaptionGenerator(llm_provider=mock_llm)
    with pytest.raises(CaptionGenerationError) as exc_info:
        gen.generate("test script", platform="tiktok")
    assert exc_info.value.reason == "json_parse_error"
    assert mock_llm.chat.call_count == 2
```

- [ ] **Step 4: Viết test cho strict field presence check**

```python
def test_caption_generator_requires_all_six_fields():
    """Thiếu bất kỳ field nào trong 6 fields -> fail."""
    required = ["thought_process", "insight", "headline", "body", "cta", "hashtags"]
    mock_llm = MagicMock()

    for missing_field in required:
        fields = {f: "x" for f in required if f != missing_field}
        mock_llm.chat.return_value = json.dumps(fields)
        gen = CaptionGenerator(llm_provider=mock_llm)
        with pytest.raises(CaptionGenerationError) as exc_info:
            gen.generate("test script", platform="tiktok")
        assert missing_field in exc_info.value.reason
        mock_llm.reset_mock()
```

- [ ] **Step 5: Run tests để verify chúng fail**

Run: `pytest tests/test_caption_generator.py -v`
Expected: FAIL (code chưa implemented)

- [ ] **Step 6: Commit**

```bash
git add tests/test_caption_generator.py
git commit -m "test(caption): add tests for CoT caption generator

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Update GeneratedCaption dataclass

**Files:**
- Modify: `modules/content/caption_generator.py:28-44` — thêm fields mới vào dataclass

- [ ] **Step 1: Thêm thought_process và insight vào dataclass**

```python
@dataclass
class GeneratedCaption:
    """Output from caption generation."""
    thought_process: str   # NEW: internal reasoning from CoT
    insight: str           # NEW: contrarian hook
    headline: str
    body: str
    hashtags: List[str]
    cta: str
    full_caption: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thought_process": self.thought_process,
            "insight": self.insight,
            "headline": self.headline,
            "body": self.body,
            "hashtags": self.hashtags,
            "cta": self.cta,
            "full_caption": self.full_caption,
        }
```

- [ ] **Step 2: Chạy tests**

Run: `pytest tests/test_caption_generator.py -v`
Expected: FAIL (for_tiktok/for_facebook đã remove, full_caption logic changed)

- [ ] **Step 3: Commit**

```bash
git add modules/content/caption_generator.py
git commit -m "feat(caption): add thought_process and insight fields to GeneratedCaption

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Rewrite `_generate_via_llm()` với CoT prompt + strict parse

**Files:**
- Modify: `modules/content/caption_generator.py:176-223` — rewrite method

- [ ] **Step 1: Viết lại `_generate_via_llm()`**

Thay toàn bộ method này bằng implementation mới:

```python
def _generate_via_llm(self, script: str, platform: str) -> GeneratedCaption:
    """Generate caption via LLM with chain-of-thought prompting.

    Raises CaptionGenerationError on any failure (no defaults, no fallback).
    """
    if self._llm is None:
        raise CaptionGenerationError("llm_unavailable")

    platform_label = "TikTok" if platform == "tiktok" else "Facebook"

    if platform == "tiktok":
        system = (
            "Bạn là chuyên gia viết caption cho video TikTok/Reels Vietnamese.\n"
            "CRITICAL: Bạn PHẢI trả lời CHỈ có JSON hợp lệ, không có gì khác.\n\n"
            "CHUỖI SUY NGHĨ (chain-of-thought):\n"
            "1. Đọc script và phân tích:\n"
            "   - Điều bất ngờ/contrarian insight là gì?\n"
            "   - Key message chính là gì?\n"
            "   - Audience pain point là gì?\n"
            "2. Viết caption theo format bên dưới\n\n"
            "FORMAT JSON (bắt buộc - thiếu field = fail):\n"
            '{\n'
            '  "thought_process": "Chuỗi suy nghĩ của bạn khi phân tích script (1-2 câu)",\n'
            '  "insight": "Contrarian hook rút gọn 1-2 câu, gây tò mò mạnh nhất",\n'
            '  "headline": "🔥 headline dưới 10 từ, curiosity hook hoặc bold statement",\n'
            '  "body": "150 chars max, direct, conversational, viết như đang nói chuyện với viewer",\n'
            '  "cta": "CTA ngắn gọn dưới 15 từ, tự nhiên, kêu hành động cụ thể",\n'
            '  "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"]\n'
            "}\n\n"
            "RULES:\n"
            "- headline phải có fire emoji 🔥\n"
            "- body không quá 150 ký tự\n"
            "- hashtags phải là array có đúng 5 items, mỗi item phải bắt đầu bằng #\n"
            "- Không viết thêm giải thích gì khác ngoài JSON"
        )
    else:
        system = (
            "Bạn là chuyên gia viết caption cho Facebook post Vietnamese.\n"
            "CRITICAL: Bạn PHẢI trả lời CHỈ có JSON hợp lệ, không có gì khác.\n\n"
            "CHUỖI SUY NGHĨ (chain-of-thought):\n"
            "1. Đọc script và phân tích:\n"
            "   - Điều bất ngờ/contrarian insight là gì?\n"
            "   - Key message chính là gì?\n"
            "   - Audience pain point là gì?\n"
            "2. Viết caption theo format bên dưới\n\n"
            "FORMAT JSON (bắt buộc - thiếu field = fail):\n"
            '{\n'
            '  "thought_process": "Chuỗi suy nghĩ của bạn khi phân tích script (1-2 câu)",\n'
            '  "insight": "Contrarian hook rút gọn 1-2 câu, gây tò mò mạnh nhất",\n'
            '  "headline": "**headline dưới 10 từ, bold statement**",\n'
            '  "body": "300 chars, có context, có giá trị, viết tự nhiên như storyteller",\n'
            '  "cta": "Câu hỏi gợi discussion, tag bạn bè, hoặc kêu hành động cụ thể",\n'
            '  "hashtags": ["#tag1", "#tag2", "#tag3"]\n'
            "}\n\n"
            "RULES:\n"
            "- headline không cần emoji, dùng **bold** cho emphasis\n"
            "- body tối đa 300 ký tự\n"
            "- hashtags phải là array có đúng 3 items, mỗi item phải bắt đầu bằng #\n"
            "- Không viết thêm giải thích gì khác ngoài JSON"
        )

    user = f'Video script:\n"{script[:800]}"\n\nViết caption theo format JSON ở trên.'

    # Retry logic: 1 retry on JSON parse failure
    last_error = None
    for attempt in range(2):
        try:
            response = self._llm.chat(user, system=system, max_tokens=1200)
            m = re.search(r'\{.*\}', response, re.DOTALL)
            if not m:
                raise CaptionGenerationError(
                    "json_parse_error",
                    ValueError(f"No JSON found in response: {response[:100]}")
                )

            data = json.loads(m.group())

            # Strict field presence check - all 6 fields required
            required_fields = ["thought_process", "insight", "headline", "body", "cta", "hashtags"]
            for field in required_fields:
                if field not in data:
                    raise CaptionGenerationError(
                        f"missing_field:{field}",
                        ValueError(f"Response missing required field: {field}")
                    )
                if data[field] is None or (isinstance(data[field], str) and not data[field].strip()):
                    raise CaptionGenerationError(
                        f"missing_field:{field}",
                        ValueError(f"Field '{field}' is empty")
                    )

            # Validate hashtags structure
            if not isinstance(data["hashtags"], list):
                raise CaptionGenerationError(
                    "invalid_field:hashtags",
                    ValueError("hashtags must be a list")
                )
            if platform == "tiktok" and len(data["hashtags"]) != 5:
                raise CaptionGenerationError(
                    "invalid_field:hashtags",
                    ValueError(f"TikTok requires exactly 5 hashtags, got {len(data['hashtags'])}")
                )
            if platform == "facebook" and len(data["hashtags"]) != 3:
                raise CaptionGenerationError(
                    "invalid_field:hashtags",
                    ValueError(f"Facebook requires exactly 3 hashtags, got {len(data['hashtags'])}")
                )

            # Build full_caption
            if platform == "tiktok":
                full = "\n".join([
                    f"🔥 {data['headline']}",
                    data['body'],
                    data['cta'],
                    " ".join(data['hashtags']),
                ])
            else:
                full = "\n".join([
                    f"**{data['headline']}**",
                    data['body'],
                    f"👉 {data['cta']}",
                    " ".join(data['hashtags']),
                ])

            logger.info(f"Caption generated via LLM (CoT mode)")
            return GeneratedCaption(
                thought_process=data["thought_process"],
                insight=data["insight"],
                headline=data["headline"],
                body=data["body"],
                hashtags=data["hashtags"],
                cta=data["cta"],
                full_caption=full,
            )

        except CaptionGenerationError:
            raise  # Already structured, re-raise
        except Exception as e:
            last_error = e
            continue  # Retry

    # Both attempts failed
    raise CaptionGenerationError(
        "json_parse_error",
        last_error or ValueError("Unknown error")
    )
```

- [ ] **Step 2: Update `generate()` method**

```python
def generate(self, script: str, platform: str = "tiktok") -> GeneratedCaption:
    """Generate caption via LLM only. No fallback."""
    return self._generate_via_llm(script, platform)
```

- [ ] **Step 3: Update imports**

```python
from modules.pipeline.exceptions import CaptionGenerationError
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_caption_generator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/content/caption_generator.py
git commit -m "feat(caption): implement CoT caption generation with strict error handling

- CoT prompt with thought_process and insight intermediates
- Strict 6-field presence validation
- No template fallback - fail on any LLM error
- Retry once on JSON parse failure

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 5: Remove template fallback code

**Files:**
- Modify: `modules/content/caption_generator.py` — xóa `_generate_template()`, `HEADLINE_TEMPLATES`, `CTA_TEMPLATES`, `HASHTAG_SETS`

- [ ] **Step 1: Xóa các constants và method fallback**

Xóa:
- `HEADLINE_TEMPLATES` (line ~71)
- `CTA_TEMPLATES` (line ~82)
- `HASHTAG_SETS` (line ~93)
- `_generate_template()` method

- [ ] **Step 2: Xóa `batch_generate()` nếu nó gọi template**

Đọc `batch_generate()` — nếu nó gọi `generate()` thì OK (generate() gọi LLM). Nhưng kiểm tra xem có logic fallback nào không.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_caption_generator.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add modules/content/caption_generator.py
git commit -m "refactor(caption): remove template fallback code

Template-based generation removed - all captions go through LLM.
If LLM fails, CaptionGenerationError is raised immediately.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Self-Review Checklist

After writing the plan, run through:

1. **Spec coverage:** Each section in `2026-04-16-caption-cot-design.md` maps to a task?
   - [x] Tổng quan schema → Task 3 (dataclass), Task 4 (CoT prompt)
   - [x] TikTok vs Facebook prompts → Task 4
   - [x] GeneratedCaption fields → Task 3
   - [x] Strict error handling → Task 1, Task 4
   - [x] Retry logic → Task 4 (retry loop)
   - [x] Files to change → All tasks

2. **Placeholder scan:** No "TBD", "TODO", "implement later" in steps.

3. **Type consistency:** All tasks reference same dataclass field names: `thought_process`, `insight`, `headline`, `body`, `cta`, `hashtags`, `full_caption`.

4. **Spec vs Plan gaps:**
   - Spec says "bỏ for_tiktok()/for_facebook()" → Task 3 removes these from dataclass (not methods since they were instance methods, not class methods — but `full_caption` is now pre-formatted so they become unnecessary)
   - Spec says `CaptionGenerationError` in exceptions.py → Task 1
   - Spec says 1 retry on JSON parse fail → Task 4 retry loop

---

## Plan saved to: `docs/superpowers/plans/2026-04-16-caption-cot-implementation-plan.md`
