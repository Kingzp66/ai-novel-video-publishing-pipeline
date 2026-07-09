import argparse
import sys
from pathlib import Path

from generate_images import generate_missing_images
from generate_voice import generate_voiceover
from make_subtitles import create_subtitles
from make_video import render_video
from utils import (
    PipelineError,
    ensure_project_directories,
    load_config,
    load_dotenv_if_available,
    load_scenes,
    project_path,
    validate_project_folder,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an AI story video from one project folder.")
    parser.add_argument("--project", required=True, help="Path to the project folder.")
    return parser.parse_args()


def run_pipeline(project: Path) -> int:
    summary: list[tuple[str, str]] = []

    try:
        load_dotenv_if_available()
        validate_project_folder(project)
        ensure_project_directories(project)
        config = load_config(project)
        scenes = load_scenes(project)

        generated_images = generate_missing_images(project, config, scenes)
        summary.append(("Images", f"generated {len(generated_images)} new image(s)"))

        voice_path = generate_voiceover(project, config)
        summary.append(("Voice", str(voice_path) if voice_path else "skipped"))

        subtitle_path = create_subtitles(project, scenes)
        summary.append(("Subtitles", str(subtitle_path)))

        output_path = render_video(project, config, scenes)
        summary.append(("Video", str(output_path)))

    except PipelineError as exc:
        print("\nPipeline failed.")
        print(f"Error: {exc}")
        if summary:
            print("\nCompleted before failure:")
            for label, detail in summary:
                print(f"- {label}: {detail}")
        return 1
    except KeyboardInterrupt:
        print("\nPipeline cancelled by user.")
        return 130

    print("\nPipeline completed successfully.")
    for label, detail in summary:
        print(f"- {label}: {detail}")
    print(f"\nProject folder: {project}")
    return 0


def main() -> int:
    args = parse_args()
    return run_pipeline(project_path(args.project))


if __name__ == "__main__":
    raise SystemExit(main())
