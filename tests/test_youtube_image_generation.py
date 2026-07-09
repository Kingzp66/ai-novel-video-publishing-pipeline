import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_youtube_images_replicate.py"
SPEC = importlib.util.spec_from_file_location("youtube_images", SCRIPT)
youtube_images = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(youtube_images)


class YoutubeImageGenerationTests(unittest.TestCase):
    def test_kontext_prompt_locks_doodle_style_without_realism(self):
        prompt = youtube_images.build_kontext_prompt(
            "Scene: Jake listens carefully.",
            scene_number=18,
        )

        self.assertIn("same hand-drawn editorial stick-figure doodle style", prompt)
        self.assertIn("lower 18 percent", prompt)
        self.assertNotIn("cinematic realism", prompt)
        self.assertNotIn("35mm documentary", prompt)

    def test_kontext_input_uses_reference_image(self):
        model_input = youtube_images.build_model_input(
            prompt="A new scene",
            reference_image=Path("scene_17.png"),
            seed=418,
        )

        self.assertEqual(model_input["aspect_ratio"], "16:9")
        self.assertEqual(model_input["input_image"], Path("scene_17.png"))
        self.assertEqual(model_input["seed"], 418)


if __name__ == "__main__":
    unittest.main()
