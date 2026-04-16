def test_pipeline_runner_completes_run_on_success():
    """VideoPipelineRunner should call db.complete_video_run() after successful pipeline."""
    from unittest.mock import patch, MagicMock
    from modules.pipeline.pipeline_runner import VideoPipelineRunner
    from modules.pipeline.models import (
        TechnicalConfig, GenerationConfig, GenerationLLM, GenerationTTS, GenerationImage,
        GenerationLipsync, GenerationSeeds, ParallelSceneConfig, APIKeys, APIURLs,
        GenerationModels, ObserverConfig, StorageConfig, S3Config, DatabaseConfig
    )
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_s3 = S3Config(
            endpoint="http://localhost:9000",
            access_key="test",
            secret_key="test",
            bucket="test",
            region="us-east-1",
            public_url_base="http://localhost:9000/test"
        )
        mock_db_cfg = DatabaseConfig(host="localhost", name="test", user="test", password="test")

        # Use real TechnicalConfig with temp directory
        tech_config = TechnicalConfig(
            api_keys=APIKeys(wavespeed="fake-ws", minimax="fake-key", kie_ai="fake-kie", you_search=""),
            api_urls=APIURLs(
                wavespeed="https://api.wavespeed.ai",
                minimax_tts="https://api.minimax.io/v1/t2a_v2",
                minimax_image="https://api.minimax.io/v1/image_generation",
                kie_ai="https://api.kie.ai/api/v1",
                tiktok="",
                facebook_graph=""
            ),
            models=GenerationModels(tts="edge", image="minimax"),
            generation=GenerationConfig(
                llm=GenerationLLM(),
                tts=GenerationTTS(model="speech-2.1-hd", sample_rate=32000, timeout=60, max_duration=15.0, min_duration=5.0, words_per_second=2.5, bitrate=128000, format="mp3", channel=1),
                image=GenerationImage(timeout=120),
                lipsync=GenerationLipsync(),
                seeds=GenerationSeeds(),
                parallel_scene_processing=ParallelSceneConfig(enabled=True, max_workers=3),
            ),
            storage=StorageConfig(
                output_dir=tmp_dir,
                temp_dir=None,
                s3=mock_s3,
                database=mock_db_cfg
            ),
            observer=ObserverConfig(host="localhost", port=8765, enabled=False),
        )

        ctx = MagicMock()
        ctx.channel_id = "test_channel"
        ctx.scenario.slug = "test-slug"
        ctx.scenario.title = "Test Scenario"
        ctx.scenario.scenes = []
        ctx.channel.background_music.enable = False
        ctx.channel.generation = MagicMock()
        ctx.channel.generation.models = MagicMock()
        ctx.channel.generation.models.tts = "edge"
        ctx.channel.generation.models.image = "minimax"
        ctx.channel.lipsync = None
        ctx.channel.watermark = None
        ctx.channel.subtitle = None
        ctx.channel.characters = []
        ctx.technical = tech_config

        with patch("modules.pipeline.pipeline_runner.db") as mock_db:
            mock_db.configure = MagicMock()
            mock_db.init_db = MagicMock()
            mock_db.get_or_create_project = MagicMock(return_value=1)
            mock_db.start_video_run = MagicMock(return_value=42)
            mock_db.complete_video_run = MagicMock()
            mock_db.fail_video_run = MagicMock()
            mock_db.mark_stale_runs_failed = MagicMock(return_value=0)

            runner = VideoPipelineRunner(ctx, dry_run=True)

            # Create a fake scene directory with video already processed (so it skips processing)
            fake_scene_dir = runner.run_dir / "scene_1"
            fake_scene_dir.mkdir(parents=True, exist_ok=True)
            with open(fake_scene_dir / "video_9x16.mp4", "w") as f:
                f.write("fake video content")
            with open(fake_scene_dir / "words_timestamps.json", "w") as f:
                f.write("[]")

            # Override scenario scenes to reference our fake scene
            mock_scene = MagicMock()
            mock_scene.id = 1
            mock_scene.tts = "Test script"
            mock_scene.script = "Test script"
            mock_scene.characters = ["speaker1"]
            ctx.scenario.scenes = [mock_scene]

            char_mock = MagicMock()
            char_mock.name = "speaker1"
            ctx.channel.characters = [char_mock]

            concat_output = runner.run_dir / "video_concat.mp4"
            with open(concat_output, "w") as f:
                f.write("concat video")
            final_video = runner.media_dir / f"video_v3_{runner.timestamp}.mp4"
            with open(final_video, "w") as f:
                f.write("final video")
            subtitled_video = runner.media_dir / f"video_v3_{runner.timestamp}_subtitled.mp4"
            with open(subtitled_video, "w") as f:
                f.write("subtitled video")

            with patch.object(runner.single_processor, 'process',
                              return_value=(str(fake_scene_dir / "video_9x16.mp4"), [])):
                runner.run()

            assert mock_db.complete_video_run.called, "complete_video_run was never called"
            call_args = mock_db.complete_video_run.call_args
            assert call_args[0][0] == 42, f"Expected run_id=42, got {call_args[0]}"

