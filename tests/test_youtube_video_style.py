import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_youtube_video.py"
SPEC = importlib.util.spec_from_file_location("youtube_video", SCRIPT)
youtube_video = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(youtube_video)


class YoutubeVideoStyleTests(unittest.TestCase):
    def test_subtitle_style_is_readable_and_bottom_centered(self):
        style = youtube_video.subtitle_force_style()

        self.assertIn("FontSize=24", style)
        self.assertIn("Alignment=2", style)
        self.assertIn("MarginV=56", style)

    def test_zoompan_keeps_full_frame_before_subtle_motion(self):
        filter_value = youtube_video.zoompan_filter("zoom_in", 1920, 1080, 90, 30)

        self.assertNotIn("crop=1920:1080", filter_value)
        self.assertIn("min(1.08", filter_value)


if __name__ == "__main__":
    unittest.main()
