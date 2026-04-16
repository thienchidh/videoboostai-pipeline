# Caption Thinking Blocks Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix CaptionGenerationError (json_parse_error) caused by MiniMax M2.7 thinking blocks polluting JSON extraction.

**Architecture:**
1. Filter `type == "thinking"` blocks in `MiniMaxLLMProvider.chat()` — only collect `type == "text"` blocks
2. Add final retry with cleaner system prompt in `CaptionGenerator._generate_via_llm()`

**Tech Stack:** Python, pytest, MiniMax LLM API (Anthropic-compatible)

---

## File Map

| File | Responsibility |
|------|----------------|
| `modules/llm/minimax.py` | MiniMax LLM provider — filter thinking blocks |
| `modules/content/caption_generator.py` | Caption generation with retry logic |

---

## Task 1: Filter Thinking Blocks in MiniMaxLLMProvider

**Files:**
- Modify: `modules/llm/minimax.py:94-104`

- [ ] **Step 1: Read the current implementation**

Read `modules/llm/minimax.py` lines 94-104 to confirm current text extraction logic.

- [ ] **Step 2: Write the failing test**

Create `tests/test_llm_minimax.py` with:

```python
import pytest
from modules.llm.minimax import MiniMaxLLMProvider

class TestMiniMaxLLMProvider:
    def test_chat_skips_thinking_blocks(self, monkeypatch):
        """chat() should skip type=='thinking' blocks and only collect type=='text' blocks."""
        provider = MiniMaxLLMProvider(api_key="test-key")

        # Mock the session.post to return a response with thinking + text blocks
        mock_response = pytest.importorskip("requests").Response()
        mock_response._content = b'{
            "content": [
                {"type": "text", "text": "Let me analyze..."},
                {"type": "thinking", "text": "Thinking step 1: analyzing..."},
                {"type": "thinking", "text": "Thinking step 2: deciding..."},
                {"type": "text", "text": "Final answer JSON here"}
            ]
        }'
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None

        def mock_post(*args, **kwargs):
            return mock_response

        monkeypatch.setattr(provider._session, "post", mock_post)

        result = provider.chat("test prompt")
        assert "Let me analyze" in result
        assert "Thinking step" not in result
        assert "Final answer JSON here" in result
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_llm_minimax.py::TestMiniMaxLLMProvider::test_chat_skips_thinking_blocks -v`
Expected: FAIL (thinking blocks currently included)

- [ ] **Step 4: Implement the fix**

Modify `modules/llm/minimax.py` at lines 94-104, change:

```python
        # Strip thinking/reasoning blocks that MiniMax sometimes includes
        content = data.get("content", [])
        if isinstance(content, list) and content:
            text_parts = []
            for block in content:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            if text_parts:
                return "".join(text_parts)
        return ""
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_llm_minimax.py::TestMiniMaxLLMProvider::test_chat_skips_thinking_blocks -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_llm_minimax.py modules/llm/minimax.py
git commit -m "$(cat <<'EOF'
feat(llm): filter thinking blocks in MiniMaxLLMProvider.chat()

MiniMax M2.7 with extended thinking returns type=="thinking" blocks
mixed with type=="text" blocks. Only collect text blocks to prevent
thinking content from polluting downstream JSON parsing.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Final Retry with Cleaner Prompt in CaptionGenerator

**Files:**
- Modify: `modules/content/caption_generator.py:141-222`

- [ ] **Step 1: Read the current implementation**

Read `modules/content/caption_generator.py` lines 141-222 to confirm retry loop structure.

- [ ] **Step 2: Write the failing test**

Create `tests/test_caption_generator.py` with:

```python
import pytest
from unittest.mock import MagicMock
from modules.content.caption_generator import CaptionGenerator, CaptionGenerationError

