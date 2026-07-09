"""
Run the simplest full video workflow from one story prompt.

Example:
python scripts/make_video.py --mode placeholder --prompt "your story prompt"
"""

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
OUTPUT_PATH = PROJECT_ROOT / "output" / "episode_01_final.mp4"
VOICEOVER_PATH = PROJECT_ROOT / "assets" / "audio" / "voiceover.mp3"
VIDEO_DIR = PROJECT_ROOT / "assets" / "videos"


def run_python_script(script_name, script_args):
    """Run one project script with the current Python interpreter."""
    command = [sys.executable, str(SCRIPTS_DIR / script_name), *script_args]
    completed = subprocess.run(command, cwd=PROJECT_ROOT)
    return completed.returncode


def run_step(step_number, description, script_name, script_args, runner):
    """Print progress, run one script, and return its exit code."""
    print(f"\nStep {step_number}: {description}", flush=True)
    return runner(script_name, script_args)


def remove_old_voiceover():
    """Avoid accidentally reusing audio from a previous story."""
    if VOICEOVER_PATH.exists():
        VOICEOVER_PATH.unlink()
        print(f"Removed old voiceover: {VOICEOVER_PATH}", flush=True)


def remove_replicate_clips():
    """Avoid mixing stale three-digit Replicate clips into placeholder videos."""
    if not VIDEO_DIR.exists():
        return

    for clip_path in VIDEO_DIR.glob("scene_[0-9][0-9][0-9].mp4"):
        clip_path.unlink()
        print(f"Removed old Replicate clip: {clip_path}", flush=True)


def run_workflow(prompt=None, mode="placeholder", max_scenes=None, prompt_pack=None, runner=run_python_script):
    """Generate the episode JSON, clips, voiceover, subtitles, and final MP4."""
    print("Starting video workflow...", flush=True)
    remove_old_voiceover()

    episode_args = ["--prompt-pack", prompt_pack] if prompt_pack else ["--prompt", prompt]

    result = run_step(
        1,
        "Generate episode JSON",
        "generate_episode_from_text.py",
        episode_args,
        runner,
    )
    if result != 0:
        print("Could not generate episode JSON. Please check the prompt and try again.", flush=True)
        return result

    if mode == "placeholder":
        remove_replicate_clips()
        result = run_step(
            2,
            "Generate local placeholder video clips",
            "generate_placeholder_clips.py",
            [],
            runner,
        )
    else:
        replicate_args = []
        if max_scenes is not None:
            replicate_args.extend(["--max-scenes", str(max_scenes)])

        result = run_step(
            2,
            "Generate AI video clips with Replicate",
            "generate_video_clips_replicate.py",
            replicate_args,
            runner,
        )

    if result != 0:
        print("Video clip generation stopped safely. Check your .env API keys and model settings.", flush=True)
        return result

    voiceover_result = run_step(
        3,
        "Generate ElevenLabs voiceover if API keys are configured",
        "generate_voiceover.py",
        [],
        runner,
    )
    if voiceover_result != 0:
        print("Voiceover was skipped or failed. Continuing without narration audio.", flush=True)

    result = run_step(4, "Generate subtitles", "generate_srt.py", [], runner)
    if result != 0:
        print("Subtitle generation failed.", flush=True)
        return result

    result = run_step(5, "Assemble final video", "assemble_video.py", [], runner)
    if result != 0:
        print("Video assembly failed. Check that FFmpeg is installed and clips exist.", flush=True)
        return result

    print(f"\nFinal video created: {OUTPUT_PATH}", flush=True)
    return 0


def parse_args(argv=None):
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description="Make a short video from one story prompt.")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--prompt", help="Story prompt for episode generation.")
    source_group.add_argument("--prompt-pack", help="Path to a structured prompt pack text file.")
    parser.add_argument(
        "--mode",
        choices=["placeholder", "replicate"],
        required=True,
        help="Use local placeholder clips or Replicate AI video clips.",
    )
    parser.add_argument(
        "--max-scenes",
        type=int,
        default=None,
        help="For replicate mode, generate only the first N scenes.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """Run the command-line workflow."""
    args = parse_args(argv)
    return run_workflow(
        prompt=args.prompt,
        mode=args.mode,
        max_scenes=args.max_scenes,
        prompt_pack=args.prompt_pack,
    )


if __name__ == "__main__":
    raise SystemExit(main())
