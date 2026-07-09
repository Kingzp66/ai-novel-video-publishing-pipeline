from pathlib import Path
from textwrap import wrap
from typing import Any

from utils import read_text_file


def format_srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def subtitle_source_path(project: Path) -> Path:
    subtitle_script = project / "subtitle_script.txt"
    if subtitle_script.is_file():
        return subtitle_script
    return project / "script.txt"


def split_subtitle_text(text: str, count: int) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return [""] * count
    if len(lines) >= count:
        head = lines[: count - 1]
        tail = " ".join(lines[count - 1 :])
        return head + ([tail] if count else [])

    joined = " ".join(lines)
    wrapped = wrap(joined, width=max(40, len(joined) // max(count, 1)), break_long_words=False)
    if len(wrapped) >= count:
        return wrapped[: count - 1] + [" ".join(wrapped[count - 1 :])]

    padded = wrapped[:]
    while len(padded) < count:
        padded.append("")
    return padded


def wrap_subtitle_line(text: str, width: int = 38) -> str:
    if not text:
        return ""
    return "\n".join(wrap(text, width=width, break_long_words=False)) or text


def build_subtitle_blocks(text: str, scenes: list[dict[str, Any]]) -> str:
    subtitles = split_subtitle_text(text, len(scenes))
    blocks = []
    for index, scene in enumerate(scenes, start=1):
        start = format_srt_time(float(scene["start_time"]))
        end = format_srt_time(float(scene["end_time"]))
        caption = wrap_subtitle_line(subtitles[index - 1])
        blocks.append(f"{index}\n{start} --> {end}\n{caption}")
    return "\n\n".join(blocks) + "\n"


def create_subtitles(project: Path, scenes: list[dict[str, Any]]) -> Path:
    text = read_text_file(subtitle_source_path(project))
    output_path = project / "generated_subtitles" / "subtitles.srt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_subtitle_blocks(text, scenes), encoding="utf-8")
    return output_path
