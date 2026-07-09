import subprocess
import tempfile
import unittest
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


ROOT = Path(r"D:\ai-novel-video-generator\youtube6")
VIDEO = ROOT / "output" / "final_youtube_video.mp4"
FFMPEG = Path(r"D:\ffmpeg\bin\ffmpeg.exe")
TIMING = json.loads((ROOT / "subtitles" / "timing.json").read_text(encoding="utf-8"))


def extract_frame(timestamp: float, destination: Path) -> None:
    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-ss",
            str(timestamp),
            "-i",
            str(VIDEO),
            "-frames:v",
            "1",
            str(destination),
        ],
        check=True,
    )


class Youtube6TransitionTest(unittest.TestCase):
    def test_scene_10_stays_visible_through_the_scene_11_intro_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline.png"
            near_end = Path(directory) / "near_end.png"
            sentence_54 = next(item for item in TIMING["sentences"] if item["sequence"] == 54)
            sentence_55 = next(item for item in TIMING["sentences"] if item["sequence"] == 55)
            extract_frame(sentence_54["start"] + 0.5, baseline)
            extract_frame(sentence_55["end"] - 0.2, near_end)

            with Image.open(baseline).convert("RGB") as left, Image.open(near_end).convert("RGB") as right:
                difference = ImageChops.difference(left.resize((320, 180)), right.resize((320, 180)))
                mean_difference = sum(ImageStat.Stat(difference).mean) / 3

        self.assertLess(mean_difference, 30.0, f"scene changes before the intro line ends: {mean_difference:.2f}")

    def test_scene_10_to_11_is_not_an_abrupt_visual_jump(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            before = Path(directory) / "before.png"
            after = Path(directory) / "after.png"
            sentence_55 = next(item for item in TIMING["sentences"] if item["sequence"] == 55)
            extract_frame(sentence_55["end"] - 0.1, before)
            extract_frame(sentence_55["end"] + 0.2, after)

            with Image.open(before).convert("RGB") as left, Image.open(after).convert("RGB") as right:
                difference = ImageChops.difference(left.resize((320, 180)), right.resize((320, 180)))
                mean_difference = sum(ImageStat.Stat(difference).mean) / 3

        self.assertLess(mean_difference, 24.0, f"abrupt transition score: {mean_difference:.2f}")


if __name__ == "__main__":
    unittest.main()
