# Video Message + Script Quality — Two-Step Generation

**Date:** 2026-04-16
**Status:** Approved
**Based on:** Brainstorming session 2026-04-16

---

## Problem Statement

Two issues in `ContentIdeaGenerator`:

1. **`video_message` is null** — LLM sometimes omits `video_message` from response JSON, even though the prompt asks for it.
2. **Scripts are all questions** — Scenes generated are hook-only questions with no answers. Viewer gets no value; content is engagement-bait rather than substantive.

---

## Goals

1. `video_message` must **never be null** in output YAML.
2. Every scene must **deliver concrete value** to the viewer (fact / technique / principle / proof). Scene 1 can be a hook with a partial answer, but no scene may be *only* questions.
3. Scene count is **dynamic** (2–5 scenes) based on topic depth, not hardcoded to 3.

---

## Architecture

### Two-Step Generation

```
generate_script_from_idea(idea)
  │
  ├── Step 1: _generate_video_message(idea)
  │     ├── LLM call #1 → returns {"video_message": "..."}
  │     └── video_message is NEVER None — required field
  │
  └── Step 2: _generate_scenes(idea, video_message)
        ├── LLM call #2 (video_message as mandatory context)
        └── Returns List[SceneConfig], each with scene_type + delivers
```

The `description` field (from research phase) is passed into **both** steps — it remains the source of factual content. LLM structures it via `video_message` in Step 2.

---

## Step 1: `_generate_video_message`

### Signature
```python
def _generate_video_message(self, title: str, keywords: List[str],
                            angle: str, description: str) -> str:
    """Returns non-null video_message string. Raises on failure."""
```

### Prompt
```
Bạn là CHIEF CONTENT STRATEGIST cho kênh TikTok/Reels tiếng Việt.

NHIỆM VỤ:
Xác định "video_message" — thông điệp MANG ĐI của viewer sau khi xem video.

QUY TẮC:
1. video_message phải là 1-2 câu, NGẮN GỌN, CÓ Ý NGHĨA RÕ RÀNG
2. KHÔNG generic — phải CỤ THỂ, có con số HOẶC promise rõ ràng
3. Phải có "hook" — điều bất ngờ, thách thức, hoặc specific claim
4. Dựa vào NỘI DUNG THAM KHẢO, không bịa

NỘI DUNG THAM KHẢO:
{title}
Keywords: {kw_list}
Content angle: {angle}
Description:
{description[:1500]}

VÍ DỤ TỐT:
- "Phương pháp 90-phút giúp deep work HIỆU QUẢ HƠN 40% so với Pomodoro"
- "Nguyên tắc Pareto 80/20 không phải lúc nào cũng đúng — đây là version CẢI TIẾN"
- "Đêm ngủ 8 tiếng là SAI — thực tế Olympic dùng phương pháp khác"

OUTPUT JSON:
{
  "video_message": "viết video_message ở đây"
}

CHỈ JSON, không markdown, KHÔNG THÊM GÌ KHÁC.
```

### Error Handling
- LLM returns invalid JSON → retry via tenacity
- LLM returns null/empty `video_message` → retry, raise after max attempts

---

## Step 2: `_generate_scenes`

### New Signature
```python
def _generate_scenes(self, title: str, keywords: List[str], angle: str,
                     description: str, num_scenes: int,
                     video_message: str) -> Tuple[List[SceneConfig], Optional[str]]:
```

The `video_message` is passed as a **mandatory parameter** and included in the prompt as context.

### Prompt
```
Bạn là CONTENT WRITER cho kênh TikTok/Reels tiếng Việt.

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

GIỚI HẠN: mỗi scene {tts.min_duration}-{tts.max_duration} giây ({int(tts.min_duration*2.5)}-{int(tts.max_duration*2.5)} từ)

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

OUTPUT JSON:
{
  "scenes": [
    {
      "id": 1,
      "scene_type": "hook",
      "script": "...",
      "character": "...",
      "delivers": "what viewer gets from this scene in 1 sentence",
      "creative_brief": {...},
      "image_prompt": "...",
      "lipsync_prompt": "..."
    },
    ...
  ]
}

CHỈ JSON object có "scenes" array, không markdown, không thêm field nào khác.
```

---

## Scene Type Definitions

| `scene_type` | Mục đích | Phải có gì |
|---|---|---|
| `hook` | Thu hút, đặt vấn đề | Câu hỏi **hoặc** provocative statement **có hint/trả lời một phần** |
| `insight` | Truyền tri thức | Fact / data / principle với con số cụ thể |
| `technique` | Hướng dẫn action | Step-by-step hoặc method rõ ràng |
| `proof` | Tăng credibility | Case study / research / example |
| `cta` | Kết thúc | Summary **hoặc** save/share/try hook |

---

## SceneConfig Changes

New optional fields (backward-compatible):

```python
class SceneConfig(BaseModel):
    # ... existing fields ...

    scene_type: Optional[str] = None   # hook | insight | technique | proof | cta
    delivers: Optional[str] = None      # plain-language summary of viewer takeaway
```

---

## Validation Rules

When parsing LLM response in `_parse_scenes`:

1. `scenes` array must have ≥ 2 scenes
2. Scene 1 must have `scene_type == "hook"`
3. Last scene must have `scene_type` in `["insight", "technique", "proof", "cta"]`
4. Each scene's `script` must not be only questions (>50% sentences ending in `?` → warn/flag)

---

## Data Flow

```
idea {
  title: "...",
  description: "...",       ← from research phase
  topic_keywords: [...],
  content_angle: "tips"
}

Step 1: _generate_video_message(title, keywords, angle, description)
  → LLM reads description + title
  → output: video_message (string, never null/empty)

Step 2: _generate_scenes(idea + video_message)
  → Prompt includes: description (source content) + video_message (mandatory context)
  → LLM writes 2-5 scenes, each with scene_type + delivers
  → output: List[SceneConfig]

Save to YAML:
  title
  video_message        ← NEVER null
  scenes[]             ← each delivers concrete value
```

---

## Error Handling

| Failure | Action |
|---|---|
| Step 1 LLM returns invalid JSON | retry via tenacity |
| Step 1 returns `video_message: null/empty` | retry, raise after max attempts |
| Step 2 LLM returns < 2 scenes | retry |
| Step 2 LLM scene is only questions | flag for regeneration |
| Step 2 LLM scene doesn't relate to `video_message` | flag for regeneration |

---

## Test Changes

New/updated tests:

| Test | Description |
|---|---|
| `test_generate_video_message_returns_non_null` | Mock LLM → verify non-null string returned |
| `test_generate_video_message_raises_on_empty` | Mock LLM returns empty → expect exception |
| `test_scene_1_is_hook_with_partial_answer` | Scene 1 has `scene_type == "hook"` and script implies answer |
| `test_all_scenes_deliver_concrete_value` | No scene is only questions; each has fact/technique/principle |
| `test_scene_count_dynamic` | Verify LLM can return 2–5 scenes (not fixed at 3) |
| `test_final_scene_has_cta_or_summary` | Last scene has `scene_type` in cta/proof/insight/technique |
| `test_generate_script_from_idea_includes_video_message` | Already exists → may need update for two-step flow |

---

## Implementation Notes

- `_generate_video_message` is called once before `_generate_scenes`
- `video_message` is stored in the output dict alongside scenes
- Retry logic (tenacity) is reused from existing `_generate_scenes` implementation
- No changes to `ContentIdeaGenerator.__init__` or public API signature (only internal `_generate_scenes` gains a parameter)
- `SceneConfig` model needs `scene_type` and `delivers` fields added