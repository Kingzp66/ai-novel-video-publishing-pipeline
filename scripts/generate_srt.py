"""
Create a subtitle file from prompts/episode_01.json.

This script reads each scene's duration and caption, then writes a standard
.srt subtitle file that FFmpeg can burn into the final video.
"""

import json
import re
import textwrap
from pathlib import Path


# The project root is one folder above this script file.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
EPISODE_PATH = PROJECT_ROOT / "prompts" / "episode_01.json"
SUBTITLE_PATH = PROJECT_ROOT / "assets" / "subtitles" / "episode_01.srt"


def format_timestamp(seconds):
    """Turn seconds into the SRT time format: HH:MM:SS,mmm."""
    total_milliseconds = int(round(seconds * 1000))

    hours = total_milliseconds // 3_600_000
    total_milliseconds %= 3_600_000

    minutes = total_milliseconds // 60_000
    total_milliseconds %= 60_000

    whole_seconds = total_milliseconds // 1000
    milliseconds = total_milliseconds % 1000

    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"


def wrap_caption(caption, max_line_length=24):
    """Wrap long captions so burned-in subtitles stay inside a vertical frame."""
    return "\n".join(
        textwrap.wrap(
            caption,
            width=max_line_length,
            break_long_words=False,
            break_on_hyphens=False,
        )
    )


def split_voiceover_lines(voiceover):
    """Split voiceover narration into subtitle-sized lines."""
    cleaned = voiceover.replace("\\n", "\n")
    raw_lines = []

    for paragraph in cleaned.splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        pieces = re.split(r"(?<=[.!?])\s+", paragraph)
        raw_lines.extend(piece.strip() for piece in pieces if piece.strip())

    return raw_lines


def make_voiceover_srt_blocks(lines, total_duration):
    """Build SRT blocks for every voiceover line across the full duration."""
    if not lines:
        return ""

    weights = [max(1, len(line.split())) for line in lines]
    total_weight = sum(weights)
    current_time = 0.0
    blocks = []

    for subtitle_number, (line, weight) in enumerate(zip(lines, weights), start=1):
        start_time = current_time
        if subtitle_number == len(lines):
            end_time = float(total_duration)
        else:
            end_time = start_time + (float(total_duration) * weight / total_weight)

        blocks.append(
            "\n".join(
                [
                    str(subtitle_number),
                    f"{format_timestamp(start_time)} --> {format_timestamp(end_time)}",
                    wrap_caption(line),
                ]
            )
        )
        current_time = end_time

    return "\n\n".join(blocks) + "\n"


def make_srt_blocks(scenes):
    """Build all subtitle blocks as one string."""
    blocks = []
    current_time = 0.0

    for subtitle_number, scene in enumerate(scenes, start=1):
        start_time = current_time
        end_time = start_time + float(scene["duration"])
        caption = wrap_caption(scene["caption"])

        blocks.append(
            "\n".join(
                [
                    str(subtitle_number),
                    f"{format_timestamp(start_time)} --> {format_timestamp(end_time)}",
                    caption,
                ]
            )
        )

        current_time = end_time

    # SRT files separate subtitle blocks with a blank line.
    return "\n\n".join(blocks) + "\n"


def main():
    """Read the episode JSON and write assets/subtitles/episode_01.srt."""
    with EPISODE_PATH.open("r", encoding="utf-8") as file:
        episode = json.load(file)

    SUBTITLE_PATH.parent.mkdir(parents=True, exist_ok=True)

    voiceover_lines = split_voiceover_lines(episode.get("voiceover", ""))
    if voiceover_lines:
        total_duration = sum(float(scene["duration"]) for scene in episode["scenes"])
        subtitle_text = make_voiceover_srt_blocks(voiceover_lines, total_duration)
    else:
        subtitle_text = make_srt_blocks(episode["scenes"])

    SUBTITLE_PATH.write_text(subtitle_text, encoding="utf-8")

    print(f"Created subtitles: {SUBTITLE_PATH}")


if __name__ == "__main__":
    main()
