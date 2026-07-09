import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts import assemble_video
from scripts import generate_episode_from_text
from scripts import generate_video_clips_replicate
from scripts import generate_voiceover
from scripts import make_video
from scripts import publish_videos_official
from scripts import tiktok_oauth_setup
from scripts import meta_oauth_setup
from scripts import publish_videos
from scripts.generate_srt import (
    format_timestamp,
    make_srt_blocks,
    make_voiceover_srt_blocks,
    split_voiceover_lines,
    wrap_caption,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class EpisodeProjectTests(unittest.TestCase):
    def test_publish_videos_loads_metadata_rows_and_resolves_video_paths(self):
        with TemporaryDirectory() as temp_dir:
            videos_dir = Path(temp_dir) / "videos"
            videos_dir.mkdir()
            video_path = videos_dir / "clip1.mp4"
            video_path.write_bytes(b"fake video")
            metadata_path = videos_dir / "metadata.csv"
            metadata_path.write_text(
                "platform,title,description,hashtags,file_path,scheduled_time\n"
                "youtube,My Short,Short description,#ai #story,clip1.mp4,2026-07-08T10:00:00-04:00\n",
                encoding="utf-8",
            )

            rows = publish_videos.load_metadata(metadata_path, videos_dir)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].platform, "youtube")
        self.assertEqual(rows[0].video_path, video_path)
        self.assertEqual(rows[0].content, "Short description\n\n#ai #story")

    def test_publish_videos_rejects_password_style_metadata_columns(self):
        with TemporaryDirectory() as temp_dir:
            videos_dir = Path(temp_dir) / "videos"
            videos_dir.mkdir()
            metadata_path = videos_dir / "metadata.csv"
            metadata_path.write_text(
                "platform,title,description,hashtags,file_path,scheduled_time,password\n"
                "tiktok,Title,Description,#tag,clip.mp4,2026-07-08T10:00:00Z,secret\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "password"):
                publish_videos.load_metadata(metadata_path, videos_dir)

    def test_publish_videos_dry_run_previews_without_calling_postiz(self):
        with TemporaryDirectory() as temp_dir:
            videos_dir = Path(temp_dir) / "videos"
            videos_dir.mkdir()
            video_path = videos_dir / "clip1.mp4"
            video_path.write_bytes(b"fake video")
            metadata_path = videos_dir / "metadata.csv"
            metadata_path.write_text(
                "platform,title,description,hashtags,file_path,scheduled_time\n"
                "instagram,Reel Title,Description,#reel,clip1.mp4,2026-07-08T10:00:00Z\n",
                encoding="utf-8",
            )
            client = unittest.mock.Mock()

            result = publish_videos.run_workflow(metadata_path, videos_dir, dry_run=True, client=client)

        self.assertEqual(result.failed, 0)
        self.assertEqual(result.previewed, 1)
        client.schedule_video.assert_not_called()

    def test_publish_videos_builds_postiz_payload_for_youtube_short(self):
        row = publish_videos.PublishRow(
            platform="youtube",
            title="A Sharp Hook",
            description="Watch this short.",
            hashtags="#ai #story",
            video_path=Path("clip.mp4"),
            scheduled_time="2026-07-08T14:00:00Z",
        )

        payload = publish_videos.build_post_payload(
            row,
            integration_id="youtube-integration",
            media={"id": "media-id", "path": "https://uploads.postiz.com/clip.mp4"},
        )

        self.assertEqual(payload["type"], "schedule")
        self.assertEqual(payload["date"], "2026-07-08T14:00:00Z")
        post = payload["posts"][0]
        self.assertEqual(post["integration"]["id"], "youtube-integration")
        self.assertEqual(post["value"][0]["image"][0]["id"], "media-id")
        self.assertEqual(post["settings"]["__type"], "youtube")
        self.assertEqual(post["settings"]["title"], "A Sharp Hook")
        self.assertEqual(post["settings"]["tags"], ["ai", "story"])

    def test_publish_videos_resolves_integration_from_environment_first(self):
        with patch.dict("os.environ", {"POSTIZ_TIKTOK_INTEGRATION_ID": "explicit-tiktok"}, clear=True):
            integration = publish_videos.resolve_integration(
                "tiktok",
                [{"id": "wrong", "identifier": "tiktok", "disabled": False}],
            )

        self.assertEqual(integration["id"], "explicit-tiktok")
        self.assertEqual(integration["identifier"], "tiktok")

    def test_publish_videos_uses_instagram_standalone_settings_when_matched(self):
        integration = publish_videos.resolve_integration(
            "instagram",
            [{"id": "ig-id", "identifier": "instagram-standalone", "disabled": False}],
        )
        row = publish_videos.PublishRow(
            platform="instagram",
            title="Standalone Reel",
            description="Description",
            hashtags="#reel",
            video_path=Path("clip.mp4"),
            scheduled_time="2026-07-08T14:00:00Z",
        )

        payload = publish_videos.build_post_payload(
            row,
            integration_id=integration["id"],
            media={"id": "media-id", "path": "https://uploads.postiz.com/clip.mp4"},
            provider_type=integration["identifier"],
        )

        self.assertEqual(payload["posts"][0]["settings"]["__type"], "instagram-standalone")

    def test_publish_videos_continues_after_one_postiz_failure(self):
        with TemporaryDirectory() as temp_dir:
            videos_dir = Path(temp_dir) / "videos"
            videos_dir.mkdir()
            (videos_dir / "clip1.mp4").write_bytes(b"fake video")
            (videos_dir / "clip2.mp4").write_bytes(b"fake video")
            metadata_path = videos_dir / "metadata.csv"
            metadata_path.write_text(
                "platform,title,description,hashtags,file_path,scheduled_time\n"
                "youtube,First,Description,#one,clip1.mp4,2026-07-08T10:00:00Z\n"
                "tiktok,Second,Description,#two,clip2.mp4,2026-07-08T11:00:00Z\n",
                encoding="utf-8",
            )
            client = unittest.mock.Mock()
            client.list_integrations.return_value = [
                {"id": "youtube-id", "identifier": "youtube", "disabled": False},
                {"id": "tiktok-id", "identifier": "tiktok", "disabled": False},
            ]
            client.schedule_video.side_effect = [RuntimeError("upload failed"), {"postId": "ok"}]

            result = publish_videos.run_workflow(metadata_path, videos_dir, dry_run=False, client=client)

        self.assertEqual(result.failed, 1)
        self.assertEqual(result.published, 1)
        self.assertEqual(client.schedule_video.call_count, 2)

    def test_official_publisher_dry_run_does_not_call_clients(self):
        with TemporaryDirectory() as temp_dir:
            videos_dir = Path(temp_dir) / "videos"
            videos_dir.mkdir()
            (videos_dir / "clip1.mp4").write_bytes(b"fake video")
            metadata_path = videos_dir / "metadata.csv"
            metadata_path.write_text(
                "platform,title,description,hashtags,file_path,scheduled_time\n"
                "youtube,First,Description,#one,clip1.mp4,2026-07-08T10:00:00Z\n",
                encoding="utf-8",
            )
            registry = {"youtube": unittest.mock.Mock()}

            result = publish_videos_official.run_workflow(
                metadata_path,
                videos_dir,
                dry_run=True,
                clients=registry,
                now=publish_videos_official.parse_iso_time("2026-07-08T10:00:00Z"),
            )

        self.assertEqual(result.previewed, 1)
        registry["youtube"].publish.assert_not_called()

    def test_official_publisher_skips_future_rows_by_default(self):
        with TemporaryDirectory() as temp_dir:
            videos_dir = Path(temp_dir) / "videos"
            videos_dir.mkdir()
            (videos_dir / "clip1.mp4").write_bytes(b"fake video")
            metadata_path = videos_dir / "metadata.csv"
            metadata_path.write_text(
                "platform,title,description,hashtags,file_path,scheduled_time\n"
                "youtube,Future,Description,#one,clip1.mp4,2026-07-08T10:00:00Z\n",
                encoding="utf-8",
            )
            registry = {"youtube": unittest.mock.Mock()}

            result = publish_videos_official.run_workflow(
                metadata_path,
                videos_dir,
                dry_run=False,
                clients=registry,
                now=publish_videos_official.parse_iso_time("2026-07-08T09:59:00Z"),
            )

        self.assertEqual(result.skipped, 1)
        registry["youtube"].publish.assert_not_called()

    def test_youtube_client_refreshes_token_and_uploads_video(self):
        calls = []

        class FakeResponse:
            headers = {"Location": "https://upload.youtube.test/session"}

            def __init__(self, data=None):
                self._data = data or {}

            def json(self):
                return self._data

            def raise_for_status(self):
                return None

        class FakeSession:
            def post(self, url, **kwargs):
                calls.append(("post", url, kwargs))
                if "oauth2" in url:
                    return FakeResponse({"access_token": "access-token"})
                return FakeResponse()

            def put(self, url, **kwargs):
                calls.append(("put", url, kwargs))
                return FakeResponse({"id": "youtube-video-id"})

        with TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "clip.mp4"
            video_path.write_bytes(b"fake video")
            row = publish_videos.PublishRow(
                platform="youtube",
                title="Short Title",
                description="Description",
                hashtags="#shorts",
                video_path=video_path,
                scheduled_time="2026-07-08T10:00:00Z",
            )
            client = publish_videos_official.YouTubeClient(
                client_id="client-id",
                client_secret="client-secret",
                refresh_token="refresh-token",
                session=FakeSession(),
            )

            result = client.publish(row)

        self.assertEqual(result["id"], "youtube-video-id")
        self.assertEqual(calls[0][0], "post")
        self.assertEqual(calls[1][0], "post")
        self.assertIn("uploadType=resumable", calls[1][1])
        self.assertEqual(calls[2][0], "put")

    def test_tiktok_client_initializes_direct_post_and_uploads_file(self):
        calls = []

        class FakeResponse:
            def __init__(self, data=None):
                self._data = data or {}

            def json(self):
                return self._data

            def raise_for_status(self):
                return None

        class FakeSession:
            def post(self, url, **kwargs):
                calls.append(("post", url, kwargs))
                return FakeResponse(
                    {
                        "data": {
                            "publish_id": "publish-id",
                            "upload_url": "https://upload.tiktok.test/video",
                        }
                    }
                )

            def put(self, url, **kwargs):
                calls.append(("put", url, kwargs))
                return FakeResponse({})

        with TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "clip.mp4"
            video_path.write_bytes(b"fake video")
            row = publish_videos.PublishRow(
                platform="tiktok",
                title="TikTok Title",
                description="Description",
                hashtags="#story",
                video_path=video_path,
                scheduled_time="2026-07-08T10:00:00Z",
            )
            client = publish_videos_official.TikTokClient(access_token="token", session=FakeSession())

            result = client.publish(row)

        self.assertEqual(result["publish_id"], "publish-id")
        self.assertEqual(calls[0][0], "post")
        self.assertEqual(calls[1][0], "put")

    def test_tiktok_client_can_upload_draft_with_video_upload_scope(self):
        calls = []

        class FakeResponse:
            def __init__(self, data=None):
                self._data = data or {}

            def json(self):
                return self._data

            def raise_for_status(self):
                return None

        class FakeSession:
            def post(self, url, **kwargs):
                calls.append(("post", url, kwargs))
                return FakeResponse(
                    {
                        "data": {
                            "publish_id": "draft-publish-id",
                            "upload_url": "https://upload.tiktok.test/video",
                        }
                    }
                )

            def put(self, url, **kwargs):
                calls.append(("put", url, kwargs))
                return FakeResponse({})

        with TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "clip.mp4"
            video_path.write_bytes(b"fake video")
            row = publish_videos.PublishRow(
                platform="tiktok",
                title="TikTok Draft",
                description="Description",
                hashtags="#story",
                video_path=video_path,
                scheduled_time="2026-07-08T10:00:00Z",
            )
            client = publish_videos_official.TikTokClient(
                access_token="token",
                post_mode="upload",
                session=FakeSession(),
            )

            result = client.publish(row)

        self.assertEqual(result["publish_id"], "draft-publish-id")
        self.assertIn("/v2/post/publish/inbox/video/init/", calls[0][1])
        self.assertNotIn("post_info", calls[0][2]["json"])

    def test_tiktok_oauth_authorization_url_uses_pkce_and_scopes(self):
        url, state, verifier = tiktok_oauth_setup.build_authorization_url(
            client_key="client-key",
            redirect_uri="http://127.0.0.1:3455/callback/",
            scopes=["user.info.basic", "video.publish"],
            state="state-token",
            code_verifier="a" * 64,
        )

        self.assertEqual(state, "state-token")
        self.assertEqual(verifier, "a" * 64)
        self.assertIn("client_key=client-key", url)
        self.assertIn("scope=user.info.basic%2Cvideo.publish", url)
        self.assertIn("code_challenge_method=S256", url)

    def test_tiktok_refresh_token_gets_access_token_without_printing_secret(self):
        calls = []

        class FakeResponse:
            def json(self):
                return {"access_token": "new-access-token", "refresh_token": "new-refresh-token"}

            def raise_for_status(self):
                return None

        class FakeSession:
            def post(self, url, **kwargs):
                calls.append((url, kwargs))
                return FakeResponse()

        tokens = publish_videos_official.refresh_tiktok_access_token(
            client_key="client-key",
            client_secret="client-secret",
            refresh_token="refresh-token",
            session=FakeSession(),
        )

        self.assertEqual(tokens["access_token"], "new-access-token")
        self.assertEqual(calls[0][1]["data"]["grant_type"], "refresh_token")

    def test_instagram_client_creates_reel_container_then_publishes(self):
        calls = []

        class FakeResponse:
            def __init__(self, data):
                self._data = data

            def json(self):
                return self._data

            def raise_for_status(self):
                return None

        class FakeSession:
            def get(self, url, **kwargs):
                calls.append((url, kwargs))
                return FakeResponse({"status_code": "FINISHED"})

            def post(self, url, **kwargs):
                calls.append((url, kwargs))
                if url.endswith("/media"):
                    return FakeResponse({"id": "container-id"})
                return FakeResponse({"id": "media-id"})

        row = publish_videos.PublishRow(
            platform="instagram",
            title="IG Title",
            description="Description",
            hashtags="#reels",
            video_path=Path("clip.mp4"),
            scheduled_time="2026-07-08T10:00:00Z",
        )
        client = publish_videos_official.InstagramClient(
            access_token="token",
            ig_user_id="ig-user-id",
            public_base_url="https://cdn.example.com/videos",
            session=FakeSession(),
            container_poll_interval=0,
        )

        result = client.publish(row)

        self.assertEqual(result["id"], "media-id")
        self.assertEqual(calls[0][1]["data"]["media_type"], "REELS")
        self.assertIn("/container-id", calls[1][0])
        self.assertEqual(calls[1][1]["params"]["fields"], "status_code,status")
        self.assertEqual(calls[2][1]["data"]["creation_id"], "container-id")

    def test_instagram_client_uses_video_host_url(self):
        calls = []

        class FakeVideoHost:
            def video_url(self, video_path):
                self.video_path = video_path
                return "https://blob.example.com/videos/clip.mp4"

        class FakeResponse:
            def __init__(self, data):
                self._data = data

            def json(self):
                return self._data

            def raise_for_status(self):
                return None

        class FakeSession:
            def get(self, url, **kwargs):
                calls.append((url, kwargs))
                return FakeResponse({"status_code": "FINISHED"})

            def post(self, url, **kwargs):
                calls.append((url, kwargs))
                if url.endswith("/media"):
                    return FakeResponse({"id": "container-id"})
                return FakeResponse({"id": "media-id"})

        row = publish_videos.PublishRow(
            platform="instagram",
            title="IG Title",
            description="Description",
            hashtags="#reels",
            video_path=Path("clip.mp4"),
            scheduled_time="2026-07-08T10:00:00Z",
        )
        video_host = FakeVideoHost()
        client = publish_videos_official.InstagramClient(
            access_token="token",
            ig_user_id="ig-user-id",
            public_base_url="",
            session=FakeSession(),
            video_host=video_host,
            container_poll_interval=0,
        )

        client.publish(row)

        self.assertEqual(video_host.video_path, Path("clip.mp4"))
        self.assertEqual(calls[0][1]["data"]["video_url"], "https://blob.example.com/videos/clip.mp4")

    def test_vercel_blob_cli_video_host_uploads_and_returns_url(self):
        calls = []

        def fake_runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Uploaded https://blob.vercel-storage.com/videos/clip.mp4\n",
                stderr="",
            )

        host = publish_videos_official.VercelBlobCliVideoHost(
            rw_token="blob-token",
            upload_prefix="videos",
            cli_command="vercel",
            runner=fake_runner,
        )

        url = host.video_url(Path("clip.mp4"))

        self.assertEqual(url, "https://blob.vercel-storage.com/videos/clip.mp4")
        self.assertIn("blob", calls[0][0])
        self.assertIn("put", calls[0][0])
        self.assertIn("--allow-overwrite", calls[0][0])
        self.assertIn("videos/clip.mp4", calls[0][0])
        self.assertEqual(calls[0][1]["check"], True)

    def test_meta_oauth_authorization_url_requests_page_publish_scopes(self):
        url, state = meta_oauth_setup.build_authorization_url(
            app_id="app-id",
            redirect_uri="http://127.0.0.1:3456/callback/",
            scopes=["pages_show_list", "pages_read_engagement", "pages_manage_posts"],
            state="state-token",
        )

        self.assertEqual(state, "state-token")
        self.assertIn("client_id=app-id", url)
        self.assertIn("pages_show_list%2Cpages_read_engagement%2Cpages_manage_posts", url)

    def test_meta_get_page_access_token_selects_named_page(self):
        calls = []

        class FakeResponse:
            def __init__(self, data):
                self._data = data

            def json(self):
                return self._data

            def raise_for_status(self):
                return None

        class FakeSession:
            def get(self, url, **kwargs):
                calls.append((url, kwargs))
                return FakeResponse(
                    {
                        "data": [
                            {"id": "page-1", "name": "Other Page", "access_token": "other-token"},
                            {"id": "page-2", "name": "Maple Cast", "access_token": "page-token"},
                        ]
                    }
                )

        page = meta_oauth_setup.get_page_access_token(
            user_access_token="user-token",
            page_name="Maple Cast",
            session=FakeSession(),
        )

        self.assertEqual(page["id"], "page-2")
        self.assertEqual(page["access_token"], "page-token")
        self.assertIn("/me/accounts", calls[0][0])

    def test_facebook_client_publishes_reel_from_local_file(self):
        calls = []

        class FakeResponse:
            def __init__(self, data):
                self._data = data

            def json(self):
                return self._data

            def raise_for_status(self):
                return None

        class FakeSession:
            def post(self, url, **kwargs):
                calls.append((url, kwargs))
                if len(calls) == 1:
                    return FakeResponse(
                        {
                            "video_id": "video-id",
                            "upload_url": "https://rupload.facebook.com/video-upload/v20.0/video-id",
                        }
                    )
                if len(calls) == 2:
                    return FakeResponse({"success": True})
                return FakeResponse({"id": "facebook-reel-id", "success": True})

        with TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "clip.mp4"
            video_path.write_bytes(b"fake-video")

            row = publish_videos.PublishRow(
                platform="facebook",
                title="FB Reel",
                description="Description",
                hashtags="#reels",
                video_path=video_path,
                scheduled_time="2026-07-08T10:00:00Z",
            )
            client = publish_videos_official.FacebookClient(
                page_id="page-id",
                page_access_token="page-token",
                session=FakeSession(),
            )

            result = client.publish(row)

        self.assertEqual(result["id"], "facebook-reel-id")
        self.assertIn("/page-id/video_reels", calls[0][0])
        self.assertEqual(calls[0][1]["data"]["upload_phase"], "start")
        self.assertEqual(calls[1][0], "https://rupload.facebook.com/video-upload/v20.0/video-id")
        self.assertEqual(calls[1][1]["headers"]["Authorization"], "OAuth page-token")
        self.assertEqual(calls[1][1]["headers"]["file_size"], "10")
        self.assertEqual(calls[2][1]["data"]["upload_phase"], "finish")
        self.assertEqual(calls[2][1]["data"]["video_state"], "PUBLISHED")
        self.assertEqual(calls[2][1]["data"]["description"], "Description\n\n#reels")

    def test_episode_has_twelve_scenes(self):
        episode_path = PROJECT_ROOT / "prompts" / "episode_01.json"

        with episode_path.open("r", encoding="utf-8") as file:
            episode = json.load(file)

        self.assertEqual(episode["aspect_ratio"], "9:16")
        self.assertEqual(len(episode["scenes"]), 12)

        for index, scene in enumerate(episode["scenes"], start=1):
            self.assertEqual(scene["id"], index)
            self.assertIn("duration", scene)
            self.assertIn("caption", scene)
            self.assertIn("prompt", scene)

    def test_srt_timestamp_formatting(self):
        self.assertEqual(format_timestamp(0), "00:00:00,000")
        self.assertEqual(format_timestamp(65.25), "00:01:05,250")

    def test_make_srt_blocks_uses_scene_durations(self):
        scenes = [
            {"id": 1, "duration": 1.5, "caption": "First line"},
            {"id": 2, "duration": 2.0, "caption": "Second line"},
        ]

        blocks = make_srt_blocks(scenes)

        self.assertIn("1\n00:00:00,000 --> 00:00:01,500\nFirst line", blocks)
        self.assertIn("2\n00:00:01,500 --> 00:00:03,500\nSecond line", blocks)

    def test_wrap_caption_splits_long_lines(self):
        caption = '"She is useless." "She won\'t survive one night."'

        wrapped = wrap_caption(caption, max_line_length=24)

        self.assertIn("\n", wrapped)
        for line in wrapped.splitlines():
            self.assertLessEqual(len(line), 24)

    def test_split_voiceover_lines_keeps_full_narration(self):
        voiceover = "The sky cracked open.\nEARTH HAS FAILED.\nThey were wrong."

        lines = split_voiceover_lines(voiceover)

        self.assertEqual(lines, ["The sky cracked open.", "EARTH HAS FAILED.", "They were wrong."])

    def test_make_voiceover_srt_blocks_uses_all_voiceover_lines(self):
        lines = ["The sky cracked open.", "EARTH HAS FAILED.", "They were wrong."]

        blocks = make_voiceover_srt_blocks(lines, total_duration=9)

        self.assertIn("The sky cracked open.", blocks)
        self.assertIn("EARTH HAS FAILED.", blocks)
        self.assertIn("They were wrong.", blocks)
        self.assertIn("--> 00:00:09,000", blocks)

    def test_generate_voiceover_reads_episode_voiceover_text(self):
        voiceover = generate_voiceover.load_voiceover_text(PROJECT_ROOT / "prompts" / "episode_01.json")

        self.assertIsInstance(voiceover, str)
        self.assertGreater(len(voiceover), 20)

    def test_generate_voiceover_skips_cleanly_without_api_key(self):
        with patch.dict("os.environ", {"ELEVENLABS_VOICE_ID": "voice-123"}, clear=True):
            with patch.object(generate_voiceover, "load_environment"):
                with patch("builtins.print") as mock_print:
                    result = generate_voiceover.main()

        self.assertEqual(result, 1)
        mock_print.assert_called_with(
            "Missing ELEVENLABS_API_KEY. Add it to .env before generating voiceover audio."
        )

    def test_assemble_video_uses_voiceover_mp3_when_it_exists(self):
        with TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "voiceover.mp3"
            audio_path.write_bytes(b"fake mp3")

            with patch.object(assemble_video, "AUDIO_PATH", audio_path):
                command = assemble_video.build_ffmpeg_command("ffmpeg")

        self.assertIn(str(audio_path), command)
        self.assertIn("-shortest", command)
        self.assertIn("-c:a", command)

    def test_assemble_video_uses_smaller_wrapped_subtitle_style(self):
        command = assemble_video.build_ffmpeg_command("ffmpeg")
        command_text = " ".join(command)

        self.assertIn("FontSize=7", command_text)
        self.assertIn("MarginV=70", command_text)
        self.assertIn("WrapStyle=2", command_text)

    def test_replicate_output_path_uses_three_digit_scene_numbers(self):
        output_path = generate_video_clips_replicate.scene_output_path({"id": 7})

        self.assertEqual(output_path.name, "scene_007.mp4")

    def test_replicate_max_scenes_limits_episode_scenes(self):
        scenes = [{"id": 1}, {"id": 2}, {"id": 3}]

        selected = generate_video_clips_replicate.select_scenes(scenes, max_scenes=2)

        self.assertEqual([scene["id"] for scene in selected], [1, 2])

    def test_replicate_model_input_defaults_to_low_cost_vertical_clip(self):
        model_input = generate_video_clips_replicate.build_model_input("A forest scene")

        self.assertEqual(model_input["prompt"], "A forest scene")
        self.assertEqual(model_input["duration"], 5)
        self.assertEqual(model_input["aspect_ratio"], "9:16")
        self.assertEqual(model_input["resolution"], "720p")

    def test_replicate_skips_cleanly_without_api_token(self):
        with patch.dict("os.environ", {"REPLICATE_VIDEO_MODEL": "owner/model"}, clear=True):
            with patch.object(generate_video_clips_replicate, "load_environment"):
                with patch("builtins.print") as mock_print:
                    result = generate_video_clips_replicate.main([])

        self.assertEqual(result, 1)
        mock_print.assert_called_with(
            "Missing REPLICATE_API_TOKEN. Add it to .env before generating video clips."
        )

    def test_replicate_main_reports_generation_failure_without_traceback(self):
        with patch.dict("os.environ", {"REPLICATE_API_TOKEN": "token", "REPLICATE_VIDEO_MODEL": "owner/model"}):
            with patch.object(generate_video_clips_replicate, "load_environment"):
                with patch.object(generate_video_clips_replicate, "generate_scene_clip", side_effect=RuntimeError("Insufficient credit")):
                    with patch("builtins.print") as mock_print:
                        result = generate_video_clips_replicate.main(["--max-scenes", "1"])

        self.assertEqual(result, 1)
        printed_text = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
        self.assertIn("Video generation failed for scene 001", printed_text)
        self.assertIn("Insufficient credit", printed_text)

    def test_replicate_scene_generation_retries_after_failure(self):
        calls = []

        def fake_run_model(model, model_input):
            calls.append((model, model_input))
            if len(calls) == 1:
                raise RuntimeError("temporary failure")
            return b"video bytes"

        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "scene_001.mp4"

            with patch("builtins.print"):
                generate_video_clips_replicate.generate_scene_clip(
                    scene={"id": 1, "prompt": "A vertical library video"},
                    model="owner/model",
                    output_path=output_path,
                    run_model=fake_run_model,
                    max_retries=2,
                    retry_delay_seconds=0,
                )

            self.assertEqual(output_path.read_bytes(), b"video bytes")

        self.assertEqual(len(calls), 2)

    def test_assemble_video_prefers_three_digit_generated_clips(self):
        with TemporaryDirectory() as temp_dir:
            video_dir = Path(temp_dir)
            three_digit_clip = video_dir / "scene_001.mp4"
            two_digit_clip = video_dir / "scene_01.mp4"
            three_digit_clip.write_bytes(b"replicate")
            two_digit_clip.write_bytes(b"placeholder")

            with patch.object(assemble_video, "VIDEO_DIR", video_dir):
                clip_path = assemble_video.scene_clip_path(1)

        self.assertEqual(clip_path.name, "scene_001.mp4")

    def test_generate_episode_from_prompt_has_required_fields(self):
        episode = generate_episode_from_text.build_episode_from_prompt(
            "Write an apocalypse lord game short video first episode about Maya Lin."
        )

        self.assertIn("title", episode)
        self.assertIn("episode_title", episode)
        self.assertIn("voiceover", episode)
        self.assertEqual(episode["character_prompt"], generate_episode_from_text.CHARACTER_PROMPT)
        self.assertEqual(episode["style_prompt"], generate_episode_from_text.STYLE_PROMPT)
        self.assertEqual(episode["negative_prompt"], generate_episode_from_text.NEGATIVE_PROMPT)
        self.assertEqual(episode["aspect_ratio"], "9:16")
        self.assertGreaterEqual(len(episode["scenes"]), 10)
        self.assertLessEqual(len(episode["scenes"]), 12)

        for index, scene in enumerate(episode["scenes"], start=1):
            self.assertEqual(scene["id"], index)
            self.assertIn("duration", scene)
            self.assertIn("caption", scene)
            self.assertIn("prompt", scene)
            self.assertIn("Maya Lin", scene["prompt"])
            self.assertIn("vertical 9:16", scene["prompt"])

    def test_generate_episode_writes_valid_json_file(self):
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "episode_01.json"

            generate_episode_from_text.write_episode_json(
                generate_episode_from_text.build_episode_from_prompt("Maya enters the forest."),
                output_path,
            )

            with output_path.open("r", encoding="utf-8") as file:
                episode = json.load(file)

        self.assertEqual(episode["episode_title"], "Episode 01")
        self.assertEqual(len(episode["scenes"]), 12)

    def test_generate_episode_from_prompt_pack_uses_pack_fields(self):
        prompt_pack_text = """
Project: The Girl Who Built Earth Again
Episode 1: The Last Game

AI Image/Video Character Prompt:
A realistic young Asian woman, 19 years old, messy black hair, oversized gray hoodie, vertical 9:16 frame.

Negative Prompt:
No fantasy armor, no anime style.

============================================================
5. SHORTER 60-SECOND VOICEOVER VERSION
============================================================

The sky cracked open at 7:03 p.m.
Earth has failed.

============================================================
6. SCENE-BY-SCENE VIDEO PROMPTS
============================================================

Scene 1: The Sky Cracks Open
------------------------------------------------------------
Visual Prompt:
A modern city at dusk, the sky cracks open, cinematic, vertical 9:16.

Text on Screen:
The sky cracked open at 7:03 p.m.

Sound:
Low rumble.

Scene 2: Every Screen Goes Black
------------------------------------------------------------
Visual Prompt:
Phones and billboards turn black, white text appears, cinematic, vertical 9:16.

Text on Screen:
EARTH HAS FAILED.

Sound:
Electronic glitch.

============================================================
7. COVER IMAGE PROMPTS
============================================================
"""

        episode = generate_episode_from_text.build_episode_from_prompt_pack(prompt_pack_text)

        self.assertEqual(episode["title"], "The Girl Who Built Earth Again")
        self.assertEqual(episode["episode_title"], "The Last Game")
        self.assertIn("The sky cracked open", episode["voiceover"])
        self.assertEqual(len(episode["scenes"]), 2)
        self.assertEqual(episode["scenes"][0]["caption"], "The sky cracked open at 7:03 p.m.")
        self.assertIn("A modern city at dusk", episode["scenes"][0]["prompt"])

    def test_make_video_prompt_pack_workflow_runs_episode_pack_step(self):
        calls = []

        def fake_runner(script_name, script_args):
            calls.append((script_name, script_args))
            return 0

        with patch.object(make_video, "remove_old_voiceover"), patch.object(make_video, "remove_replicate_clips"), patch("builtins.print"):
            result = make_video.run_workflow(
                prompt=None,
                prompt_pack="D:/downlano/AI_Video_Episode1_Prompt_Pack.txt",
                mode="placeholder",
                max_scenes=None,
                runner=fake_runner,
            )

        self.assertEqual(result, 0)
        self.assertEqual(
            calls[0],
            (
                "generate_episode_from_text.py",
                ["--prompt-pack", "D:/downlano/AI_Video_Episode1_Prompt_Pack.txt"],
            ),
        )

    def test_make_video_placeholder_removes_stale_replicate_clips(self):
        with TemporaryDirectory() as temp_dir:
            video_dir = Path(temp_dir)
            replicate_clip = video_dir / "scene_001.mp4"
            placeholder_clip = video_dir / "scene_01.mp4"
            other_file = video_dir / "notes.txt"
            replicate_clip.write_bytes(b"old ai")
            placeholder_clip.write_bytes(b"placeholder")
            other_file.write_text("keep", encoding="utf-8")

            with patch.object(make_video, "VIDEO_DIR", video_dir), patch("builtins.print"):
                make_video.remove_replicate_clips()

            self.assertFalse(replicate_clip.exists())
            self.assertTrue(placeholder_clip.exists())
            self.assertTrue(other_file.exists())

    def test_make_video_placeholder_workflow_runs_expected_steps(self):
        calls = []

        def fake_runner(script_name, script_args):
            calls.append((script_name, script_args))
            return 0

        with patch.object(make_video, "remove_old_voiceover"), patch("builtins.print"):
            result = make_video.run_workflow(
                prompt="Maya enters the island.",
                mode="placeholder",
                max_scenes=None,
                runner=fake_runner,
            )

        self.assertEqual(result, 0)
        self.assertEqual(
            [script_name for script_name, script_args in calls],
            [
                "generate_episode_from_text.py",
                "generate_placeholder_clips.py",
                "generate_voiceover.py",
                "generate_srt.py",
                "assemble_video.py",
            ],
        )

    def test_make_video_replicate_workflow_passes_max_scenes(self):
        calls = []

        def fake_runner(script_name, script_args):
            calls.append((script_name, script_args))
            return 0

        with patch.object(make_video, "remove_old_voiceover"), patch("builtins.print"):
            result = make_video.run_workflow(
                prompt="Maya enters the island.",
                mode="replicate",
                max_scenes=1,
                runner=fake_runner,
            )

        self.assertEqual(result, 0)
        self.assertIn(("generate_video_clips_replicate.py", ["--max-scenes", "1"]), calls)

    def test_make_video_continues_when_voiceover_step_has_missing_key(self):
        calls = []

        def fake_runner(script_name, script_args):
            calls.append(script_name)
            if script_name == "generate_voiceover.py":
                return 1
            return 0

        with patch.object(make_video, "remove_old_voiceover"), patch("builtins.print"):
            result = make_video.run_workflow(
                prompt="Maya enters the island.",
                mode="placeholder",
                max_scenes=None,
                runner=fake_runner,
            )

        self.assertEqual(result, 0)
        self.assertIn("assemble_video.py", calls)

    def test_make_video_stops_safely_when_required_step_fails(self):
        calls = []

        def fake_runner(script_name, script_args):
            calls.append(script_name)
            if script_name == "generate_video_clips_replicate.py":
                return 1
            return 0

        with patch.object(make_video, "remove_old_voiceover"), patch("builtins.print"):
            result = make_video.run_workflow(
                prompt="Maya enters the island.",
                mode="replicate",
                max_scenes=1,
                runner=fake_runner,
            )

        self.assertEqual(result, 1)
        self.assertNotIn("assemble_video.py", calls)


if __name__ == "__main__":
    unittest.main()