def test_pipeline_runner_fails_run_on_error():
    """VideoPipelineRunner should call db.fail_video_run() when pipeline raises."""
    from unittest.mock import patch, MagicMock
    from modules.pipeline.pipeline_runner import VideoPipelineRunner
    from modules.pipeline.models import (
        TechnicalConfig, GenerationConfig, GenerationLLM, GenerationTTS, GenerationImage,
        GenerationLipsync, GenerationSeeds, ParallelSceneConfig, APIKeys, APIURLs,
        GenerationModels, ObserverConfig, StorageConfig, S3Config, DatabaseConfig
    )
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_s3 = S3Config(
            endpoint="http://localhost:9000",
            access_key="test",
            secret_key="test",
            bucket="test",
            region="us-east-1",
            public_url_base="http://localhost:9000/test"
        )
        mock_db_cfg = DatabaseConfig(host="localhost", name="test", user="test", password="test")

        tech_config = TechnicalConfig(
            api_keys=APIKeys(wavespeed="fake-ws", minimax="fake-key", kie_ai="fake-kie", you_search=""),
            api_urls=APIURLs(
                wavespeed="https://api.wavespeed.ai",
                minimax_tts="https://api.minimax.io/v1/t2a_v2",
                minimax_image="https://api.minimax.io/v1/image_generation",
                kie_ai="https://api.kie.ai/api/v1",
                tiktok="",
                facebook_graph=""
            ),
            models=GenerationModels(tts="edge", image="minimax"),
            generation=GenerationConfig(
                llm=GenerationLLM(),
                tts=GenerationTTS(model="speech-2.1-hd", sample_rate=32000, timeout=60, max_duration=15.0, min_duration=5.0, words_per_second=2.5, bitrate=128000, format="mp3", channel=1),
                image=GenerationImage(timeout=120),
                lipsync=GenerationLipsync(),
                seeds=GenerationSeeds(),
                parallel_scene_processing=ParallelSceneConfig(enabled=True, max_workers=3),
            ),
            storage=StorageConfig(
                output_dir=tmp_dir,
                temp_dir=None,
                s3=mock_s3,
                database=mock_db_cfg
            ),
            observer=ObserverConfig(host="localhost", port=8765, enabled=False),
        )

        ctx = MagicMock()
        ctx.channel_id = "test_channel"
        ctx.scenario.slug = "test-slug"
        ctx.scenario.scenes = [MagicMock()]
        ctx.channel.background_music.enable = False
        ctx.channel.generation = MagicMock()
        ctx.channel.generation.models = MagicMock()
        ctx.channel.generation.models.tts = "edge"
        ctx.channel.generation.models.image = "minimax"
        ctx.channel.lipsync = None
        ctx.technical = tech_config

        with patch("modules.pipeline.pipeline_runner.db") as mock_db:
            mock_db.configure = MagicMock()
            mock_db.init_db = MagicMock()
            mock_db.get_or_create_project = MagicMock(return_value=1)
            mock_db.start_video_run = MagicMock(return_value=42)
            mock_db.complete_video_run = MagicMock()
            mock_db.fail_video_run = MagicMock()
            mock_db.mark_stale_runs_failed = MagicMock(return_value=0)

            runner = VideoPipelineRunner(ctx, dry_run=True)

            with patch.object(runner.single_processor, "process", side_effect=Exception("test error")):
                try:
                    runner.run()
                except Exception:
                    pass

            assert mock_db.fail_video_run.called, "fail_video_run was never called on error"

