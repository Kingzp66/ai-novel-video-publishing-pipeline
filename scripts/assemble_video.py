"""
Assemble the final vertical video.

This script joins all scene clips, burns in the generated SRT subtitles, and
optionally adds assets/audio/voiceover.mp3 if that file exists.
"""

import json
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EPISODE_PATH = PROJECT_ROOT / "prompts" / "episode_01.json"
VIDEO_DIR = PROJECT_ROOT / "assets" / "videos"
SUBTITLE_PATH = PROJECT_ROOT / "assets" / "subtitles" / "episode_01.srt"
AUDIO_PATH = PROJECT_ROOT / "assets" / "audio" / "voiceover.mp3"
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_PATH = OUTPUT_DIR / "episode_01_final.mp4"
CONCAT_LIST_PATH = OUTPUT_DIR / "episode_01_clips.txt"


def find_ffmpeg():
    """Find FFmpeg from PATH, or from the D: drive install used in this project."""
    ffmpeg_from_path = shutil.which("ffmpeg")
    if ffmpeg_from_path:
        return ffmpeg_from_path

    windows_d_drive_ffmpeg = Path("D:/ffmpeg/bin/ffmpeg.exe")
    if windows_d_drive_ffmpeg.exists():
        return str(windows_d_drive_ffmpeg)

    raise FileNotFoundError(
        "FFmpeg was not found. Install FFmpeg and make sure ffmpeg.exe is in PATH."
    )


def as_ffmpeg_path(path):
    """Convert a Windows path to a form FFmpeg filter strings understand."""
    return path.resolve().as_posix()


def scene_clip_path(scene_id):
    """Find a scene clip, preferring Replicate's three-digit filenames."""
    replicate_clip_path = VIDEO_DIR / f"scene_{scene_id:03}.mp4"
    if replicate_clip_path.exists():
        return replicate_clip_path

    return VIDEO_DIR / f"scene_{scene_id:02}.mp4"


def write_concat_list(scene_ids):
    """Create the text file FFmpeg's concat demuxer needs."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    lines = []
    for scene_id in scene_ids:
        clip_path = scene_clip_path(scene_id)
        if not clip_path.exists():
            raise FileNotFoundError(
                f"Missing clip for scene {scene_id}. Run scripts/generate_placeholder_clips.py or scripts/generate_video_clips_replicate.py first."
            )

        # Single quotes are part of FFmpeg's concat list format.
        lines.append(f"file '{as_ffmpeg_path(clip_path)}'")

    CONCAT_LIST_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_ffmpeg_command(ffmpeg):
    """Build the FFmpeg command for the current files on disk."""
    # Use a relative subtitle path so Windows drive letters like D: do not
    # confuse FFmpeg's subtitles filter option parser.
    subtitle_filter = (
        "subtitles=assets/subtitles/episode_01.srt:"
        "force_style='FontName=Arial,FontSize=7,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,"
        "Alignment=2,MarginV=70,WrapStyle=2'"
    )

    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(CONCAT_LIST_PATH),
    ]

    if AUDIO_PATH.exists():
        command.extend(["-i", str(AUDIO_PATH), "-map", "0:v:0", "-map", "1:a:0"])
    else:
        command.extend(["-map", "0:v:0"])

    command.extend(
        [
            "-vf",
            subtitle_filter,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
        ]
    )

    if AUDIO_PATH.exists():
        command.extend(["-c:a", "aac", "-shortest"])

    command.append(str(OUTPUT_PATH))
    return command


def main():
    """Join clips, burn subtitles, and export output/episode_01_final.mp4."""
    if not SUBTITLE_PATH.exists():
        raise FileNotFoundError(
            f"Missing subtitles: {SUBTITLE_PATH}. Run scripts/generate_srt.py first."
        )

    ffmpeg = find_ffmpeg()

    with EPISODE_PATH.open("r", encoding="utf-8") as file:
        episode = json.load(file)

    scene_ids = [scene["id"] for scene in episode["scenes"]]
    write_concat_list(scene_ids)

    command = build_ffmpeg_command(ffmpeg)
    subprocess.run(command, check=True, cwd=PROJECT_ROOT)

    print(f"Created final video: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
