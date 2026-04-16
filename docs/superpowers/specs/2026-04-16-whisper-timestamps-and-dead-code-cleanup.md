# Whisper Timestamps Consolidation & Dead Code Cleanup

## Status

Draft.

## Context

Two separate issues were identified:

1. **Whisper timestamp logic is triplicated** across 3 locations:
   - `modules/media/tts.py`: standalone `get_whisper_timestamps()` function (also the most configurable — supports `config` param for timeout)
   - `modules/pipeline/scene_processor.py`: `SceneProcessor.get_whisper_timestamps()` method — duplicate of above
   - `modules/pipeline/parallel_processor.py`: `ParallelSceneProcessor._get_whisper_timestamps()` method — duplicate of above

   This caused the `--word_timestamps True` bug to need fixing in 3 places simultaneously.

2. **`ParallelSceneProcessor` is dead code**: never wired into `pipeline_runner.py` or any production entry point. `VideoPipelineRunner` uses only `SingleCharSceneProcessor`. The class exists only in `parallel_processor.py` and its tests.

3. **`retry_from_checkpoint.py` passes `parallel_scenes=True`** to `VideoPipelineRunner.__init__()`, but that parameter doesn't exist → dead code path.

## Goals

1. Single source of truth for Whisper timestamp extraction.
2. Remove dead `ParallelSceneProcessor` code (file + tests).
3. Remove dead `parallel_scenes` argument from `retry_from_checkpoint.py`.

---

## Item 1: Consolidate Whisper Timestamps

### Decision

Use `modules/media/tts.py::get_whisper_timestamps()` as the single source of truth. It is the most complete version (supports configurable `config` param) and is already in the right module (media).

### Changes

#### `modules/pipeline/scene_processor.py`

- Delete the `get_whisper_timestamps` method from `SceneProcessor` class.
- Import `get_whisper_timestamps` from `modules.media.tts` at the top.
- In `SingleCharSceneProcessor.get_whisper_timestamps()` (the call site at line ~414), replace the method call with a direct call to the imported function:
  ```python
  # Before (self.method call)
  word_timestamps = self.get_whisper_timestamps(str(audio_file), scene_output)
  # After (direct function call)
  word_timestamps = get_whisper_timestamps(str(audio_file), str(scene_output))
  ```

#### `modules/pipeline/parallel_processor.py` (will be deleted — see Item 2)

No changes needed; file will be deleted.

#### `modules/media/tts.py`

No changes needed; it already has the correct implementation with `--word_timestamps True`.

#### Import addition in `scene_processor.py`

Add to existing imports from `modules.media.tts`:
```python
from modules.media.tts import get_whisper_timestamps
```

Note: `tts.py`'s `get_whisper_timestamps` accepts `output_dir: Optional[str]`, while the method accepted `Optional[Path]`. The call site uses `str(scene_output)` so type conversion is handled at call site.

---

## Item 2: Delete `ParallelSceneProcessor`

### Files to delete

1. **`modules/pipeline/parallel_processor.py`** — entire file (dead code, never wired in)
2. **`tests/test_parallel_processor.py`** — entire file (tests the deleted class)

### Side effects

- `modules/pipeline/__init__.py` — check if it exports anything from `parallel_processor.py`, remove if so.
- `modules/pipeline/models.py` — `ParallelSceneConfig` model may still be referenced elsewhere. Check. If only used by deleted processor, consider removing but this is out of scope (keep for now).
- `scripts/retry_from_checkpoint.py` — remove `parallel_scenes=True` argument (dead).

---

## Item 3: Clean up `retry_from_checkpoint.py`

### Change

In `scripts/retry_from_checkpoint.py` line ~163:
```python
# Before
runner = VideoPipelineRunner(ctx, dry_run=dry_run, timestamp=..., parallel_scenes=True)
# After — remove parallel_scenes (parameter doesn't exist)
runner = VideoPipelineRunner(ctx, dry_run=dry_run, timestamp=...)
```

Also remove any comments referencing `parallel_scenes`.

---

## Files Changed Summary

| File | Action |
|------|--------|
| `modules/pipeline/scene_processor.py` | Import `get_whisper_timestamps` from tts; replace `self.get_whisper_timestamps()` method call with function call |
| `modules/pipeline/parallel_processor.py` | **DELETE** |
| `tests/test_parallel_processor.py` | **DELETE** |
| `scripts/retry_from_checkpoint.py` | Remove `parallel_scenes=True` argument |

## Verification

1. Run `pytest tests/test_scene_processor.py -v` — existing tests should pass.
2. `python -c "from modules.pipeline.scene_processor import SingleCharSceneProcessor"` — should import without error.
3. `python -c "from modules.pipeline.parallel_processor import ParallelSceneProcessor"` — should fail (file deleted).
4. Run pipeline at least once end-to-end to confirm whisper timestamps work.

## Dependencies

None — this is a cleanup/refactor with no new external dependencies.
