# Design: Chain-of-Thought Caption Generator

**Date:** 2026-04-16
**Author:** Claude
**Status:** Approved

---

## 1. Tổng quan

Cải thiện `CaptionGenerator._generate_via_llm()` bằng cách đổi từ single-pass prompt → **chain-of-thought prompt** với `thought_process` và `insight` làm intermediate outputs. Hệ thống yêu cầu strict output — thiếu field = fail ngay, không silent default.

**LLM output schema mới:**

```json
{
  "thought_process": "Phân tích script: điều bất ngờ, key message, pain point...",
  "insight": "Contrarian insight rút gọn 1-2 câu, hook mạnh",
  "headline": "🔥 headline dưới 10 từ, curiosity hook",
  "body": "150-300 chars, story-telling, natural Vietnamese",
  "cta": "CTA tự nhiên, gắn với nội dung video",
  "hashtags": ["#tag1", "#tag2", ...]
}
```

---

## 2. Prompt cho TikTok vs Facebook

**TikTok prompt:**
- System: viết caption ngắn, emoji nhiều, hook ngay đầu
- Body: 150 chars max, direct, conversational
- CTA: like/share/comment ngắn gọn
- Hashtags: 5-8 cái, trending + niche

**Facebook prompt:**
- System: caption dài hơn, storytelling nhẹ
- Body: 300 chars, có context, có giá trị
- CTA: câu hỏi gợi discussion, tag bạn bè
- Hashtags: ít hơn (3-5), viết tự nhiên hơn

Platform parameter truyền vào prompt để LLM adapt tone + length.

---

## 3. Thay đổi code

### 3.1 `GeneratedCaption` dataclass — thêm 2 fields

```python
@dataclass
class GeneratedCaption:
    thought_process: str   # NEW: internal reasoning
    insight: str           # NEW: contrarian hook
    headline: str
    body: str
    hashtags: List[str]
    cta: str
    full_caption: str
```

### 3.2 `CaptionGenerator._generate_via_llm()` — sửa prompt + parse

- Prompt mới với CoT instruction
- JSON parsing kiểm tra đủ 6 fields: `thought_process`, `insight`, `headline`, `body`, `cta`, `hashtags`
- Bỏ `for_tiktok()` / `for_facebook()` — `full_caption` là string đã format sẵn

### 3.3 Template fallback — REMOVED

Xóa `_generate_template()` path. Nếu LLM fail → raise exception ngay.

---

## 4. Error handling — STRICT (no defaults, no fallback)

**Nguyên tắc:** LLM generate phải trả đủ fields. Thiếu field = thất bại, không silence default.

1. **Thiếu field bất kỳ** → `CaptionGenerationError` raised, không dùng default
2. **JSON parse fail** → retry LLM 1 lần với cùng prompt, sau đó fail luôn
3. **Tất cả retry fail** → raise `CaptionGenerationError`, KHÔNG fallback sang template
4. **LLM unavailable** → raise `CaptionGenerationError` ngay, không template

**Rationale:** Caption tốt quan trọng hơn caption có mặt bằng mọi giá. Silence fallback tạo ra caption tầm thường mà không ai phát hiện.

```python
class CaptionGenerationError(Exception):
    """Raised when LLM caption generation fails after all retries."""
    pass
```

---

## 5. Retry logic

- **Max retries:** 1 lần cho JSON parse fail (sau lần đầu parse fail)
- **Retry strategy:** gọi lại LLM với cùng prompt (không sửa prompt giữa chừng)
- **Không retry timeout** — nếu LLM không respond thì fail luôn

---

## 6. Files to change

| File | Change |
|------|--------|
| `modules/content/caption_generator.py` | Prompt CoT mới, dataclass fields mới, strict error handling, bỏ template fallback |
| `modules/pipeline/exceptions.py` | Thêm `CaptionGenerationError` exception |
