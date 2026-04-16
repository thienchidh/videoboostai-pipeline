# Whisper Timestamps Consolidation & Dead Code Cleanup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Single source of truth for Whisper timestamps; delete dead `ParallelSceneProcessor` code and `parallel_scenes` dead argument.

**Architecture:** Consolidate three `get_whisper_timestamps` implementations into one (`tts.py`), delete unused `ParallelSceneProcessor`, clean up dead `parallel_scenes` argument.

**Tech Stack:** Python, Whisper CLI, pytest

---

## Before You Start

Verify current state of the files you'll touch:

```bash
# Confirm parallel_processor.py exists
ls modules/pipeline/parallel_processor.py

# Confirm test_parallel_processor.py exists
ls tests/test_parallel_processor.py

# Check current imports in scene_processor.py line 33
sed -n '33p' modules/pipeline/scene_processor.py
```

---

## Task 1: Consolidate Whisper — modify scene_processor.py

**Files:**
- Modify: `modules/pipeline/scene_processor.py`

- [ ] **Step 1: Add import from tts.py**

Add to the imports section (around line 33, after the existing `from modules.media.prompt_builder` import):

```python
from modules.media.tts import get_whisper_timestamps
```

Run: `grep -n "from modules.media.tts" modules/pipeline/scene_processor.py`
Expected: shows the new import line

- [ ] **Step 2: Delete `get_whisper_timestamps` method from SceneProcessor class**

The method spans lines ~139–173. Delete the entire `get_whisper_timestamps` method definition (lines 139–173 inclusive).

The deleted code looks like:
```python
    def get_whisper_timestamps(self, audio_path: str, output_dir: Optional[Path] = None) -> Optional[List[Dict]]:
        """Get word timestamps from audio using Whisper."""
        if not Path(audio_path).exists():
            return None
        ...
        return None
```

To delete, replace lines 139–173 with a single blank line or just remove the block.

Run: `sed -n '139,173p' modules/pipeline/scene_processor.py` — should show the method body.
After: `sed -n '139p' modules/pipeline/scene_processor.py` should now be `def align_word_timestamps` or blank.

- [ ] **Step 3: Replace `self.get_whisper_timestamps(...)` with direct function call**

Line ~414 currently reads:
```python
word_timestamps = self.get_whisper_timestamps(str(audio_file), scene_output)
```

Change to:
```python
word_timestamps = get_whisper_timestamps(str(audio_file), str(scene_output))
```

Note: `scene_output` is a `Path` object; `tts.py`'s function takes `output_dir: Optional[str]`, so wrap with `str()`.

Run: `grep -n "get_whisper_timestamps" modules/pipeline/scene_processor.py`
Expected: only the call site at line ~414 (no method definition)

- [ ] **Step 4: Verify import works**

```bash
python -c "from modules.pipeline.scene_processor import SingleCharSceneProcessor; print('OK')"
```

Expected: prints "OK" with no errors

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/scene_processor.py
git commit -m "refactor: use get_whisper_timestamps from tts.py as single source of truth"
```

---

## Task 2: Delete ParallelSceneProcessor

**Files:**
- Delete: `modules/pipeline/parallel_processor.py`
- Delete: `tests/test_parallel_processor.py`

- [ ] **Step 1: Delete parallel_processor.py**

```bash
rm modules/pipeline/parallel_processor.py
ls modules/pipeline/parallel_processor.py
```
Expected: "No such file or directory"

- [ ] **Step 2: Delete test_parallel_processor.py**

```bash
rm tests/test_parallel_processor.py
ls tests/test_parallel_processor.py
```
Expected: "No such file or directory"

- [ ] **Step 3: Verify nothing imports the deleted module**

```bash
grep -rn "parallel_processor\|ParallelSceneProcessor" modules/ --include="*.py" 2>/dev/null
```
Expected: no output (nothing should reference the deleted module)

- [ ] **Step 4: Commit**

```bash
git add -A  # stages deletions
git commit -m "refactor: delete dead ParallelSceneProcessor (never wired into pipeline)"
```

---

## Task 3: Clean up parallel_scenes dead argument

**Files:**
- Modify: `scripts/retry_from_checkpoint.py`

- [ ] **Step 1: Find the parallel_scenes=True line**

```bash
grep -n "parallel_scenes" scripts/retry_from_checkpoint.py
```

Expected: shows `parallel_scenes=True` around line 163

- [ ] **Step 2: Read context lines 160–170**

```bash
sed -n '160,170p' scripts/retry_from_checkpoint.py
```

- [ ] **Step 3: Remove parallel_scenes=True from VideoPipelineRunner call**

The line currently reads (approximately):
```python
runner = VideoPipelineRunner(
    ctx,
    dry_run=dry_run,
    timestamp=int(run_dir.name.split("_")[0]) if run_dir.name[0].isdigit() else None,
    parallel_scenes=True,
)
```

Remove the `parallel_scenes=True,` line entirely.

After the edit, the call should be:
```python
runner = VideoPipelineRunner(
    ctx,
    dry_run=dry_run,
    timestamp=int(run_dir.name.split("_")[0]) if run_dir.name[0].isdigit() else None,
)
```

- [ ] **Step 4: Verify no more references to parallel_scenes**

```bash
grep -n "parallel_scenes" scripts/retry_from_checkpoint.py
```
Expected: no output

- [ ] **Step 5: Commit**

```bash
git add scripts/retry_from_checkpoint.py
git commit -m "fix: remove dead parallel_scenes=True argument (parameter does not exist)"
```

---

## Task 4: Final verification

- [ ] **Step 1: Run scene_processor tests**

```bash
pytest tests/test_scene_processor.py -v --tb=short 2>&1 | tail -20
```

Expected: existing tests pass (some pre-existing failures are unrelated to this change — Pydantic SceneCharacter validation)

- [ ] **Step 2: Confirm ParallelSceneProcessor is truly gone**

```bash
python -c "from modules.pipeline.parallel_processor import ParallelSceneProcessor"
```
Expected: `ModuleNotFoundError: No module named 'modules.pipeline.parallel_processor'`

- [ ] **Step 3: Confirm SingleCharSceneProcessor still imports fine**

```bash
python -c "from modules.pipeline.scene_processor import SingleCharSceneProcessor; print('OK')"
```
Expected: "OK"

- [ ] **Step 4: Push**

```bash
git push
```
