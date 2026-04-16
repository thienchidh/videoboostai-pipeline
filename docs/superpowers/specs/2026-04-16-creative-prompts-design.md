# Creative Prompts Pipeline Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** LLM tạo ra image_prompt và lipsync_prompt **thực sự sáng tạo, không lặp lại** — không cần thêm config thủ công. Variety đến từ creative process, không từ style pool.

**Architecture:** Two-phase generation — LLM tạo internal creative brief cho từng scene, rồi viết prompts từ brief. Few-shot examples + anti-patterns + diversity constraints đảm bảo variety.

---

## 1. Problem Statement

### Current State

LLM viết prompts theo template cứng:

```
Prompt: "A professional speaker in modern office, warm lighting, eye-level camera..."
→ Mọi scene đều y hệt, chỉ thay script content
```

ImageStyleConfig dùng single fixed values → prompts identical across scenes.

### Root Cause

LLM chỉ "assemble" từ fixed style fields, không có "creative space" để invent.

---

## 2. Design: Two-Phase Creative Generation

### Core Insight

Thay vì config thêm style fields, cho LLM **không gian để sáng tạo**. LLM tự quyết định visual concept, camera mood, emotion — dựa trên script content.

### Phase 1: Creative Brief (Internal → Stored)

LLM tạo vision/plan cho **mỗi scene** trước khi viết prompts:

```json
{
  "id": 1,
  "script": "Hãy bắt đầu với kế hoạch hôm nay...",
  "character": "NamMinh",
  "creative_brief": {
    "visual_concept": "Close-up khuôn mặt người đang suy nghĩ, có vẻ tập trung, ánh sáng tự nhiên từ cửa sổ",
    "emotion": "determined and inviting",
    "camera_mood": "shallow depth of field, intimate close-up",
    "setting_vibe": "quiet home office with natural elements",
    "unique_angle": "shooting from above desk, papers scattered",
    "action_description": "person looking directly at camera, slight nod while speaking"
  }
}
```

`creative_brief` được **lưu vào `scene_meta.json`** để debug và trace.

### Phase 2: Prompts from Brief

Từ creative_brief, LLM viết complete prompts:

```json
{
  "id": 1,
  "script": "Hãy bắt đầu với kế hoạch hôm nay...",
  "character": "NamMinh",
  "image_prompt": "Close-up of a young professional in deep thought, warm natural window light, shallow depth of field with soft bokeh, home office setting with plants in background, looking directly at camera with inviting determined expression, intimate cinematic feel, high quality 3D render style",
  "lipsync_prompt": "NamMinh speaking directly to camera with warm smile, slight nod on key words, measured thoughtful pace, occasional hand gesture toward planner, confident but approachable energy, Vietnamese language delivery"
}
```

---

## 3. Few-Shot Examples

Nhúng trực tiếp trong system prompt để LLM học cách viết creative briefs:

```
VÍ DỤ TỐT (học cách viết creative brief + prompts):

Input topic: "3 Tips Quản Lý Thời Gian"
Characters: NamMinh (female, vi-VN-NamMinhNeural), HoaiMy (female, vi-VN-HoaiMyNeural)

--- Scene 1 (Tip về lập kế hoạch) ---
creative_brief:
  visual_concept: "Close-up khuôn mặt tập trung, ánh sáng warm từ lamp"
  emotion: "serious but approachable"
  camera_mood: "shallow DOF, intimate close-up"
  setting_vibe: "home office with plants"
  unique_angle: "shooting from above desk, papers and planner visible"
  action_description: "speaking directly to camera, occasional hand gesture toward planner"

image_prompt: "Close-up of a focused young woman at a desk with planner and scattered papers, warm lamp light creating soft shadows, shallow depth of field with desk details in bokeh, home office with small plants, looking directly at camera with determined yet approachable expression, intimate cinematic feel, professional 3D render style"

lipsync_prompt: "NamMinh speaking directly to camera with warm inviting smile, slight nod on key words like 'planning' and 'important', occasional hand gesture toward planner, measured thoughtful pace, confident energy, Vietnamese language delivery"

--- Scene 2 (Tip về ưu tiên) ---
creative_brief:
  visual_concept: "Medium shot người đang cầm list, ánh sáng bright white"
  emotion: "energetic, motivated"
  camera_mood: "medium shot, eye-level, slightly high angle"
  setting_vibe: "clean minimalist workspace"
  unique_angle: "camera to the side, showing screen with task list"
  action_description: "pointing at list, engaging body language"

image_prompt: "Young professional woman pointing at a digital task list on screen, clean minimalist white workspace, bright diffused lighting from ceiling, medium shot eye-level with slightly high angle, engaged and energetic expression, professional 3D render style"

lipsync_prompt: "HoaiMy speaking with energetic enthusiasm, animated hand gestures pointing at list items, faster paced delivery with excitement on priority keywords, confident authoritative tone, Vietnamese language delivery"

--- Scene 3 (Tip về nghỉ ngơi) ---
creative_brief:
  visual_concept: "Relaxed shot người đang uống coffee, ánh sáng soft golden"
  emotion: "relaxed, balanced"
  camera_mood: "wide shot, lifestyle feel"
  setting_vibe: "cozy café corner with plants"
  unique_angle: "over-the-shoulder showing coffee cup"
  action_description: "relaxed posture, occasional sip, thoughtful pauses"

image_prompt: "Young woman relaxing with coffee cup, soft golden hour lighting from window, cozy café corner with plants and warm wooden elements, over-the-shoulder composition showing both face and coffee, relaxed balanced expression with slight smile, lifestyle photography feel, professional 3D render style"

lipsync_prompt: "NamMinh speaking in a relaxed slower pace, occasional sip of coffee between sentences, thoughtful pauses on key points, warm casual tone, gentle hand movements, peaceful balanced energy, Vietnamese language delivery"
```

