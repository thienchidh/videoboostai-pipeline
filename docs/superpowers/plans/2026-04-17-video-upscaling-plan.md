# Video Upscaling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add FFmpeg-based upscaling from ~480p to 2K (1920x3408) after video concatenation, using lanczos scale + unsharp + minterpolate filters for smoother, sharper output.

**Architecture:** New `upscale_video()` function in `core/video_utils.py`, called from `pipeline_runner.py` after `concat_videos()` and before `_add_watermark()`. Config-driven via `configs/technical/config_technical.yaml`.

**Tech Stack:** FFmpeg CLI via `get_ffmpeg()`, Python `subprocess`, no external Python packages.

---

## File Map

| File | Role |
|------|------|
| `configs/technical/config_technical.yaml` | Add `generation.video_upscale` config block |
| `core/video_utils.py` | Add `upscale_video()` function (new export) |
| `modules/pipeline/pipeline_runner.py` | Call `upscale_video()` after concat, before watermark |
| `tests/test_video_utils.py` | Add tests for `upscale_video()` |

---

## Task 1: Add config fields

**Files:**
- Modify: `configs/technical/config_technical.yaml:74-79`

- [ ] **Step 1: Add video_upscale config block**

After line 79 (`pipeline:` section closing), add:

```yaml
  video_upscale:
    enabled: true          # true | false — enable upscaling after concat
    crf: 18               # quality: lower = better quality, 18 = nearly lossless
    preset: "slow"        # encoding speed: slow = best compress, fast = quickest
    fps: 60               # target framerate for interpolation
```

- [ ] **Step 2: Commit**

```bash
git add configs/technical/config_technical.yaml
git commit -m "feat(config): add video_upscale settings for 480p→2K upscaling"
```

---

## Task 2: Add upscale_video() function

**Files:**
- Modify: `core/video_utils.py` — add new function

Read the end of `video_utils.py` to find where to append (look for the last function and add after it).

- [ ] **Step 1: Write the upscale_video() function**

Append this to `core/video_utils.py`:

```python
def upscale_video(input_path: str,
                  output_path: str,
                  crf: int = 18,
                  preset: str = "slow",
                  fps: int = 60) -> Optional[str]:
    """Upscale video from ~480p to 2K (1920x3408) using FFmpeg filters.

    Filter chain:
      - scale: 4x upscale with lanczos algorithm (sharpest available)
      - unsharp: light sharpen to enhance edges
      - minterpolate: motion-compensated interpolation to target fps

    Args:
        input_path: Path to input video (9:16, ~480p)
        output_path: Path to output video
        crf: CRF value (18=nearly lossless, 23=default)
        preset: FFmpeg encoding preset (slow=best compress, fast=quickest)
        fps: Target framerate for interpolation

    Returns:
        Output path on success, None on failure
    """
    scale_filter = "scale=1920:3408:flags=lanczos+accurate_rnd"
    sharpen_filter = "unsharp=5:5:0.5:5:5:0.0"
    interp_filter = f"minterpolate=fps={fps}:mi_mode=mci"
    vf = f"{scale_filter},{sharpen_filter},{interp_filter}"

    cmd = [
        get_ffmpeg(), "-y",
        "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path,
    ]

    logger.info(f"Upscaling video: CRF={crf}, preset={preset}, fps={fps}")
    logger.debug(f"FFmpeg upscale cmd: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(f"Upscale failed: {result.stderr}")
            return None
        logger.info(f"Upscale complete: {output_path}")
        return output_path
    except Exception as e:
        logger.warning(f"Upscale exception: {e}")
        return None
```

- [ ] **Step 2: Verify file still imports correctly**

Run: `python -c "from core.video_utils import upscale_video; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add core/video_utils.py
git commit -m "feat(video_utils): add upscale_video() for 480p→2K FFmpeg upscaling"
```

---

## Task 3: Integrate upscale into pipeline_runner

**Files:**
- Modify: `modules/pipeline/pipeline_runner.py:484-509`

- [ ] **Step 1: Find the insertion point**

Read lines 475-515 of `pipeline_runner.py`. The relevant section is:

