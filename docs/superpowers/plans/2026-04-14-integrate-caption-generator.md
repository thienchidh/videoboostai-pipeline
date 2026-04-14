# Integrate CaptionGenerator into Pipeline & Save Caption Files

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `CaptionGenerator` into `SocialPublisher.upload_to_socials()` so it generates platform-specific TikTok/Facebook captions from the script, saves `caption_tiktok.txt` and `caption_facebook.txt` to the run's output folder, and passes the formatted captions to publishers instead of raw script text.

**Architecture:** Minimal changes to `publisher.py` only. Derive the output folder from the `video_path` argument (video is at e.g. `output/{channel_id}/{slug}_{timestamp}/final/video_v3_{ts}.mp4`, so caption files go alongside at `output/{channel_id}/{slug}_{timestamp}/caption_tiktok.txt`). No changes to `pipeline_runner.py` or scene processor.

**Tech Stack:** Python, `modules.content.caption_generator.CaptionGenerator`, standard library `pathlib`.

---

## File Structure

| File | Change |
|------|--------|
| `modules/pipeline/publisher.py` | Modify: add `CaptionGenerator` import, refactor `upload_to_socials()` to generate + save captions, pass formatted captions to FB/TT publishers |
| `tests/modules/pipeline/test_publisher.py` | Create: test `SocialPublisher` with mocked `CaptionGenerator`, verify correct caption files written and correct strings passed to publishers |

---

## Preconditions

- `CaptionGenerator` is already fully implemented and does NOT need changes
- `GeneratedCaption.for_tiktok()` and `GeneratedCaption.for_facebook()` already return correctly formatted strings
- Output folder already exists (created by `pipeline_runner.py`) before `upload_to_socials()` is called

---

## Mock Strategy

Mock `FacebookPublisher.publish()` and `TikTokPublisher.publish()` at the `SocialPublisher` level — mock the publisher instances directly, not the underlying HTTP calls.

---

## Task 1: Write the failing test for `SocialPublisher` caption integration

**Files:**
- Create: `tests/modules/pipeline/test_publisher.py`
- Modify: `modules/pipeline/publisher.py`

- [ ] **Step 1: Create test file**