---

## 4. Anti-Patterns

Explicitly banned trong system prompt:

```
TRÁNH CÁC PATTERN SAU — KHÔNG ĐƯỢC LẶP LẠI:
❌ "professional speaker in modern office" — DÙNG QUÁ NHIỀU, XÓA
❌ "warm lighting, eye-level camera" — QUÁ GENERIC, KHÔNG MÔ TẢ GÌ
❌ Mọi scene đều là người đứng nói chuyện trước camera
❌ Mọi scene đều có cùng background (office)
❌ "confident, knowledgeable" — adjectives TRỐNG, không có action
❌ "gesturing naturally" — quá mơ hồ
❌ Tất cả scenes đều có cùng camera angle (close-up)
❌ Prompt bắt đầu bằng "A person..." thay vì mô tả cụ thể
```

---

## 5. Diversity Constraints

Yêu cầu LLM cam kết khác biệt giữa các scenes:

```
MỖI SCENE PHẢI KHÁC NHAU — CAM KẾT TRƯỚC:
1. Scene N+1 phải có ÍT NHẤT 1 trong:
   - Camera angle khác (close-up ≠ medium ≠ wide)
   - Emotion khác (serious ≠ playful ≠ calm)
   - Setting khác (office ≠ café ≠ outdoor)

2. Không được dùng cùng lighting setup cho 2 scene liên tiếp
   (warm lamp → bright white → golden hour → soft blue)

3. Mỗi scene phải có "unique visual element" — detail nhỏ đặc biệt
   VD: "có sách stack trên bàn", "cây cảnh trong góc", "light leak từ cửa sổ"

4. Nếu script có emotion mạnh (excited, serious, funny) →
   camera_mood phải phản ánh đúng emotion đó
```

---

## 6. Changes to `content_idea_generator.py`

### `_build_scene_prompt()` — Updated system prompt

```python
def _build_scene_prompt(self, title, keywords, angle, description, num_scenes):
    # ... existing config reading ...

    return f"""Bạn là chuyên gia sản xuất video viral cho kênh "{cfg.name}".
Viết {num_scenes} scene với prompts SÁNG TẠO, KHÔNG LẶP LẠI.

{desc_line}{kw_line}Phong cách nội dung: {angle}{tts_context}

PHONG CÁCH KÊNH (brand tone):
{cfg.style}

NHÂN VẬT VÀ GIỌNG NÓI:
{char_list_str}

---

VÍ DỤ TỐT (học cách viết creative brief + prompts):
[... few-shot examples from Section 3 ...]

---

TRÁNH CÁC PATTERN SAU — KHÔNG ĐƯỢC LẶP LẠI:
[... anti-patterns from Section 4 ...]

---

MỖI SCENE PHẢI KHÁC NHAU — CAM KẾT TRƯỚC:
[... diversity constraints from Section 5 ...]

---

ĐỊNH DẠNG JSON OUTPUT:
[
  {{
    "id": 1,
    "script": "lời thoại TTS...",
    "character": "NamMinh",
    "creative_brief": {{
      "visual_concept": "mô tả ngắn gọn concept visual",
      "emotion": "mood chính của scene",
      "camera_mood": "camera angle + depth of field",
      "setting_vibe": "mô tả không gian/background",
      "unique_angle": "detail đặc biệt chỉ có scene này",
      "action_description": "mô tả body language, gesture"
    }},
    "image_prompt": "PROMPT HOÀN CHỈNH cho image gen, CHỨA creative_brief elements",
    "lipsync_prompt": "PROMPT HOÀN CHỈNH cho lipsync, CHỨA emotion + action + pace"
  }}
]

Trả về CHỈ JSON array, không kèm markdown."""
```