```python
            # Line 484-485:
            shutil.copy(str(concat_output), str(final_video))
            log(f"  ✅ Concat copied: {final_video.stat().st_size/1024/1024:.1f}MB")

            # Lines 487-508: combined_timestamps building...
            # Lines 509+: subtitle saving...
```

- [ ] **Step 2: Insert upscale call after concat copy, before timestamp building**

Replace lines 484-486:
```python
            shutil.copy(str(concat_output), str(final_video))
            log(f"  ✅ Concat copied: {final_video.stat().st_size/1024/1024:.1f}MB")
```

With:
```python
            shutil.copy(str(concat_output), str(final_video))
            log(f"  ✅ Concat copied: {final_video.stat().st_size/1024/1024:.1f}MB")

            # Upscale video if enabled
            upscale_cfg = self.ctx.technical.generation.get("video_upscale")
            if upscale_cfg and upscale_cfg.get("enabled", False):
                upscaled = self.run_dir / "video_upscale.mp4"
                crf = upscale_cfg.get("crf", 18)
                preset = upscale_cfg.get("preset", "slow")
                fps = upscale_cfg.get("fps", 60)
                log(f"\n🔍 UPSCALING VIDEO: CRF={crf}, preset={preset}, fps={fps}")
                up_result = upscale_video(str(final_video), str(upscaled),
                                          crf=crf, preset=preset, fps=fps)
                if up_result and Path(up_result).exists():
                    shutil.copy(str(up_result), str(final_video))
                    log(f"  ✅ Upscale complete: {final_video.stat().st_size/1024/1024:.1f}MB")
                else:
                    log(f"  ⚠️  Upscale failed, continuing with original concat video")
```

- [ ] **Step 3: Verify syntax**

Run: `python -m py_compile modules/pipeline/pipeline_runner.py`
Expected: no output (no errors)

- [ ] **Step 4: Commit**

```bash
git add modules/pipeline/pipeline_runner.py
git commit -m "feat(pipeline): call upscale_video() after concat if enabled"
```

---

## Task 4: Add tests for upscale_video()

**Files:**
- Modify: `tests/test_video_utils.py`

- [ ] **Step 1: Read existing test file to understand patterns**

Run: `pytest tests/test_video_utils.py -v --collect-only 2>&1 | head -30`

- [ ] **Step 2: Write tests for upscale_video()**

Add to `tests/test_video_utils.py`:

```python
def test_upscale_video_success(tmp_path, monkeypatch):
    """Test upscale_video returns output path on success."""
    # Create a minimal valid MP4 (or use a fixture if available)
    input_video = tmp_path / "input.mp4"
    output_video = tmp_path / "output.mp4"

    # Mock subprocess to simulate success
    class MockResult:
        returncode = 0
        stderr = ""

    monkeypatch.setattr("core.video_utils.subprocess.run", lambda *a, **kw: MockResult())

    from core.video_utils import upscale_video
    result = upscale_video(str(input_video), str(output_video), crf=18, preset="fast", fps=30)
    assert result == str(output_video)


def test_upscale_video_failure_returns_none(tmp_path, monkeypatch):
    """Test upscale_video returns None when FFmpeg fails."""
    input_video = tmp_path / "input.mp4"
    output_video = tmp_path / "output.mp4"

    class MockResult:
        returncode = 1
        stderr = "Error: something failed"

    monkeypatch.setattr("core.video_utils.subprocess.run", lambda *a, **kw: MockResult())

    from core.video_utils import upscale_video
    result = upscale_video(str(input_video), str(output_video))
    assert result is None
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_video_utils.py -v -k "upscale" 2>&1`
Expected: both tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_video_utils.py
git commit -m "test: add upscale_video() tests"
```

---

## Self-Review Checklist

1. **Spec coverage:** Upscale config ✓, `upscale_video()` function ✓, pipeline integration ✓, tests ✓
2. **Placeholder scan:** No TBD/TODO in code — all filter values are explicit ✓
3. **Type consistency:** `upscale_video` signature matches call site in `pipeline_runner.py` (crf=int, preset=str, fps=int) ✓
4. **Config path:** `video_upscale` nested under `generation` matches `generation.lipsync` sibling structure ✓

## Execution Options

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks

**2. Inline Execution** — Execute tasks in this session using executing-plans

Which approach?
