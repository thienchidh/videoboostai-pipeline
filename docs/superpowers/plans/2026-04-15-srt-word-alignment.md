# SRT Word Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `align_word_timestamps()` function that replaces Whisper words with scenario script words when word count matches, keeping Whisper timestamps for timing accuracy.

**Architecture:** Per-scene alignment in `scene_processor.py` after Whisper returns timestamps. Combined timestamps from all scenes flow into `pipeline_runner.py` unchanged (no changes needed there).

**Tech Stack:** Python, no new dependencies.

---

## File Structure

- `modules/pipeline/scene_processor.py` — add `align_word_timestamps()` function, call it after Whisper in `process()`
- `tests/test_scene_processor.py` — add `TestAlignWordTimestamps` class with tests

---

## Implementation Plan

### Task 1: Write failing tests for `align_word_timestamps`

**Files:**
- Modify: `tests/test_scene_processor.py`

- [ ] **Step 1: Add `TestAlignWordTimestamps` class with 3 failing tests**

Add at end of `tests/test_scene_processor.py`:

```python
class TestAlignWordTimestamps:
    """Tests for align_word_timestamps function."""

    def test_count_match_replaces_words_keeps_timestamps(self):
        """When whisper and script word counts match, replace words, keep timestamps."""
        from modules.pipeline.scene_processor import align_word_timestamps

        whisper = [
            {"word": "tám", "start": 0.0, "end": 0.3},
            {"word": "mươi", "start": 0.3, "end": 0.6},
            {"word": "phần", "start": 0.6, "end": 0.9},
            {"word": "trăm", "start": 0.9, "end": 1.2},
        ]
        script_words = ["80%", "nhân", "viên", "tự"]

        result = align_word_timestamps(whisper, script_words)

        assert result[0]["word"] == "80%"
        assert result[1]["word"] == "nhân"
        assert result[2]["word"] == "viên"
        assert result[3]["word"] == "tự"
        # Timestamps preserved
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 0.3
        assert result[3]["start"] == 0.9
        assert result[3]["end"] == 1.2

    def test_count_mismatch_returns_whisper_intact(self):
        """When word counts differ, return original Whisper timestamps unchanged."""
        from modules.pipeline.scene_processor import align_word_timestamps

        whisper = [
            {"word": "tám", "start": 0.0, "end": 0.3},
            {"word": "mươi", "start": 0.3, "end": 0.6},
        ]
        script_words = ["80%", "nhân", "viên", "tự", "nhận"]  # 5 words vs 2

        result = align_word_timestamps(whisper, script_words)

        assert result == whisper
        assert result[0]["word"] == "tám"
        assert result[1]["word"] == "mươi"

    def test_empty_whisper_returns_empty(self):
        """Empty Whisper timestamps returns empty list."""
        from modules.pipeline.scene_processor import align_word_timestamps

        result = align_word_timestamps([], ["word"])
        assert result == []

    def test_empty_script_returns_whisper(self):
        """Empty script words returns Whisper timestamps unchanged."""
        from modules.pipeline.scene_processor import align_word_timestamps

        whisper = [{"word": "tám", "start": 0.0, "end": 0.3}]
        result = align_word_timestamps(whisper, [])
        assert result == whisper
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scene_processor.py::TestAlignWordTimestamps -v`
Expected: FAIL — `align_word_timestamps` not defined

- [ ] **Step 3: Commit**

```bash
git add tests/test_scene_processor.py
git commit -m "test(scene_processor): add tests for align_word_timestamps

Tests cover:
- Count match: words replaced, timestamps preserved
- Count mismatch: original Whisper timestamps returned
- Empty inputs handled gracefully

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
"
```

---

### Task 2: Implement `align_word_timestamps` function

**Files:**
- Modify: `modules/pipeline/scene_processor.py:265-288`

- [ ] **Step 1: Add `align_word_timestamps` function after `get_whisper_timestamps`**

Read lines 255–310 to find the exact insertion point (after `get_whisper_timestamps`, before `# ==================== REGISTER PROVIDERS`):

```python
def align_word_timestamps(whisper_timestamps: List[Dict], script_words: List[str]) -> List[Dict]:
    """Replace Whisper words with script words when count matches.

    Args:
        whisper_timestamps: [{"word": "...", "start": 0.0, "end": 0.5}, ...] from Whisper
        script_words: [word, ...] from scenario script (already split by whitespace)

    Returns:
        Aligned timestamps with script words + Whisper timestamps if count matches,
        otherwise original Whisper timestamps unchanged.
    """
    if not whisper_timestamps:
        return whisper_timestamps
    if not script_words:
        return whisper_timestamps

    n_whisper = len(whisper_timestamps)
    n_script = len(script_words)

    if n_whisper == n_script:
        return [
            {
                "word": script_words[i],
                "start": whisper_timestamps[i]["start"],
                "end": whisper_timestamps[i]["end"]
            }
            for i in range(n_whisper)
        ]
    else:
        return whisper_timestamps
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_scene_processor.py::TestAlignWordTimestamps -v`
Expected: PASS (all 4 tests)

- [ ] **Step 3: Commit**

```bash
git add modules/pipeline/scene_processor.py
git commit -m "feat(scene_processor): add align_word_timestamps function

Replace Whisper words with script words when word counts match,
preserving Whisper timestamps for timing accuracy. Falls back to
original Whisper timestamps on count mismatch.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
"
```

---

### Task 3: Call `align_word_timestamps` in `process()` after Whisper

**Files:**
- Modify: `modules/pipeline/scene_processor.py:273-279`

- [ ] **Step 1: Find the Whisper block and add alignment call**

The Whisper block in `SingleCharSceneProcessor.process()` is around line 273–279:

```python
        if not word_timestamps:
            word_timestamps = self.get_whisper_timestamps(str(audio_file), scene_output)
        if word_timestamps:
            ts_file = scene_output / "words_timestamps.json"
            with open(ts_file, "w", encoding="utf-8") as f:
                json.dump(word_timestamps, f, ensure_ascii=False)
            log(f"  📝 Saved {len(word_timestamps)} word timestamps")
```

Replace it with:

```python
        if not word_timestamps:
            word_timestamps = self.get_whisper_timestamps(str(audio_file), scene_output)
        if word_timestamps:
            # Align Whisper words with script words when counts match
            script_words = tts_text.split()
            word_timestamps = align_word_timestamps(word_timestamps, script_words)
            ts_file = scene_output / "words_timestamps.json"
            with open(ts_file, "w", encoding="utf-8") as f:
                json.dump(word_timestamps, f, ensure_ascii=False)
            log(f"  📝 Saved {len(word_timestamps)} word timestamps (aligned)")
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `pytest tests/test_scene_processor.py -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add modules/pipeline/scene_processor.py
git commit -m "feat(scene_processor): call align_word_timestamps after Whisper

Align Whisper word timestamps with scenario script words right after
Whisper returns timestamps, before saving words_timestamps.json.
Logs "(aligned)" suffix when alignment was applied.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
"
```

---

## Verification

After all tasks complete, run:
```bash
pytest tests/test_scene_processor.py -v
```

All tests should pass.

**Files changed:**
- `modules/pipeline/scene_processor.py` — 1 function added, 1 call added in `process()`
- `tests/test_scene_processor.py` — 1 test class (4 tests)

**Spec reference:** `docs/superpowers/specs/2026-04-15-srt-word-alignment-design.md`