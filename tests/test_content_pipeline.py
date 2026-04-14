"""
Tests for ContentPipeline - specifically CaptionGenerator integration.
"""
import pytest
from unittest.mock import patch, MagicMock
from modules.pipeline.models import ContentPipelineConfig


def test_caption_generator_integrated_in_produce_video():
    """CaptionGenerator should be called during video production to generate captions."""
    from modules.content.content_pipeline import ContentPipeline

    # Create a minimal config using the proper model
    cfg = ContentPipelineConfig(
        page={"facebook": {"page_id": "FB123"}, "tiktok": {"account_id": "TT456"}},
        content={"auto_schedule": False}
    )

    # Create a minimal config
    pipeline = ContentPipeline(
        project_id=1,
        config=cfg,
        dry_run=False,
        channel_id="nang_suat_thong_minh",
    )

    # Mock the script JSON that would come from DB
    mock_script = {
        "title": "Test Video Title",
        "scenes": [
            {"tts": "Xin chào các bạn"},
            {"tts": "Hôm nay chúng ta nói về năng suất"},
        ]
    }

    with patch("db.get_content_idea") as mock_get_idea:
        mock_get_idea.return_value = {"script_json": mock_script}

        with patch("modules.content.content_pipeline.CaptionGenerator") as MockCaptionGen:
            mock_cap_instance = MagicMock()
            mock_cap_instance.generate.return_value = MagicMock(
                for_facebook=lambda: "Facebook caption",
                for_tiktok=lambda: "TikTok caption",
            )
            MockCaptionGen.return_value = mock_cap_instance

            with patch.object(pipeline, "_save_script_config", return_value="/tmp/script.yaml"):
                # Mock the video pipeline to avoid actually running it
                with patch("scripts.video_pipeline_v3.VideoPipelineV3") as MockVP:
                    mock_vp_instance = MagicMock()
                    mock_vp_instance.run.return_value = True
                    mock_vp_instance._runner = MagicMock()
                    mock_vp_instance._runner.media_dir = MagicMock()
                    mock_vp_instance._runner.media_dir.glob.return_value = []
                    mock_vp_instance._runner.run_dir = MagicMock()
                    MockVP.return_value = mock_vp_instance

                    try:
                        result = pipeline.produce_video(idea_id=1)
                    except Exception as e:
                        # May fail due to missing config, but CaptionGenerator should be instantiated
                        pass

                    # Verify CaptionGenerator was used
                    assert MockCaptionGen.called, "CaptionGenerator was never instantiated - captions are not being generated in produce_video"


def test_produce_video_returns_captions():
    """produce_video should return captions in its result dict when video production succeeds."""
    from modules.content.content_pipeline import ContentPipeline
    from pathlib import Path

    # Create a minimal config using the proper model
    cfg = ContentPipelineConfig(
        page={"facebook": {"page_id": "FB123"}, "tiktok": {"account_id": "TT456"}},
        content={"auto_schedule": False}
    )

    pipeline = ContentPipeline(
        project_id=1,
        config=cfg,
        dry_run=False,
        channel_id="nang_suat_thong_minh",
    )

    mock_script = {
        "title": "Test Video Title",
        "scenes": [
            {"tts": "Xin chào các bạn"},
            {"tts": "Hôm nay chúng ta nói về năng suất"},
        ]
    }

    # Use a valid config path under the project root to avoid path resolution errors
    valid_config_path = str(pipeline.project_root / "configs" / "channels" / "nang_suat_thong_minh" / "scenarios" / "test_script.yaml")

    with patch("db.get_content_idea") as mock_get_idea:
        mock_get_idea.return_value = {"script_json": mock_script}

        with patch("modules.content.content_pipeline.CaptionGenerator") as MockCaptionGen:
            mock_cap_instance = MagicMock()
            mock_fb_caption = MagicMock()
            mock_fb_caption.for_facebook.return_value = "Facebook caption"
            mock_tt_caption = MagicMock()
            mock_tt_caption.for_tiktok.return_value = "TikTok caption"
            mock_cap_instance.generate.side_effect = [mock_fb_caption, mock_tt_caption]
            MockCaptionGen.return_value = mock_cap_instance

            with patch("scripts.video_pipeline_v3.VideoPipelineV3") as MockVP:
                mock_vp_instance = MagicMock()
                mock_vp_instance.run.return_value = True
                mock_vp_instance._runner = MagicMock()
                mock_vp_instance._runner.media_dir = MagicMock()
                mock_vp_instance._runner.media_dir.glob.return_value = []
                mock_vp_instance._runner.run_dir = MagicMock()
                MockVP.return_value = mock_vp_instance

                # Pass config_path directly to avoid _save_script_config being called
                result = pipeline.produce_video(idea_id=1, config_path=valid_config_path)

                # Check that result contains captions
                assert "captions" in result, \
                    f"produce_video result should contain captions key for social upload, got: {result.keys()}"
                assert result["captions"]["facebook"] is not None, \
                    "Facebook caption should be generated"
                assert result["captions"]["tiktok"] is not None, \
                    "TikTok caption should be generated"
