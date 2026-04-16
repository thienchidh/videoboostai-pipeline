# Fix CaptionGenerationError from MiniMax Thinking Blocks

Date: 2026-04-17
Author: Claude Code

## Problem

MiniMax M2.7 với extended thinking ENABLED trả về response với multiple content blocks — bao gồm cả `thinking` blocks (type == "thinking") và `text` blocks (type == "text").

`MiniMaxLLMProvider.chat()` hiện tại extract TẤT CẢ text blocks vào một string:

```python
for block in content:
    if block.get("type") == "text":
        text_parts.append(block.get("text", ""))
```

Khi thinking text bị trộn lẫn với JSON output, regex `\{.*\}` trong `CaptionGenerator._generate_via_llm()` có thể:
- Capture incomplete JSON (bị cắt giữa chừng ở log truncation)
- Capture thinking text làm confuse JSON structure

Result: `CaptionGenerationError: json_parse_error`

## Solution

### Fix 1: MiniMaxLLMProvider — Filter Thinking Blocks

**File:** `modules/llm/minimax.py`

**Change:** `chat()` method — skip `type == "thinking"` blocks, only collect `type == "text"` blocks.

```python
for block in content:
    if block.get("type") == "text":
        text_parts.append(block.get("text", ""))
    elif block.get("type") == "thinking":
        logger.debug("MiniMax thinking block skipped")
```

**Why at provider level:** All consumers of MiniMaxLLMProvider benefit automatically.

### Fix 2: CaptionGenerator — Final Retry with Cleaner Prompt

**File:** `modules/content/caption_generator.py`

**Change:** `_generate_via_llm()` — thêm final fallback attempt với cleaner system prompt khi JSON parse fail sau 2 attempts.

System prompt thêm final attempt suffix:
```
CRITICAL: Trả lời CHỈ có JSON hợp lệ. Không viết suy nghĩ, không viết gì khác ngoài JSON.
```

Retry flow:
- Attempt 1: Normal prompt → fail → retry
- Attempt 2: Normal prompt → fail → **retry with cleaner prompt**
- Still fail → raise CaptionGenerationError

### Fix 3: CaptionGenerator — Robust JSON Extraction (Optional Safety Net)

**File:** `modules/content/caption_generator.py`

**Change:** Cải thiện JSON extraction để handle truncated JSON:

```python
matches = re.findall(r'\{[^{}]*\}', response, re.DOTALL)
for m in matches:
    try:
        data = json.loads(m)
        # validate required fields...
        return data
    except json.JSONDecodeError:
        continue
```

**Note:** Có thể không cần thiết nếu Fix 1 đủ — chỉ implement nếu testing cho thấy còn edge cases.

## Data Flow

```
MiniMax API Response:
  content: [
    {"type": "text", "text": "Let me analyze..."},
    {"type": "thinking", "text": "Thinking about..."},
    {"type": "text", "text": "{"thought_process":..."}
  ]

MiniMaxLLMProvider.chat():
  text_parts = ["Let me analyze...", '{"thought_process":...}']
  → return "Let me analyze...{'thought_process':..."

CaptionGenerator._generate_via_llm():
  regex \{.*\} → matches full concatenated string
  → may capture incomplete JSON or thinking+JSON mix
  → json_parse_error
```

Fixed flow:
```
MiniMax API Response:
  content: [
    {"type": "text", "text": "Let me analyze..."},
    {"type": "thinking", "text": "Thinking about..."},
    {"type": "text", "text": "{"thought_process":..."}
  ]

MiniMaxLLMProvider.chat():
  text_parts = ["Let me analyze...", '{"thought_process":...}']
  thinking block skipped
  → return "Let me analyze...{'thought_process':..."

CaptionGenerator._generate_via_llm():
  regex \{.*\} → clean JSON capture
  → json.loads success
```

## Backwards Compatibility

- MiniMaxLLMProvider: Chỉ thay đổi internal extraction logic — interface không đổi
- CaptionGenerator: Retry logic mở rộng — existing behavior không thay đổi (chỉ thêm fallback)

## Testing

1. **Unit test: MiniMaxLLMProvider.chat() with thinking blocks**
   - Mock API response với 2 text blocks + 1 thinking block
   - Verify return string chỉ chứa text blocks

2. **Unit test: CaptionGenerator with incomplete JSON**
   - Mock LLM trả về response với incomplete JSON
   - Verify CaptionGenerationError raised sau exhausted retries

## Files to Modify

- `modules/llm/minimax.py` — Filter thinking blocks in `chat()`
- `modules/content/caption_generator.py` — Final retry with cleaner prompt + robust JSON extraction

## Status

Draft — pending implementation