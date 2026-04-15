# Spec: SRT Word Alignment — Script Words + Whisper Timestamps

## Problem

SRT subtitles are generated from Whisper word recognition, which can produce different words than the original scenario script (e.g., Whisper detects "tám mươi phần trăm" vs script has "80%").

This causes subtitles to be inaccurate relative to the intended script.

## Solution

After Whisper generates word timestamps, replace Whisper words with scenario script words when word count matches. Otherwise fall back to Whisper words.

## Algorithm

```
Input:
  - whisper_timestamps: List[Dict] — [{"word": "tám", "start": 0.0, "end": 0.3}, ...]
  - script_words: List[str]        — ["Bạn", "có", "biết", "80%", "nhân", ...]

Step 1: Count match
  M = len(script_words)
  N = len(whisper_timestamps)

Step 2: Align
  if M == N:
      // Perfect count match — replace Whisper words with script words, keep timestamps
      aligned = [{"word": script_words[i], "start": whisper_timestamps[i]["start"],
                  "end": whisper_timestamps[i]["end"]} for i in range(M)]
  else:
      // Count mismatch — fall back to Whisper words entirely
      aligned = whisper_timestamps

Step 3: Output aligned timestamps
```

## Where to implement

**`modules/pipeline/scene_processor.py`** — in `SingleCharSceneProcessor.process()` after Whisper timestamps are obtained (around line 274), before saving `words_timestamps.json`.

No changes to `pipeline_runner.py` — it already reads `words_timestamps.json` and merges across scenes.

## Implementation Details

### New function: `align_word_timestamps`

Location: `modules/pipeline/scene_processor.py` (near line 265, alongside `get_whisper_timestamps`)

```python
def align_word_timestamps(whisper_timestamps: List[Dict], script_words: List[str]) -> List[Dict]:
    """Replace Whisper words with script words when count matches.

    Args:
        whisper_timestamps: [{word, start, end}, ...] from Whisper
        script_words: [word, ...] from scenario script (already split)

    Returns:
        Aligned timestamps with script words + Whisper timestamps if count matches,
        otherwise original Whisper timestamps.
    """
    if not whisper_timestamps or not script_words:
        return whisper_timestamps

    n_whisper = len(whisper_timestamps)
    n_script = len(script_words)

    if n_whisper == n_script:
        return [
            {"word": script_words[i], "start": whisper_timestamps[i]["start"], "end": whisper_timestamps[i]["end"]}
            for i in range(n_whisper)
        ]
    else:
        return whisper_timestamps
```

### Changes to `SingleCharSceneProcessor.process()`

Around line 274, after Whisper returns timestamps:

```python
# Existing code:
word_timestamps = self.get_whisper_timestamps(str(audio_file), scene_output)

# Add after:
if word_timestamps:
    # Align Whisper words with script words when counts match
    tts_text = scene.tts or scene.script or ""
    script_words = tts_text.split()
    word_timestamps = align_word_timestamps(word_timestamps, script_words)
```

### Inputs available

- `scene.tts` or `scene.script` — already available in `process()`, used to build `tts_text`
- `word_timestamps` — from Whisper output

### Output

No change to output format. `words_timestamps.json` still saves `[{word, start, end}, ...]`. `pipeline_runner.py` combination logic unchanged.

## Scope

- Single scene alignment only — per-scene alignment before merge
- No LLM, no fuzzy matching — simple count comparison
- No changes to SRT generation (`generate_srt` in `subtitle_srt.py`)
- No changes to combination step in `pipeline_runner.py`

## Testing

- Unit test for `align_word_timestamps`:
  - M == N: words replaced, timestamps preserved
  - M != N: original Whisper timestamps returned
  - Empty inputs handled gracefully

## File changes

| File | Change |
|------|--------|
| `modules/pipeline/scene_processor.py` | Add `align_word_timestamps()`, call after Whisper |
| `tests/test_scene_processor.py` | Add tests for alignment function |