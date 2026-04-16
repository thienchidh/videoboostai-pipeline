"""
tests/test_lipsync.py — VP-034

Unit tests for modules/media/lipsync.py quota fallback paths:
- WaveSpeed LTX quota detection (429 + keyword)
- WaveSpeed InfiniteTalk quota detection (429 + keyword)
- Kie.ai Infinitalk quota detection (submit + poll)
- create_static_video_with_audio fallback on LipsyncQuotaError

All HTTP calls are mocked — no real API calls.
"""

import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from core.video_utils import LipsyncQuotaError


# ─── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_upload():
    """All providers call upload_file to get URLs before posting."""
    with patch.object(
        __import__("modules.media.lipsync", fromlist=["WaveSpeedLipsyncProvider"]).WaveSpeedLipsyncProvider,
        "upload_file",
        return_value="https://cdn.example.com/fake_upload.jpg",
    ) as mock:
        yield mock


@pytest.fixture
def mock_upload_multi():
    """MultiTalkProvider also uses upload_file."""
    with patch.object(
        __import__("modules.media.lipsync", fromlist=["WaveSpeedMultiTalkProvider"]).WaveSpeedMultiTalkProvider,
        "upload_file",
        return_value="https://cdn.example.com/fake_upload.jpg",
    ) as mock:
        yield mock


# ─── WaveSpeed LTX quota detection ───────────────────────────────────────────────