```python
# tests/modules/pipeline/test_publisher.py
import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from modules.pipeline.publisher import SocialPublisher
from modules.pipeline.models import SocialConfig
from modules.content.caption_generator import GeneratedCaption


@pytest.fixture
def mock_social_config():
    """Minimal SocialConfig for testing — platforms present but not is_configured."""
    cfg = MagicMock(spec=SocialConfig)
    cfg.facebook = MagicMock()
    cfg.facebook.is_configured = False
    cfg.tiktok = MagicMock()
    cfg.tiktok.is_configured = False
    return cfg


@pytest.fixture
def mock_caption():
    """Sample GeneratedCaption for mocking."""
    return GeneratedCaption(
        headline="Bí kíp năng suất",
        body="Làm việc hiệu quả hơn mỗi ngày.",
        hashtags=["#nangsuat", "#thoigian", "#motivation"],
        cta="Follow để không bỏ lỡ!",
        full_caption="🔥 Bí kíp năng suất\nLàm việc hiệu quả hơn mỗi ngày.\nFollow để không bỏ lỡ!\n#nangsuat #thoigian #motivation",
    )


class TestUploadToSocialsWithCaptions:
    def test_saves_tiktok_and_facebook_caption_files(self, mock_social_config, mock_caption):
        """Caption files are written to the run output folder alongside the video."""
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "final" / "video_v3_123.mp4"
            video_path.parent.mkdir(parents=True)
            video_path.write_text("fake video content")

            with patch("modules.pipeline.publisher.CaptionGenerator") as MockCapGen:
                mock_gen_instance = MockCapGen.return_value
                mock_gen_instance.generate.return_value = mock_caption

                publisher = SocialPublisher(mock_social_config, dry_run=False)
                result = publisher.upload_to_socials(str(video_path), script="Test script content")

                # CaptionGenerator should have been called with the script
                mock_gen_instance.generate.assert_any_call("Test script content", platform="tiktok")
                mock_gen_instance.generate.assert_any_call("Test script content", platform="facebook")

                # Caption files should exist alongside the video
                expected_tiktok = video_path.parent.parent / "caption_tiktok.txt"
                expected_facebook = video_path.parent.parent / "caption_facebook.txt"

                assert expected_tiktok.exists(), f"caption_tiktok.txt not found at {expected_tiktok}"
                assert expected_facebook.exists(), f"caption_facebook.txt not found at {expected_facebook}"

                tiktok_content = expected_tiktok.read_text(encoding="utf-8")
                fb_content = expected_facebook.read_text(encoding="utf-8")

                assert "🔥 Bí kíp năng suất" in tiktok_content
                assert "**Bí kíp năng suất**" in fb_content

    def test_passes_formatted_captions_to_publishers(self, mock_social_config, mock_caption):
        """Publishers receive for_tiktok()/for_facebook() output, not raw script."""
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "final" / "video_v3_123.mp4"
            video_path.parent.mkdir(parents=True)
            video_path.write_text("fake video")

            # Make publishers appear configured so they get called
            mock_social_config.facebook.is_configured = True
            mock_social_config.tiktok.is_configured = True

            with patch("modules.pipeline.publisher.CaptionGenerator") as MockCapGen:
                mock_gen_instance = MockCapGen.return_value
                mock_gen_instance.generate.return_value = mock_caption

                with patch.object(publisher.fb_publisher, "publish", MagicMock(return_value=None)) as mock_fb:
                    with patch.object(publisher.tt_publisher, "publish", MagicMock(return_value=None)) as mock_tt:
                        publisher = SocialPublisher(mock_social_config, dry_run=False)
                        publisher.upload_to_socials(str(video_path), script="Raw script")

                        # Check FB got the Facebook-formatted caption
                        fb_call_kwargs = mock_fb.call_args[1]
                        assert fb_call_kwargs["title"] == "Raw script"  # title still raw script
                        # description should be formatted
                        assert "**Bí kíp năng suất**" in fb_call_kwargs["description"]

                        # Check TikTok got the TikTok-formatted caption
                        tt_call_kwargs = mock_tt.call_args[1]
                        assert tt_call_kwargs["title"] == "Raw script"  # title still raw script
                        assert "🔥 Bí kíp năng suất" in tt_call_kwargs["description"]

    def test_derive_output_folder_from_video_path(self, mock_social_config, mock_caption):
        """Caption files land in output/{channel_id}/{slug_timestamp}/, not inside /final/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "output" / "nang_suat_thong_minh" / "my-scenario_1713000000" / "final" / "video_v3_1713000000.mp4"
            video_path.parent.mkdir(parents=True)
            video_path.write_text("fake")

            with patch("modules.pipeline.publisher.CaptionGenerator") as MockCapGen:
                MockCapGen.return_value.generate.return_value = mock_caption

                publisher = SocialPublisher(mock_social_config, dry_run=False)
                publisher.upload_to_socials(str(video_path), script="script")

                run_dir = video_path.parent.parent  # .../my-scenario_1713000000
                assert (run_dir / "caption_tiktok.txt").exists()
                assert (run_dir / "caption_facebook.txt").exists()
                # Nothing should be saved inside /final/
                assert not (video_path.parent / "caption_tiktok.txt").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/pipeline/test_publisher.py -v`
Expected: FAIL — `modules.pipeline.publisher` has no `CaptionGenerator` imported

- [ ] **Step 3: Implement the minimal changes in `modules/pipeline/publisher.py`**

Add the import at the top of the file:

```python
from modules.content.caption_generator import CaptionGenerator, GeneratedCaption
```

Refactor `upload_to_socials()` in `SocialPublisher`. Replace the method body (lines 52–109) with:

