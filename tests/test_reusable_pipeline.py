import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils import (
    PipelineError,
    ensure_project_directories,
    load_config,
    load_scenes,
    resolve_image_path,
)
from make_subtitles import build_subtitle_blocks, format_srt_time
from make_video import build_video_plan, zoompan_expression
from generate_voice import use_edge_tts
from generate_images_openai import build_openai_prompt, should_generate_image


class ReusablePipelineTests(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        project = root / "sample_project"
        project.mkdir()
        (project / "script.txt").write_text("Line one.\nLine two.", encoding="utf-8")
        (project / "config.json").write_text(
            json.dumps(
                {
                    "project_name": "Sample",
                    "video_mode": "vertical",
                    "resolution": "1080x1920",
                    "fps": 30,
                    "generate_images": False,
                    "generate_voice": False,
                    "burn_subtitles": True,
                    "use_background_music": False,
                    "style_prefix": "cinematic",
                    "replicate_model": "owner/model",
                    "voice_name": "Rachel",
                    "output_filename": "final_video.mp4",
                }
            ),
            encoding="utf-8",
        )
        (project / "image_prompts.csv").write_text(
            "scene_id,start_time,end_time,image_file,motion_type,prompt,sfx\n"
            "1,0,2,scene_001.png,zoom_in,A city,\n"
            "2,2,5,scene_002.png,pan_left,A room,hit.mp3\n",
            encoding="utf-8",
        )
        return project

    def test_load_config_merges_defaults_and_keeps_project_values(self):
        with TemporaryDirectory() as temp_dir:
            project = self.make_project(Path(temp_dir))

            config = load_config(project)

        self.assertEqual(config["project_name"], "Sample")
        self.assertEqual(config["resolution"], "1080x1920")
        self.assertEqual(config["force_regenerate"], False)

    def test_load_scenes_validates_required_csv_columns(self):
        with TemporaryDirectory() as temp_dir:
            project = self.make_project(Path(temp_dir))
            (project / "image_prompts.csv").write_text("scene_id,prompt\n1,A city\n", encoding="utf-8")

            with self.assertRaises(PipelineError):
                load_scenes(project)

    def test_resolve_image_path_uses_generated_images_for_relative_names(self):
        with TemporaryDirectory() as temp_dir:
            project = self.make_project(Path(temp_dir))

            path = resolve_image_path(project, "scene_001.png")

        self.assertEqual(path, project / "generated_images" / "scene_001.png")

    def test_ensure_project_directories_creates_pipeline_outputs(self):
        with TemporaryDirectory() as temp_dir:
            project = self.make_project(Path(temp_dir))

            ensure_project_directories(project)

            for name in ["generated_images", "generated_audio", "generated_subtitles", "logs", "output"]:
                self.assertTrue((project / name).is_dir())

    def test_build_subtitle_blocks_maps_lines_to_scene_timings(self):
        scenes = [
            {"scene_id": "1", "start_time": 0.0, "end_time": 2.0},
            {"scene_id": "2", "start_time": 2.0, "end_time": 5.0},
        ]

        blocks = build_subtitle_blocks("First line.\nSecond line.", scenes)

        self.assertIn("1\n00:00:00,000 --> 00:00:02,000\nFirst line.", blocks)
        self.assertIn("2\n00:00:02,000 --> 00:00:05,000\nSecond line.", blocks)

    def test_format_srt_time_handles_fractional_seconds(self):
        self.assertEqual(format_srt_time(65.25), "00:01:05,250")

    def test_build_video_plan_uses_configured_output_and_scene_durations(self):
        with TemporaryDirectory() as temp_dir:
            project = self.make_project(Path(temp_dir))
            config = load_config(project)
            scenes = load_scenes(project)

            plan = build_video_plan(project, config, scenes)

        self.assertEqual(plan.output_path, project / "output" / "final_video.mp4")
        self.assertEqual([scene.duration for scene in plan.scenes], [2.0, 3.0])
        self.assertEqual(plan.width, 1080)
        self.assertEqual(plan.height, 1920)

    def test_zoompan_expression_interpolates_pan_frame_count(self):
        expression = zoompan_expression("pan_right", 1080, 1920, 300)

        self.assertNotIn("{frames}", expression)
        self.assertIn("on/300", expression)

    def test_use_edge_tts_when_voice_provider_is_edge_tts(self):
        config = {"voice_provider": "edge_tts"}

        self.assertTrue(use_edge_tts(config))

    def test_build_openai_prompt_prepends_style_prefix_once(self):
        config = {"style_prefix": "flat cartoon, no text"}
        scene = {"prompt": "A banker in an office."}

        prompt = build_openai_prompt(config, scene)

        self.assertEqual(prompt, "flat cartoon, no text. A banker in an office.")

    def test_should_generate_image_skips_existing_unless_forced(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "scene.png"
            path.write_bytes(b"image")

            self.assertFalse(should_generate_image(path, force=False))
            self.assertTrue(should_generate_image(path, force=True))


if __name__ == "__main__":
    unittest.main()
