import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(r"D:\ai-novel-video-generator\youtube6")
OUTPUT = ROOT / "output"
CLIPS = OUTPUT / "_clips"
SUBTITLES = ROOT / "subtitles"
FFMPEG = Path(r"D:\ffmpeg\bin\ffmpeg.exe")
FFPROBE = Path(r"D:\ffmpeg\bin\ffprobe.exe")
TRANSITION = 0.8


def run(command: list[str]) -> None:
    print(" ".join(command), flush=True)
    subprocess.run(command, check=True)


def duration(path: Path) -> float:
    result = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, centiseconds = divmod(centiseconds, 360_000)
    minutes, centiseconds = divmod(centiseconds, 6_000)
    secs, centiseconds = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{centiseconds:02}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def write_bilingual_ass() -> Path:
    timing = json.loads((SUBTITLES / "timing.json").read_text(encoding="utf-8"))
    translations = json.loads((SUBTITLES / "translations_zh.json").read_text(encoding="utf-8"))
    sentences = timing["sentences"]
    if len(sentences) != len(translations):
        raise ValueError(f"Subtitle count mismatch: {len(sentences)} English, {len(translations)} Chinese")

    lines = [
        "[Script Info]",
        "Title: Poppi Bilingual Subtitles",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Bilingual,Microsoft YaHei UI,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H70000000,0,0,0,0,100,100,0,0,1,2.4,0.6,2,120,120,42,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for sentence, chinese in zip(sentences, translations):
        text = rf"{{\fnArial\fs36}}{ass_escape(sentence['text'])}\N{{\fnMicrosoft YaHei UI\fs40}}{ass_escape(chinese)}"
        lines.append(
            f"Dialogue: 0,{ass_time(sentence['start'])},{ass_time(sentence['end'])},Bilingual,,0,0,0,,{text}"
        )

    path = SUBTITLES / "bilingual_en_zh.ass"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_smoothed_video(clips: list[Path], scene_durations: list[float], destination: Path) -> None:
    command = [str(FFMPEG), "-y", "-loglevel", "error"]
    for clip in clips:
        command.extend(["-i", str(clip)])

    filters = []
    for index, scene_duration in enumerate(scene_durations):
        output_duration = scene_duration + (TRANSITION if index < len(clips) - 1 else 0)
        filters.append(
            f"[{index}:v]setpts=PTS-STARTPTS,"
            "tpad=stop_mode=clone:stop_duration=5.0,"
            f"trim=duration={output_duration:.6f},setpts=PTS-STARTPTS[v{index}]"
        )

    previous = "v0"
    cumulative = 0.0
    for index in range(1, len(clips)):
        cumulative += scene_durations[index - 1]
        offset = cumulative
        output_label = f"x{index}"
        filters.append(
            f"[{previous}][v{index}]xfade=transition=fade:duration={TRANSITION}:"
            f"offset={offset:.6f}[{output_label}]"
        )
        previous = output_label

    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{previous}]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-movflags",
            "+faststart",
            str(destination),
        ]
    )
    run(command)


def main() -> None:
    clips = [CLIPS / f"scene_{index:02}.mp4" for index in range(1, 31)]
    for clip in clips:
        if not clip.exists():
            raise FileNotFoundError(clip)

    smooth_video = OUTPUT / "video_only_smooth.mp4"
    smooth_with_audio = OUTPUT / "final_youtube_video_smooth_no_subtitles.mp4"
    final = OUTPUT / "final_youtube_video.mp4"
    backup = OUTPUT / "final_youtube_video_hard_cuts.mp4"
    ass_path = write_bilingual_ass()

    timing = json.loads((SUBTITLES / "timing.json").read_text(encoding="utf-8"))
    scene_durations = [float(scene["duration"]) for scene in timing["scenes"]]
    scene_11_intro_end = float(timing["sentences"][54]["end"])
    scene_10_end = float(timing["scenes"][9]["end"])
    scene_10_hold = scene_11_intro_end - scene_10_end
    scene_durations[9] += scene_10_hold
    scene_durations[10] -= scene_10_hold
    build_smoothed_video(clips, scene_durations, smooth_video)
    run(
        [
            str(FFMPEG), "-y", "-loglevel", "error",
            "-i", str(smooth_video),
            "-i", str(OUTPUT / "final_youtube_video_no_subtitles.mp4"),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c", "copy", "-shortest", "-movflags", "+faststart",
            str(smooth_with_audio),
        ]
    )
    escaped = ass_path.as_posix().replace(":", r"\:")
    corrected = OUTPUT / "final_youtube_video_corrected.mp4"
    run(
        [
            str(FFMPEG), "-y", "-loglevel", "error",
            "-i", str(smooth_with_audio),
            "-vf", f"ass='{escaped}'",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
            str(corrected),
        ]
    )
    if final.exists() and not backup.exists():
        shutil.copy2(final, backup)
    shutil.copy2(corrected, final)
    print(final)


if __name__ == "__main__":
    main()
