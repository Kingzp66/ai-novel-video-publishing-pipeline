import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_youtube_images_sdxl.py"


class SdxlGenerationTests(unittest.TestCase):
    def load_module(self):
        self.assertTrue(SCRIPT.exists(), "SDXL generator script must exist")
        spec = importlib.util.spec_from_file_location("sdxl_generator", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_build_prompt_keeps_scene_direction_and_stays_concise(self):
        module = self.load_module()

        prompt = module.build_prompt("prefix. Scene: Jake listens carefully in his bedroom.")

        self.assertIn("Jake listens carefully in his bedroom", prompt)
        self.assertNotIn("prefix", prompt)
        self.assertLess(len(prompt.split()), 77)

    def test_scene_filename_uses_two_digit_minimum(self):
        module = self.load_module()

        self.assertEqual(module.scene_filename(7), "scene_07.png")
        self.assertEqual(module.scene_filename(112), "scene_112.png")


if __name__ == "__main__":
    unittest.main()
