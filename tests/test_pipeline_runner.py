def test_pipeline_runner_completes_run_on_success():
    """VideoPipelineRunner should call db.complete_video_run() after successful pipeline."""
    from unittest.mock import patch, MagicMock
    from modules.pipeline.pipeline_runner import VideoPipelineRunner
    import tempfile
    import os

    ctx = MagicMock()
    ctx.channel_id = "test_channel"
    ctx.scenario.slug = "test-slug"
    ctx.scenario.title = "Test Scenario"
    ctx.scenario.scenes = []  # Will be populated with a fake scene below
    ctx.channel.background_music.enable = False
    ctx.channel.generation = MagicMock()
    ctx.channel.generation.models = MagicMock()
    ctx.channel.generation.models.tts = "edge"
    ctx.channel.generation.models.image = "minimax"
    ctx.channel.lipsync = None
    ctx.channel.watermark = None
    ctx.channel.subtitle = None
    ctx.channel.characters = []
    ctx.technical.api_keys.minimax = "fake-key"
    ctx.technical.api_keys.kie_ai = "fake-kie"
    ctx.technical.api_keys.wavespeed = "fake-ws"
    ctx.technical.storage.s3.endpoint = "http://localhost:9000"
    ctx.technical.storage.s3.access_key = "test"
    ctx.technical.storage.s3.secret_key = "test"
    ctx.technical.storage.s3.bucket = "test"
    ctx.technical.storage.s3.region = "us-east-1"
    ctx.technical.storage.s3.public_url_base = "http://localhost:9000/test"
    ctx.technical.storage.database = None
    ctx.technical.generation = MagicMock()
    ctx.technical.generation.lipsync = MagicMock()
    ctx.technical.generation.lipsync.provider = "kieai"

    with patch("modules.pipeline.pipeline_runner.db") as mock_db:
        mock_db.configure = MagicMock()
        mock_db.init_db = MagicMock()
        mock_db.get_or_create_project = MagicMock(return_value=1)
        mock_db.start_video_run = MagicMock(return_value=42)
        mock_db.complete_video_run = MagicMock()
        mock_db.fail_video_run = MagicMock()

        with tempfile.TemporaryDirectory() as tmp_dir:
            ctx.technical.storage.local_output_dir = tmp_dir

            runner = VideoPipelineRunner(ctx, dry_run=True)

            # Create a fake scene directory with video already processed (so it skips processing)
            # The path must match what process_single_scene looks for: run_dir/scene_{id}/video_9x16.mp4
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

            # Also need to mock channel.characters to return a valid character
            char_mock = MagicMock()
            char_mock.name = "speaker1"
            ctx.channel.characters = [char_mock]

            # Also need to mock concat_videos to return a valid output
            concat_output = runner.run_dir / "video_concat.mp4"
            with open(concat_output, "w") as f:
                f.write("concat video")
            final_video = runner.media_dir / f"video_v3_{runner.timestamp}.mp4"
            with open(final_video, "w") as f:
                f.write("final video")
            subtitled_video = runner.media_dir / f"video_v3_{runner.timestamp}_subtitled.mp4"
            with open(subtitled_video, "w") as f:
                f.write("subtitled video")

            # Patch single_processor.process to return the fake video path directly
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

    ctx = MagicMock()
    ctx.channel_id = "test_channel"
    ctx.scenario.slug = "test-slug"
    ctx.scenario.scenes = [MagicMock()]  # Non-empty so it tries to process
    ctx.channel.background_music.enable = False
    ctx.channel.generation = MagicMock()
    ctx.channel.generation.models = MagicMock()
    ctx.channel.generation.models.tts = "edge"
    ctx.channel.generation.models.image = "minimax"
    ctx.channel.lipsync = None
    ctx.technical.api_keys.minimax = "fake-key"
    ctx.technical.api_keys.kie_ai = "fake-kie"
    ctx.technical.api_keys.wavespeed = "fake-ws"
    ctx.technical.storage.s3.endpoint = "http://localhost:9000"
    ctx.technical.storage.s3.access_key = "test"
    ctx.technical.storage.s3.secret_key = "test"
    ctx.technical.storage.s3.bucket = "test"
    ctx.technical.storage.s3.region = "us-east-1"
    ctx.technical.storage.s3.public_url_base = "http://localhost:9000/test"
    ctx.technical.storage.database = None
    ctx.technical.generation = MagicMock()
    ctx.technical.generation.lipsync = MagicMock()
    ctx.technical.generation.lipsync.provider = "kieai"

    with patch("modules.pipeline.pipeline_runner.db") as mock_db:
        mock_db.configure = MagicMock()
        mock_db.init_db = MagicMock()
        mock_db.get_or_create_project = MagicMock(return_value=1)
        mock_db.start_video_run = MagicMock(return_value=42)
        mock_db.complete_video_run = MagicMock()
        mock_db.fail_video_run = MagicMock()

        runner = VideoPipelineRunner(ctx, dry_run=True)

        # Force an error by making scene processing fail
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
    import tempfile
    import os

    ctx = MagicMock()
    ctx.channel_id = "test_channel"
    ctx.scenario.slug = "test-slug"
    ctx.scenario.title = "Test Scenario"

    # Set up a minimal scene structure with proper attributes
    mock_scene = MagicMock()
    mock_scene.id = 1
    mock_scene.tts = "Test script for background music"
    mock_scene.script = "Test script for background music"
    mock_scene.characters = ["speaker1"]
    ctx.scenario.scenes = [mock_scene]

    # Set up channel sub-object with background_music and generation models
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

    ctx.technical = MagicMock()
    ctx.technical.api_keys = MagicMock()
    ctx.technical.api_keys.minimax = "fake-key"
    ctx.technical.storage = MagicMock()
    ctx.technical.storage.s3 = MagicMock()
    ctx.technical.storage.s3.endpoint = "http://localhost:9000"
    ctx.technical.storage.s3.access_key = "test"
    ctx.technical.storage.s3.secret_key = "test"
    ctx.technical.storage.s3.bucket = "test"
    ctx.technical.storage.s3.region = "us-east-1"
    ctx.technical.storage.s3.public_url_base = "http://localhost:9000/test"
    ctx.technical.storage.database = None
    ctx.technical.generation = MagicMock()
    ctx.technical.generation.lipsync = MagicMock()
    ctx.technical.generation.lipsync.provider = "kieai"

    with patch("modules.pipeline.pipeline_runner.MiniMaxMusicProvider") as MockProvider:
        mock_instance = MagicMock()
        mock_instance.generate.return_value = "/tmp/music.mp3"
        MockProvider.return_value = mock_instance

        with patch("modules.pipeline.pipeline_runner.db") as mock_db:
            mock_db.configure = MagicMock()
            mock_db.init_db = MagicMock()
            mock_db.get_or_create_project = MagicMock(return_value=1)
            mock_db.start_video_run = MagicMock(return_value=42)

            # Create temp directory for test output
            with tempfile.TemporaryDirectory() as tmp_dir:
                ctx.technical.storage.local_output_dir = tmp_dir

                runner = VideoPipelineRunner(ctx, dry_run=True)
                # Verify music_provider is set
                assert runner.music_provider is not None, "music_provider should be instantiated"
                assert isinstance(runner.music_provider, MagicMock), f"Expected MagicMock, got {type(runner.music_provider)}"

                # Create fake video file that already exists to skip processing
                fake_video_path = os.path.join(tmp_dir, "test_channel", "test-slug", str(runner.timestamp), "scene_1", "video_9x16.mp4")
                os.makedirs(os.path.dirname(fake_video_path), exist_ok=True)
                with open(fake_video_path, "w") as f:
                    f.write("fake video content")

                # Also create timestamps file
                ts_path = os.path.join(tmp_dir, "test_channel", "test-slug", str(runner.timestamp), "scene_1", "words_timestamps.json")
                with open(ts_path, "w") as f:
                    f.write("[]")

                # Patch single_processor.process to return success (returns 2 values, process_single_scene adds tts_text)
                with patch.object(runner.single_processor, "process", return_value=(fake_video_path, [])):
                    # The run_dir is determined at init time based on PROJECT_ROOT
                    # We need to create files in the actual run_dir path
                    run_dir_path = runner.run_dir
                    media_dir = runner.media_dir

                    with patch("modules.pipeline.pipeline_runner.concat_videos") as mock_concat:
                        # concat_videos should return the path to concat_output
                        concat_output = str(run_dir_path / "video_concat.mp4")
                        mock_concat.return_value = concat_output
                        # Create the concat output file
                        os.makedirs(os.path.dirname(concat_output), exist_ok=True)
                        with open(concat_output, "w") as f:
                            f.write("concat video")

                        # Create the final_video in media_dir (this is the concat copied)
                        final_video = media_dir / f"video_v3_{runner.timestamp}.mp4"
                        os.makedirs(str(media_dir), exist_ok=True)
                        with open(str(final_video), "w") as f:
                            f.write("final video content")

                        # Create the subtitled video (this is what add_subtitles creates)
                        subtitled_video = media_dir / f"video_v3_{runner.timestamp}_subtitled.mp4"
                        with open(str(subtitled_video), "w") as f:
                            f.write("subtitled video content")

                        # Patch shutil.copy to avoid file not found issues
                        with patch("shutil.copy"):
                            # Verify add_background_music is called with music_provider
                            with patch("modules.pipeline.pipeline_runner.add_background_music") as mock_bgm:
                                output_video = media_dir / f"video_v3_{runner.timestamp}_with_music.mp4"
                                mock_bgm.return_value = str(output_video)
                                with open(str(output_video), "w") as f:
                                    f.write("output video")
                                try:
                                    runner.run()
                                except Exception as e:
                                    print(f"Exception during run: {e}")
                                # Check that add_background_music was called with music_provider kwarg or as positional arg > 5
                                for call in mock_bgm.call_args_list:
                                    if call.kwargs.get("music_provider") or (len(call.args) > 5 and isinstance(call.args[5], MagicMock)):
                                        return  # PASS if music_provider passed
                                # FAIL if music_provider was never passed
                                assert False, "add_background_music never received music_provider"