```python
    def upload_to_socials(self, video_path: str, script: str = "",
                          word_timestamps: list = None,
                          srt_output_name: str = None) -> PublishResult:
        """
        Upload video to all configured social platforms.

        Args:
            video_path: Path to the final video file
            script: Video script/title for caption
            word_timestamps: Word timestamps for SRT generation (unused for now)
            srt_output_name: Base name for SRT file (unused for now)

        Returns:
            PublishResult with per-platform results
        """
        results = []

        # Derive run output folder from video_path:
        # video_path ends with .../{channel_id}/{slug_timestamp}/final/video_v3_{ts}.mp4
        # → run_dir is .../{channel_id}/{slug_timestamp}/
        video_path_obj = Path(video_path)
        run_dir = video_path_obj.parent.parent  # up from /final/

        # Generate platform-specific captions
        capgen = CaptionGenerator(use_llm=False)
        tiktok_caption: GeneratedCaption = capgen.generate(script, platform="tiktok")
        facebook_caption: GeneratedCaption = capgen.generate(script, platform="facebook")

        # Save caption files to run output folder
        tiktok_caption_file = run_dir / "caption_tiktok.txt"
        facebook_caption_file = run_dir / "caption_facebook.txt"
        tiktok_caption_file.write_text(tiktok_caption.for_tiktok(), encoding="utf-8")
        facebook_caption_file.write_text(facebook_caption.for_facebook(), encoding="utf-8")

        if self.dry_run:
            logger.info("[SOCIAL] Dry-run mode - would upload to:")
            if self.fb_publisher.is_configured:
                logger.info(f"  Facebook: {video_path}")
            if self.tt_publisher.is_configured:
                logger.info(f"  TikTok: {video_path}")
            results.append({"platform": "facebook", "success": True, "dry_run": True})
            results.append({"platform": "tiktok", "success": True, "dry_run": True})
            return PublishResult(results)

        # Facebook
        if self.fb_publisher.is_configured:
            fb_result = self.fb_publisher.publish(
                video_path=video_path,
                title=script[:255] if script else "Video from NangSuatThongMinh",
                description=facebook_caption.for_facebook(),
            )
            results.append({
                "platform": "facebook",
                "success": fb_result is not None,
                "post_url": fb_result,
            })
        else:
            results.append({"platform": "facebook", "success": False, "error": "not configured"})

        # TikTok
        if self.tt_publisher.is_configured:
            tt_result = self.tt_publisher.publish(
                video_path=video_path,
                title=script[:100] if script else "Video from NangSuatThongMinh",
                description=tiktok_caption.for_tiktok(),
            )
            results.append({
                "platform": "tiktok",
                "success": tt_result is not None,
                "post_url": tt_result,
            })
        else:
            results.append({"platform": "tiktok", "success": False, "error": "not configured"})

        return PublishResult(results)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/modules/pipeline/test_publisher.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/modules/pipeline/test_publisher.py modules/pipeline/publisher.py
git commit -m "feat: integrate CaptionGenerator into SocialPublisher — generate and save platform-specific captions alongside video output"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - Generate TikTok caption ✓ (`capgen.generate(script, "tiktok")`)
   - Generate Facebook caption ✓ (`capgen.generate(script, "facebook")`)
   - Save `caption_tiktok.txt` to run folder ✓
   - Save `caption_facebook.txt` to run folder ✓
   - Pass formatted captions to publishers ✓ (used in `description=` arg)
   - Derive output folder from `video_path` ✓ (`video_path_obj.parent.parent`)

2. **Placeholder scan:** No "TBD", "TODO", "handle edge cases" or vague steps. All steps show actual code.

3. **Type consistency:**
   - `CaptionGenerator(use_llm=False)` — matches `modules/content/caption_generator.py:122` signature
   - `capgen.generate(script, platform="tiktok")` — matches `caption_generator.py:292` signature
   - `tiktok_caption.for_tiktok()` — method exists on `GeneratedCaption` at line 39
   - `facebook_caption.for_facebook()` — method exists at line 50
   - `Path.write_text(..., encoding="utf-8")` — standard pathlib API

4. **Output folder derivation:** `video_path` is always `.../{channel_id}/{slug_timestamp}/final/video_v3_{ts}.mp4` (set in `pipeline_runner.py` line 391 and 437). `.parent` → `/final/`, `.parent.parent` → run folder. Correct.

5. **`use_llm=False`:** Since `CaptionGenerator._check_ollama()` tries to reach localhost:11434 and `use_llm=False` disables LLM entirely, always using template fallback is the safe default for pipeline runs. LLM can be re-enabled per-run if ollama is available.