### `_parse_scenes()` — Parse creative_brief

```python
def _parse_scenes(self, text: str) -> List[Dict]:
    # ... existing JSON parsing ...
    return self._validate_scenes(scenes)

def _validate_scenes(self, scenes: List[Dict]) -> List[Dict]:
    for s in scenes:
        s["image_prompt"] = s.get("image_prompt") or None
        s["lipsync_prompt"] = s.get("lipsync_prompt") or None
        s["creative_brief"] = s.get("creative_brief") or None
    return scenes
```

---

## 7. Changes to `scene_processor.py`

### `scene_meta.json` — Store creative_brief

```python
# scene_processor.py:246-260
scene_meta = {
    "scene_id": scene_id,
    "scene_index": getattr(scene, 'scene_index', 0),
    "title": getattr(scene, 'title', None),
    "script": getattr(scene, 'script', None) or getattr(scene, 'tts', ''),
    "tts_text": getattr(scene, 'tts', '') or getattr(scene, 'script', ''),
    "characters": [c.name if hasattr(c, 'name') else str(c) for c in chars],
    "video_prompt": getattr(scene, 'video_prompt', None),
    "creative_brief": getattr(scene, 'creative_brief', None),  # NEW
    "created_at": datetime.now(timezone.utc).isoformat(),
}
```

---

## 8. Changes to `SceneConfig` (`models.py`)

```python
class SceneConfig(BaseModel):
    id: int = 0
    tts: Optional[str] = None
    script: Optional[str] = None
    characters: List["SceneCharacter | str"] = []
    video_prompt: Optional[str] = None
    background: Optional[str] = None
    image_prompt: Optional[str] = None
    lipsync_prompt: Optional[str] = None
    creative_brief: Optional[Dict[str, Any]] = None  # NEW
```

---

## 9. Validation Enhancement

### `PromptBuilder` — Validate creative_brief depth

```python
def validate_creative_brief(self, brief: Optional[Dict]) -> tuple[bool, list[str]]:
    """Check creative_brief has sufficient depth for variety."""
    if not brief:
        return False, ["creative_brief missing"]
    required_fields = ["visual_concept", "emotion", "camera_mood", "unique_angle"]
    violations = [f for f in required_fields if not brief.get(f)]
    return len(violations) == 0, violations
```

Called in `scene_processor.py`:
```python
brief = scene.creative_brief
if brief:
    is_valid, violations = prompt_builder.validate_creative_brief(brief)
    if not is_valid:
        log(f"  ⚠️ creative_brief shallow: {violations}")
```

---

## 10. Backward Compatibility

- `creative_brief` is optional — scenes without it still work (validation skipped)
- YAML scenarios without LLM-generated prompts: `scene.video_prompt` used as fallback
- `scene_meta.json` format: `creative_brief` field added, existing files still valid

---

## 11. Files Summary

| File | Change |
|------|--------|
| `modules/content/content_idea_generator.py` | Rewrite `_build_scene_prompt()` with 2-phase + few-shot + anti-patterns + diversity |
| `modules/pipeline/models.py` | Add `creative_brief: Optional[Dict]` to `SceneConfig` |
| `modules/pipeline/scene_processor.py` | Write `creative_brief` to `scene_meta.json` |
| `modules/media/prompt_builder.py` | Add `validate_creative_brief()` |
| `configs/channels/{channel}/config.yaml` | **No changes** |

---

## 12. No New Config Required

Vì LLM tự generate creative_brief từ:
- Script content (tự LLM quyết theo nội dung)
- Brand tone (từ channel config)
- Character voice info (từ channel config)
- Few-shot examples (hardcoded trong prompt)

→ Không cần thêm bất kỳ config key nào.

---

## 13. Testing

1. Generate 3-scene script → verify all 3 scenes have DIFFERENT creative_brief.camera_mood
2. Verify creative_brief stored in scene_meta.json
3. Verify image_prompt contains elements from creative_brief
4. Run 2 separate generations with same topic → prompts should differ
5. All existing tests pass