def test_pipeline_runner_wires_music_provider():
    """VideoPipelineRunner should pass music_provider to add_background_music."""
    from unittest.mock import MagicMock, patch
    from modules.pipeline.pipeline_runner import VideoPipelineRunner
    from modules.pipeline.models import (
        TechnicalConfig, GenerationConfig, GenerationLLM, GenerationTTS, GenerationImage,
        GenerationLipsync, GenerationSeeds, ParallelSceneConfig, APIKeys, APIURLs,
        GenerationModels, ObserverConfig, StorageConfig, S3Config, DatabaseConfig
    )
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_s3 = S3Config(
            endpoint="http://localhost:9000",
            access_key="test",
            secret_key="test",
            bucket="test",
            region="us-east-1",
            public_url_base="http://localhost:9000/test"
        )
        mock_db_cfg = DatabaseConfig(host="localhost", name="test", user="test", password="test")

        tech_config = TechnicalConfig(
            api_keys=APIKeys(wavespeed="fake-ws", minimax="fake-key", kie_ai="fake-kie", you_search=""),
            api_urls=APIURLs(
                wavespeed="https://api.wavespeed.ai",
                minimax_tts="https://api.minimax.io/v1/t2a_v2",
                minimax_image="https://api.minimax.io/v1/image_generation",
                kie_ai="https://api.kie.ai/api/v1",
                tiktok="",
                facebook_graph=""
            ),
            models=GenerationModels(tts="edge", image="minimax"),
            generation=GenerationConfig(
                llm=GenerationLLM(),
                tts=GenerationTTS(model="speech-2.1-hd", sample_rate=32000, timeout=60, max_duration=15.0, min_duration=5.0, words_per_second=2.5, bitrate=128000, format="mp3", channel=1),
                image=GenerationImage(timeout=120),
                lipsync=GenerationLipsync(),
                seeds=GenerationSeeds(),
                parallel_scene_processing=ParallelSceneConfig(enabled=True, max_workers=3),
            ),
            storage=StorageConfig(
                output_dir=tmp_dir,
                temp_dir=None,
                s3=mock_s3,
                database=mock_db_cfg
            ),
            observer=ObserverConfig(host="localhost", port=8765, enabled=False),
        )

        ctx = MagicMock()
        ctx.channel_id = "test_channel"
        ctx.scenario.slug = "test-slug"
        ctx.scenario.title = "Test Scenario"

        mock_scene = MagicMock()
        mock_scene.id = 1
        mock_scene.tts = "Test script for background music"
        mock_scene.script = "Test script for background music"
        mock_scene.characters = ["speaker1"]
        ctx.scenario.scenes = [mock_scene]

        ctx.channel = MagicMock()
        ctx.channel.background_music = MagicMock()
        ctx.channel.background_music.enable = True
        ctx.channel.generation = MagicMock()
        ctx.channel.generation.models = MagicMock()
        ctx.channel.generation.models.tts = "edge"
        ctx.channel.generation.models.image = "minimax"
        ctx.channel.lipsync = None
        ctx.channel.watermark = None
        ctx.channel.subtitle = None
        char_mock = MagicMock()
        char_mock.name = "speaker1"
        ctx.channel.characters = [char_mock]
        ctx.technical = tech_config

        with patch("modules.pipeline.pipeline_runner.MiniMaxMusicProvider") as MockProvider:
            mock_instance = MagicMock()
            mock_instance.generate.return_value = "/tmp/music.mp3"
            MockProvider.return_value = mock_instance

            with patch("modules.pipeline.pipeline_runner.db") as mock_db:
                mock_db.configure = MagicMock()
                mock_db.init_db = MagicMock()
                mock_db.get_or_create_project = MagicMock(return_value=1)
                mock_db.start_video_run = MagicMock(return_value=42)
                mock_db.complete_video_run = MagicMock()
                mock_db.fail_video_run = MagicMock()
                mock_db.mark_stale_runs_failed = MagicMock(return_value=0)

                runner = VideoPipelineRunner(ctx, dry_run=True)
                assert runner.music_provider is not None, "music_provider should be instantiated"
                assert isinstance(runner.music_provider, MagicMock), f"Expected MagicMock, got {type(runner.music_provider)}"

                fake_video_path = os.path.join(tmp_dir, "test_channel", "test-slug", str(runner.timestamp), "scene_1", "video_9x16.mp4")
                os.makedirs(os.path.dirname(fake_video_path), exist_ok=True)
                with open(fake_video_path, "w") as f:
                    f.write("fake video content")

                ts_path = os.path.join(tmp_dir, "test_channel", "test-slug", str(runner.timestamp), "scene_1", "words_timestamps.json")
                with open(ts_path, "w") as f:
                    f.write("[]")

                with patch.object(runner.single_processor, "process", return_value=(fake_video_path, [])):
                    run_dir_path = runner.run_dir
                    media_dir = runner.media_dir

                    with patch("modules.pipeline.pipeline_runner.concat_videos") as mock_concat:
                        concat_output = str(run_dir_path / "video_concat.mp4")
                        mock_concat.return_value = concat_output
                        os.makedirs(os.path.dirname(concat_output), exist_ok=True)
                        with open(concat_output, "w") as f:
                            f.write("concat video")

                        final_video = media_dir / f"video_v3_{runner.timestamp}.mp4"
                        os.makedirs(str(media_dir), exist_ok=True)
                        with open(str(final_video), "w") as f:
                            f.write("final video content")

                        subtitled_video = media_dir / f"video_v3_{runner.timestamp}_subtitled.mp4"
                        with open(str(subtitled_video), "w") as f:
                            f.write("subtitled video content")

                        with patch("shutil.copy"):
                            with patch("modules.pipeline.pipeline_runner.add_background_music") as mock_bgm:
                                output_video = media_dir / f"video_v3_{runner.timestamp}_with_music.mp4"
                                mock_bgm.return_value = str(output_video)
                                with open(str(output_video), "w") as f:
                                    f.write("output video")
                                try:
                                    runner.run()
                                except Exception as e:
                                    print(f"Exception during run: {e}")
                                for call in mock_bgm.call_args_list:
                                    if call.kwargs.get("music_provider") or (len(call.args) > 5 and isinstance(call.args[5], MagicMock)):
                                        return
                                assert False, "add_background_music never received music_provider"