import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(r"D:\ai-novel-video-generator\youtube5")
IMAGES = ROOT / "images"
AUDIO = ROOT / "audio"
SUBTITLES = ROOT / "subtitles"
OUTPUT = ROOT / "output"
CLIPS = OUTPUT / "_clips"
FFMPEG = Path(r"D:\ffmpeg\bin\ffmpeg.exe")
FFPROBE = Path(r"D:\ffmpeg\bin\ffprobe.exe")
FPS = 30


def run(command: list[str]) -> None:
    print(" ".join(command), flush=True)
    subprocess.run(command, check=True)


def ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, centiseconds = divmod(centiseconds, 360_000)
    minutes, centiseconds = divmod(centiseconds, 6_000)
    secs, centiseconds = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{centiseconds:02}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def write_bilingual_ass(timing: dict, translations: list[str]) -> Path:
    sentences = timing["sentences"]
    if len(sentences) != len(translations):
        raise ValueError("English and Chinese subtitle counts do not match")

    lines = [
        "[Script Info]",
        "Title: Hawaiian Rolls Bilingual Subtitles",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Bilingual,Microsoft YaHei UI,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2.2,0,2,120,120,48,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for sentence, chinese in zip(sentences, translations):
        english = ass_escape(sentence["text"])
        chinese = ass_escape(chinese)
        text = rf"{{\fnArial\fs36}}{english}\N{{\fnMicrosoft YaHei UI\fs40}}{chinese}"
        lines.append(
            f"Dialogue: 0,{ass_time(sentence['start'])},{ass_time(sentence['end'])},Bilingual,,0,0,0,,{text}"
        )
    path = SUBTITLES / "bilingual_en_zh.ass"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def motion_filter(index: int, frames: int) -> str:
    last = max(1, frames - 1)
    patterns = [
        f"z='1+0.055*on/{last}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
        f"z='1.055-0.055*on/{last}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
        f"z='1.045':x='(iw-iw/zoom)*on/{last}':y='ih/2-(ih/zoom/2)'",
        f"z='1.045':x='(iw-iw/zoom)*(1-on/{last})':y='ih/2-(ih/zoom/2)'",
        f"z='1.05':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(1-on/{last})'",
        f"z='1.05':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/{last}'",
    ]
    motion = patterns[(index - 1) % len(patterns)]
    return (
        "scale=1920:1080:force_original_aspect_ratio=increase,"
        "crop=1920:1080,"
        f"zoompan={motion}:d={frames}:s=1920x1080:fps={FPS},"
        "format=yuv420p"
    )


def build_scene_clips(scene_timings: list[dict]) -> list[Path]:
    CLIPS.mkdir(parents=True, exist_ok=True)
    clips = []
    for index, scene in enumerate(scene_timings, start=1):
        image = IMAGES / f"scene_{index:02}.png"
        clip = CLIPS / f"scene_{index:02}.mp4"
        if not image.exists():
            raise FileNotFoundError(image)
        if clip.exists() and clip.stat().st_size > 0:
            clips.append(clip)
            continue
        duration = float(scene["duration"])
        frames = max(1, round(duration * FPS))
        run(
            [
                str(FFMPEG),
                "-y",
                "-loglevel",
                "error",
                "-loop",
                "1",
                "-i",
                str(image),
                "-vf",
                motion_filter(index, frames),
                "-frames:v",
                str(frames),
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
                str(FPS),
                str(clip),
            ]
        )
        clips.append(clip)
    return clips


def concat_clips(clips: list[Path]) -> Path:
    concat_file = OUTPUT / "clips_concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{clip.as_posix()}'" for clip in clips) + "\n",
        encoding="utf-8",
    )
    video_only = OUTPUT / "video_only.mp4"
    if video_only.exists() and video_only.stat().st_size > 0:
        return video_only
    run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(video_only),
        ]
    )
    return video_only


def mix_audio(video_only: Path, voice: Path, music: Path, output: Path) -> None:
    filter_graph = (
        "[1:a]volume=1.0,aformat=channel_layouts=stereo,asplit=2[voice_mix][voice_sc];"
        "[2:a]volume=0.075[bg];"
        "[bg][voice_sc]sidechaincompress=threshold=0.018:ratio=10:attack=20:release=450[ducked];"
        "[voice_mix][ducked]amix=inputs=2:duration=first:normalize=0,"
        "alimiter=limit=0.95[aout]"
    )
    run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video_only),
            "-i",
            str(voice),
            "-stream_loop",
            "-1",
            "-i",
            str(music),
            "-filter_complex",
            filter_graph,
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def burn_subtitles(source: Path, ass_path: Path, output: Path) -> None:
    escaped = ass_path.as_posix().replace(":", r"\:")
    run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vf",
            f"ass='{escaped}'",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    timing = json.loads((SUBTITLES / "timing.json").read_text(encoding="utf-8"))
    translations = json.loads((SUBTITLES / "translations_zh.json").read_text(encoding="utf-8"))
    ass_path = write_bilingual_ass(timing, translations)

    music = AUDIO / "background_music.mp3"
    if not music.exists():
        shutil.copy2(
            Path(r"D:\ai-novel-video-generator\youtube4\audio\background_music.mp3"),
            music,
        )

    clips = build_scene_clips(timing["scenes"])
    video_only = concat_clips(clips)
    no_subtitles = OUTPUT / "final_youtube_video_no_subtitles.mp4"
    bilingual = OUTPUT / "final_youtube_video_bilingual_en_zh.mp4"
    mix_audio(video_only, AUDIO / "voiceover_brian.wav", music, no_subtitles)
    burn_subtitles(no_subtitles, ass_path, bilingual)
    shutil.copy2(bilingual, OUTPUT / "final_youtube_video.mp4")
    print(no_subtitles)
    print(bilingual)


if __name__ == "__main__":
    main()