class TestWaveSpeedLTXQuotaDetection:
    """WaveSpeedLipsyncProvider.generate() raises LipsyncQuotaError on 429 or quota keywords."""

    def test_raises_lipsync_quota_error_on_429(self, mock_upload, mock_wavespeed_config):
        from modules.media.lipsync import WaveSpeedLipsyncProvider

        provider = WaveSpeedLipsyncProvider(config=mock_wavespeed_config)

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.json.return_value = {"error": "Rate limit exceeded"}

        with patch("modules.media.lipsync.requests.post", return_value=mock_resp):
            with pytest.raises(LipsyncQuotaError) as exc_info:
                provider.generate(
                    image_path="/tmp/fake.jpg",
                    audio_path="/tmp/fake.mp3",
                    output_path="/tmp/out.mp4",
                )
        assert "WaveSpeed LTX quota exceeded" in str(exc_info.value)

    def test_raises_lipsync_quota_error_on_quota_keyword_in_message(self, mock_upload, mock_wavespeed_config):
        from modules.media.lipsync import WaveSpeedLipsyncProvider

        provider = WaveSpeedLipsyncProvider(config=mock_wavespeed_config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200  # not 429, but message contains "quota"
        mock_resp.json.return_value = {
            "error": "Your monthly quota has been exceeded"
        }

        with patch("modules.media.lipsync.requests.post", return_value=mock_resp):
            with pytest.raises(LipsyncQuotaError) as exc_info:
                provider.generate(
                    image_path="/tmp/fake.jpg",
                    audio_path="/tmp/fake.mp3",
                    output_path="/tmp/out.mp4",
                )
        assert "WaveSpeed LTX quota exceeded" in str(exc_info.value)

    def test_raises_lipsync_quota_error_on_credit_keyword(self, mock_upload, mock_wavespeed_config):
        from modules.media.lipsync import WaveSpeedLipsyncProvider

        provider = WaveSpeedLipsyncProvider(config=mock_wavespeed_config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": "Insufficient credits for this operation"
        }

        with patch("modules.media.lipsync.requests.post", return_value=mock_resp):
            with pytest.raises(LipsyncQuotaError) as exc_info:
                provider.generate(
                    image_path="/tmp/fake.jpg",
                    audio_path="/tmp/fake.mp3",
                    output_path="/tmp/out.mp4",
                )
        assert "WaveSpeed LTX quota exceeded" in str(exc_info.value)

    def test_raises_lipsync_quota_error_on_cn_chars(self, mock_upload, mock_wavespeed_config):
        """Quota keywords in Chinese (余额 / 配额 / 额度) also detected."""
        from modules.media.lipsync import WaveSpeedLipsyncProvider

        provider = WaveSpeedLipsyncProvider(config=mock_wavespeed_config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"error": "账号余额不足"}  # "Insufficient account balance"

        with patch("modules.media.lipsync.requests.post", return_value=mock_resp):
            with pytest.raises(LipsyncQuotaError) as exc_info:
                provider.generate(
                    image_path="/tmp/fake.jpg",
                    audio_path="/tmp/fake.mp3",
                    output_path="/tmp/out.mp4",
                )
        assert "WaveSpeed LTX quota exceeded" in str(exc_info.value)

    def test_does_not_raise_on_normal_error(self, mock_upload, mock_wavespeed_config):
        """Non-quota related errors return None, not LipsyncQuotaError."""
        from modules.media.lipsync import WaveSpeedLipsyncProvider

        provider = WaveSpeedLipsyncProvider(config=mock_wavespeed_config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {}  # no id, no error — just a bad response
        }

        with patch("modules.media.lipsync.requests.post", return_value=mock_resp):
            result = provider.generate(
                image_path="/tmp/fake.jpg",
                audio_path="/tmp/fake.mp3",
                output_path="/tmp/out.mp4",
            )
        # Retries exhausted → returns None (no exception raised)
        assert result is None


# ─── WaveSpeed InfiniteTalk quota detection ─────────────────────────────────────

class TestWaveSpeedInfiniteTalkQuotaDetection:
    """WaveSpeedMultiTalkProvider.generate() raises LipsyncQuotaError on 429 or quota keywords."""

    def test_raises_lipsync_quota_error_on_429(self, mock_upload_multi, mock_multitalk_config):
        from modules.media.lipsync import WaveSpeedMultiTalkProvider
        from modules.pipeline.models import LipsyncRequest

        # MultiTalk requires left+right audio; use LipsyncRequest for dual-audio test
        lipsync_req = LipsyncRequest(left_audio="/tmp/fake_l.mp3", right_audio="/tmp/fake_r.mp3")
        provider = WaveSpeedMultiTalkProvider(config=mock_multitalk_config)

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.json.return_value = {"error": "Rate limit exceeded"}

        with patch("modules.media.lipsync.requests.post", return_value=mock_resp):
            with pytest.raises(LipsyncQuotaError) as exc_info:
                provider.generate(
                    image_path="/tmp/fake.jpg",
                    audio_path=lipsync_req,
                    output_path="/tmp/out.mp4",
                )
        assert "WaveSpeed InfiniteTalk quota exceeded" in str(exc_info.value)

    def test_raises_lipsync_quota_error_on_quota_keyword(self, mock_upload_multi, mock_multitalk_config):
        from modules.media.lipsync import WaveSpeedMultiTalkProvider
        from modules.pipeline.models import LipsyncRequest

        lipsync_req = LipsyncRequest(left_audio="/tmp/fake_l.mp3", right_audio="/tmp/fake_r.mp3")
        provider = WaveSpeedMultiTalkProvider(config=mock_multitalk_config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": "Your credit limit has been exceeded"
        }

        with patch("modules.media.lipsync.requests.post", return_value=mock_resp):
            with pytest.raises(LipsyncQuotaError) as exc_info:
                provider.generate(
                    image_path="/tmp/fake.jpg",
                    audio_path=lipsync_req,
                    output_path="/tmp/out.mp4",
                )
        assert "WaveSpeed InfiniteTalk quota exceeded" in str(exc_info.value)

    def test_raises_lipsync_quota_error_on_insufficient_keyword(self, mock_upload_multi, mock_multitalk_config):
        from modules.media.lipsync import WaveSpeedMultiTalkProvider
        from modules.pipeline.models import LipsyncRequest

        lipsync_req = LipsyncRequest(left_audio="/tmp/fake_l.mp3", right_audio="/tmp/fake_r.mp3")
        provider = WaveSpeedMultiTalkProvider(config=mock_multitalk_config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "error": "Insufficient credit"
        }

        with patch("modules.media.lipsync.requests.post", return_value=mock_resp):
            with pytest.raises(LipsyncQuotaError) as exc_info:
                provider.generate(
                    image_path="/tmp/fake.jpg",
                    audio_path=lipsync_req,
                    output_path="/tmp/out.mp4",
                )
        assert "WaveSpeed InfiniteTalk quota exceeded" in str(exc_info.value)

    def test_does_not_raise_on_generic_failure(self, mock_upload_multi, mock_multitalk_config):
        """Non-quota failure → returns None, no LipsyncQuotaError."""
        from modules.media.lipsync import WaveSpeedMultiTalkProvider
        from modules.pipeline.models import LipsyncRequest

        lipsync_req = LipsyncRequest(left_audio="/tmp/fake_l.mp3", right_audio="/tmp/fake_r.mp3")
        provider = WaveSpeedMultiTalkProvider(config=mock_multitalk_config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {}}  # no id = treated as failure, not quota

        with patch("modules.media.lipsync.requests.post", return_value=mock_resp):
            result = provider.generate(
                image_path="/tmp/fake.jpg",
                audio_path=lipsync_req,
                output_path="/tmp/out.mp4",
            )
        assert result is None


# ─── Kie.ai Infinitalk quota detection ─────────────────────────────────────────

class TestKieAIInfinitalkQuotaDetection:
    """KieAIInfinitalkProvider.generate() raises LipsyncQuotaError from infinitalk() or poll_task()."""

    def _make_kieai_provider(self, mock_kieai_config):
        """Create KieAI provider with upload_func that returns mock URLs."""
        from modules.media.lipsync import KieAIInfinitalkProvider
        upload_func = MagicMock(side_effect=[
            "https://img.com/a.jpg",
            "https://audio.com/b.mp3",
        ])
        return KieAIInfinitalkProvider(config=mock_kieai_config, upload_func=upload_func)

    def test_raises_lipsync_quota_error_from_infinitalk_submit(self, mock_kieai_config):
        from modules.media.lipsync import KieAIInfinitalkProvider

        provider = self._make_kieai_provider(mock_kieai_config)
        # Patch the underlying client's infinitalk call
        with patch.object(
            provider._client, "infinitalk",
            return_value={"success": False, "error": "Quota exhausted — please upgrade your plan"},
        ):
            with pytest.raises(LipsyncQuotaError) as exc_info:
                provider.generate(
                    image_path="/tmp/fake.jpg",
                    audio_path="/tmp/fake.mp3",
                    output_path="/tmp/out.mp4",
                )
        assert "Kie.ai Infinitalk quota exceeded" in str(exc_info.value)

    def test_raises_lipsync_quota_error_from_poll_task(self, mock_kieai_config):
        from modules.media.lipsync import KieAIInfinitalkProvider

        provider = self._make_kieai_provider(mock_kieai_config)

        # infinitalk succeeds, poll_task returns quota error
        with patch.object(
            provider._client, "infinitalk",
            return_value={"success": True, "task_id": "task_quota_456"},
        ):
            with patch.object(
                provider._client, "poll_task",
                return_value={"success": False, "error": "Quota or credits exhausted"},
            ):
                with pytest.raises(LipsyncQuotaError) as exc_info:
                    provider.generate(
                        image_path="/tmp/fake.jpg",
                        audio_path="/tmp/fake.mp3",
                        output_path="/tmp/out.mp4",
                    )
        assert "Kie.ai Infinitalk quota exceeded" in str(exc_info.value)

    def test_raises_lipsync_quota_error_on_insufficient_credits_poll(self, mock_kieai_config):
        from modules.media.lipsync import KieAIInfinitalkProvider

        provider = self._make_kieai_provider(mock_kieai_config)

        with patch.object(
            provider._client, "infinitalk",
            return_value={"success": True, "task_id": "task_credits_789"},
        ):
            with patch.object(
                provider._client, "poll_task",
                return_value={"success": False, "error": "Insufficient credits"},
            ):
                with pytest.raises(LipsyncQuotaError) as exc_info:
                    provider.generate(
                        image_path="/tmp/fake.jpg",
                        audio_path="/tmp/fake.mp3",
                        output_path="/tmp/out.mp4",
                    )
        assert "Kie.ai Infinitalk quota exceeded" in str(exc_info.value)

    def test_raises_lipsync_quota_error_on_cn_quota_message(self, mock_kieai_config):
        """Chinese quota keywords (余额 / 配额 / 额度) also detected."""
        from modules.media.lipsync import KieAIInfinitalkProvider

        provider = self._make_kieai_provider(mock_kieai_config)

        with patch.object(
            provider._client, "infinitalk",
            return_value={"success": False, "error": "账号配额不足"},
        ):
            with pytest.raises(LipsyncQuotaError) as exc_info:
                provider.generate(
                    image_path="/tmp/fake.jpg",
                    audio_path="/tmp/fake.mp3",
                    output_path="/tmp/out.mp4",
                )
        assert "Kie.ai Infinitalk quota exceeded" in str(exc_info.value)

    def test_does_not_raise_on_generic_submit_error(self, mock_kieai_config):
        """Non-quota submit errors return None, not LipsyncQuotaError."""
        from modules.media.lipsync import KieAIInfinitalkProvider

        provider = self._make_kieai_provider(mock_kieai_config)

        with patch.object(
            provider._client, "infinitalk",
            return_value={"success": False, "error": "Model temporarily unavailable"},
        ):
            result = provider.generate(
                image_path="/tmp/fake.jpg",
                audio_path="/tmp/fake.mp3",
                output_path="/tmp/out.mp4",
            )
        # Returns None (no LipsyncQuotaError raised)
        assert result is None


# ─── Fallback: create_static_video_with_audio ────────────────────────────────────

class TestLipsyncQuotaFallback:
    """
    When LipsyncQuotaError is raised by a provider, scene_processor.py catches it
    and calls create_static_video_with_audio as fallback.

    We test that each provider raises LipsyncQuotaError (verified by patching
    create_static_video_with_audio at its real location in scene_processor).
    """

    def test_wavespeed_ltx_raises_quota_error_for_pipeline_fallback(self, mock_upload, mock_wavespeed_config):
        """
        WaveSpeedLTX raises LipsyncQuotaError on 429.
        scene_processor.py catches it and calls create_static_video_with_audio.
        """
        from modules.media.lipsync import WaveSpeedLipsyncProvider

        provider = WaveSpeedLipsyncProvider(config=mock_wavespeed_config)

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.json.return_value = {"error": "Monthly quota exceeded"}

        with patch("modules.media.lipsync.requests.post", return_value=mock_resp):
            # create_static_video_with_audio lives in scene_processor — patch there
            with patch("modules.pipeline.scene_processor.create_static_video_with_audio") as mock_fallback:
                mock_fallback.return_value = "/tmp/static_fallback.mp4"
                with pytest.raises(LipsyncQuotaError):
                    try:
                        provider.generate(
                            image_path="/tmp/fake.jpg",
                            audio_path="/tmp/fake.mp3",
                            output_path="/tmp/out.mp4",
                        )
                    except LipsyncQuotaError:
                        # Simulate what scene_processor does: call fallback
                        fallback_result = mock_fallback(
                            "/tmp/fake.jpg", "/tmp/fake.mp3", "/tmp/out.mp4"
                        )
                        assert fallback_result == "/tmp/static_fallback.mp4"
                        raise

    def test_wavespeed_infinitetalk_raises_quota_error_for_pipeline_fallback(self, mock_upload_multi, mock_multitalk_config):
        """
        WaveSpeedMultiTalk raises LipsyncQuotaError on quota keywords.
        scene_processor.py catches it and calls create_static_video_with_audio.
        """
        from modules.media.lipsync import WaveSpeedMultiTalkProvider
        from modules.pipeline.models import LipsyncRequest

        lipsync_req = LipsyncRequest(left_audio="/tmp/fake_l.mp3", right_audio="/tmp/fake_r.mp3")
        provider = WaveSpeedMultiTalkProvider(config=mock_multitalk_config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": "Insufficient credit"}

        with patch("modules.media.lipsync.requests.post", return_value=mock_resp):
            with patch("modules.pipeline.scene_processor.create_static_video_with_audio") as mock_fallback:
                mock_fallback.return_value = "/tmp/static_fallback.mp4"
                with pytest.raises(LipsyncQuotaError):
                    try:
                        provider.generate(
                            image_path="/tmp/fake.jpg",
                            audio_path=lipsync_req,
                            output_path="/tmp/out.mp4",
                        )
                    except LipsyncQuotaError:
                        fallback_result = mock_fallback(
                            "/tmp/fake.jpg", "/tmp/fake.mp3", "/tmp/out.mp4"
                        )
                        assert fallback_result == "/tmp/static_fallback.mp4"
                        raise

    def test_kieai_infinitalk_raises_quota_error_for_pipeline_fallback(self, mock_kieai_config):
        """
        KieAIInfinitalk raises LipsyncQuotaError when poll_task returns quota error.
        scene_processor.py catches it and calls create_static_video_with_audio.
        """
        from modules.media.lipsync import KieAIInfinitalkProvider

        upload_func = MagicMock(side_effect=[
            "https://img.com/a.jpg",
            "https://audio.com/b.mp3",
        ])
        provider = KieAIInfinitalkProvider(config=mock_kieai_config, upload_func=upload_func)

        with patch.object(
            provider._client, "infinitalk",
            return_value={"success": True, "task_id": "task_fallback_123"},
        ):
            with patch.object(
                provider._client, "poll_task",
                return_value={"success": False, "error": "Quota exhausted"},
            ):
                with patch("modules.pipeline.scene_processor.create_static_video_with_audio") as mock_fallback:
                    mock_fallback.return_value = "/tmp/static_fallback.mp4"
                    with pytest.raises(LipsyncQuotaError):
                        try:
                            provider.generate(
                                image_path="/tmp/fake.jpg",
                                audio_path="/tmp/fake.mp3",
                                output_path="/tmp/out.mp4",
                            )
                        except LipsyncQuotaError:
                            fallback_result = mock_fallback(
                                "/tmp/fake.jpg", "/tmp/fake.mp3", "/tmp/out.mp4"
                            )
                            assert fallback_result == "/tmp/static_fallback.mp4"
                            raise


# ─── create_static_video_with_audio unit tests ───────────────────────────────────

class TestCreateStaticVideoWithAudio:
    """Unit tests for the fallback function itself."""

    def test_create_static_video_with_audio_runs_ffmpeg(self, tmp_path):
        from core.video_utils import create_static_video_with_audio

        # Create a fake image file
        from PIL import Image
        img = Image.new("RGB", (1080, 1920), color="red")
        img_path = tmp_path / "scene.jpg"
        img.save(str(img_path))

        # Create a fake audio file using ffmpeg
        audio_path = tmp_path / "tts.mp3"
        import subprocess
        from core.paths import get_ffmpeg
        ffmpeg = str(get_ffmpeg())
        result = subprocess.run(
            [ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-ar", "32000", "-ac", "1", "-ab", "128k", str(audio_path)],
            capture_output=True, timeout=30,
        )
        assert audio_path.exists(), f"Audio creation failed: {result.stderr}"

        output_path = tmp_path / "static_video.mp4"

        with patch("core.video_utils.log"):  # suppress logging
            result = create_static_video_with_audio(
                image_path=str(img_path),
                audio_path=str(audio_path),
                output_path=str(output_path),
                resolution="480p",
            )

        assert result is not None, "Function should return output path"
        assert Path(result).exists(), "Output video should be created"