class TestCaptionGeneratorRetry:
    def test_final_retry_with_cleaner_prompt_on_json_error(self):
        """After 2 failed attempts, should retry with cleaner prompt that strips thinking."""
        gen = CaptionGenerator(llm_provider=MagicMock())

        # Track calls to llm.chat
        calls = []
        def mock_chat(user, system=None, max_tokens=None):
            calls.append({"user": user, "system": system})
            if len(calls) < 3:
                # First 2 attempts: return thinking+broken JSON mix
                return "Let me analyze...\n{invalid json}"
            else:
                # 3rd attempt (cleaner prompt): return clean JSON
                return '{"thought_process": "test", "insight": "hook", "headline": "test", "body": "body", "cta": "cta", "hashtags": ["#a", "#b", "#c"]}'

        gen._llm.chat = mock_chat

        # This should NOT raise — final retry with cleaner prompt succeeds
        result = gen.generate("test script", platform="facebook")
        assert result.insight == "hook"

        # Verify: 3 attempts total (2 normal + 1 cleaner prompt)
        assert len(calls) == 3
        assert "JSON" in calls[2]["system"] or "không" in calls[2]["system"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_caption_generator.py::TestCaptionGeneratorRetry::test_final_retry_with_cleaner_prompt_on_json_error -v`
Expected: FAIL (cleaner prompt retry not yet implemented)

- [ ] **Step 4: Implement the fix**

Modify `modules/content/caption_generator.py` lines 141-222, update the retry loop:

```python
        # Retry logic: 1 normal retry + 1 final retry with cleaner prompt
        last_error = None
        cleaner_prompt_suffix = (
            "\n\nCRITICAL: Trả lời CHỈ có JSON hợp lệ. "
            "Không viết suy nghĩ, không viết gì khác ngoài JSON."
        )
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
                # ... field validation (unchanged) ...
                # ... return GeneratedCaption (unchanged) ...

            except CaptionGenerationError as e:
                if attempt == 0 and e.reason == "json_parse_error":
                    last_error = e.original_error
                    continue  # Retry
                raise
            except Exception as e:
                last_error = e
                continue  # Retry

        # Final fallback: retry with cleaner prompt (attempt 2 failed)
        try:
            cleaner_system = system + cleaner_prompt_suffix
            response = self._llm.chat(user, system=cleaner_system, max_tokens=1200)
            m = re.search(r'\{.*\}', response, re.DOTALL)
            if not m:
                raise CaptionGenerationError(
                    "json_parse_error",
                    ValueError(f"No JSON found in cleaner prompt response: {response[:100]}")
                )
            data = json.loads(m.group())
            # ... field validation (unchanged) ...
            # ... return GeneratedCaption (unchanged) ...
        except Exception as final_error:
            raise CaptionGenerationError(
                "json_parse_error",
                final_error or ValueError("Unknown error after cleaner prompt retry")
            )
```

**Note:** Refactor the field validation + return logic into a helper method `_parse_caption_json(data, platform)` to avoid duplication across attempts.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_caption_generator.py::TestCaptionGeneratorRetry::test_final_retry_with_cleaner_prompt_on_json_error -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add modules/content/caption_generator.py
git commit -m "$(cat <<'EOF'
feat(caption): add final retry with cleaner prompt on JSON parse error

When normal retry (2 attempts) fails due to json_parse_error, retry
a third time with cleaner system prompt asking for JSON-only output.
This handles cases where thinking blocks still leak into response.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Verification

After both tasks complete:

```bash
# Run all caption + LLM tests
pytest tests/test_llm_minimax.py tests/test_caption_generator.py -v

# Manual integration test (if API key available)
python -c "
from modules.content.caption_generator import CaptionGenerator
gen = CaptionGenerator()
print(gen.generate('Hải sản là nguồn dinh dưỡng tuyệt vời.', 'facebook'))
"
```

Expected: All tests pass; caption generation succeeds without json_parse_error.

---

## Spec Coverage Check

- [x] Filter thinking blocks at MiniMaxLLMProvider — Task 1
- [x] Final retry with cleaner prompt — Task 2
- [x] Backwards compatible (interface unchanged) — both tasks
- [x] Unit tests — both tasks

## Status

Ready for implementation