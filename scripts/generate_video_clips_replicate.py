"""
Generate scene video clips from prompts/episode_01.json using Replicate.

The model-specific input mapping is isolated in build_model_input() so changing
Replicate text-to-video models later only requires editing one function.
"""

import argparse
import json
import os
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EPISODE_PATH = PROJECT_ROOT / "prompts" / "episode_01.json"
VIDEO_DIR = PROJECT_ROOT / "assets" / "videos"
DEFAULT_DURATION_SECONDS = 5
DEFAULT_ASPECT_RATIO = "9:16"
DEFAULT_RESOLUTION = "720p"


def load_environment():
    """Load .env values when python-dotenv is installed."""
    if load_dotenv is not None:
        load_dotenv(PROJECT_ROOT / ".env")


def load_episode(episode_path):
    """Read the episode JSON file."""
    with episode_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def select_scenes(scenes, max_scenes=None):
    """Return all scenes or only the first max_scenes scenes."""
    if max_scenes is None:
        return scenes

    return scenes[:max_scenes]


def scene_output_path(scene):
    """Return the Replicate output path for one scene."""
    return VIDEO_DIR / f"scene_{scene['id']:03}.mp4"


def build_model_input(
    prompt,
    duration_seconds=DEFAULT_DURATION_SECONDS,
    aspect_ratio=DEFAULT_ASPECT_RATIO,
    resolution=DEFAULT_RESOLUTION,
):
    """
    Build the input dictionary for the selected Replicate video model.

    Many text-to-video models accept prompt, duration, and aspect_ratio. If your
    chosen model uses different names, change this function only.
    """
    return {
        "prompt": prompt,
        "duration": duration_seconds,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
    }


def run_replicate_model(model, model_input):
    """Run the configured Replicate model."""
    import replicate

    return replicate.run(model, input=model_input)


def first_video_output(output):
    """Find the first usable video output from common Replicate return shapes."""
    if isinstance(output, (list, tuple)):
        if not output:
            raise ValueError("Replicate returned no outputs.")
        return first_video_output(output[0])

    if isinstance(output, dict):
        for key in ("video", "output", "url"):
            if key in output:
                return first_video_output(output[key])
        raise ValueError("Replicate returned a dictionary without a video output.")

    return output


def write_video_output(output, output_path):
    """Write a Replicate file output, URL, or raw bytes to disk."""
    video_output = first_video_output(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(video_output, bytes):
        output_path.write_bytes(video_output)
        return

    if hasattr(video_output, "read"):
        output_path.write_bytes(video_output.read())
        return

    if isinstance(video_output, str) and video_output.startswith(("http://", "https://")):
        import requests

        response = requests.get(video_output, timeout=120)
        response.raise_for_status()
        output_path.write_bytes(response.content)
        return

    raise TypeError(f"Unsupported Replicate output type: {type(video_output).__name__}")


def generate_scene_clip(
    scene,
    model,
    output_path,
    run_model=run_replicate_model,
    max_retries=3,
    retry_delay_seconds=5,
):
    """Generate one scene clip, retrying failed generations."""
    model_input = build_model_input(scene["prompt"])

    for attempt in range(1, max_retries + 1):
        try:
            output = run_model(model, model_input)
            write_video_output(output, output_path)
            return
        except Exception as error:
            if attempt >= max_retries:
                raise

            print(
                f"Scene {scene['id']:03} failed on attempt {attempt}/{max_retries}: {error}. Retrying..."
            )
            if retry_delay_seconds:
                time.sleep(retry_delay_seconds)


def parse_args(argv=None):
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description="Generate Replicate video clips for episode scenes.")
    parser.add_argument(
        "--max-scenes",
        type=int,
        default=None,
        help="Generate only the first N scenes for a quick test run.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Maximum attempts per scene.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """Generate assets/videos/scene_001.mp4, scene_002.mp4, and so on."""
    args = parse_args(argv)
    load_environment()

    api_token = os.getenv("REPLICATE_API_TOKEN")
    if not api_token:
        print("Missing REPLICATE_API_TOKEN. Add it to .env before generating video clips.")
        return 1

    model = os.getenv("REPLICATE_VIDEO_MODEL")
    if not model:
        print("Missing REPLICATE_VIDEO_MODEL. Add it to .env before generating video clips.")
        return 1

    episode = load_episode(EPISODE_PATH)
    scenes = select_scenes(episode["scenes"], args.max_scenes)

    for scene in scenes:
        output_path = scene_output_path(scene)
        print(f"Generating scene {scene['id']:03}: {output_path}")
        try:
            generate_scene_clip(
                scene=scene,
                model=model,
                output_path=output_path,
                max_retries=args.retries,
            )
        except Exception as error:
            print(f"Video generation failed for scene {scene['id']:03}: {error}")
            return 1

        print(f"Created clip: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
