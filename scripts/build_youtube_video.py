import asyncio
import argparse
import csv
import math
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from textwrap import wrap


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(r"C:\Users\11847\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")


@dataclass
class Segment:
    scene_index: int
    text: str
    start: float
    end: float


def run(command: list[str], label: str) -> None:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"{label} failed:\n{detail}")


def ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return float(result.stdout.strip())


def resolve_project(value: str) -> Path:
    project = Path(value)
    if not project.is_absolute():
        project = ROOT / project
    return project.resolve()


def find_scenes_csv(project: Path) -> Path:
    candidates = [
        project / "scenes.csv",
        *sorted(project.glob("*_scenes.csv")),
        *sorted(project.glob("*_prompts.csv")),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Missing scenes CSV in {project}")


def read_scenes(project: Path) -> list[dict[str, str]]:
    scenes_csv = find_scenes_csv(project)
    with scenes_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        scenes = list(csv.DictReader(handle))
    for scene in scenes:
        if "narration" not in scene and scene.get("narration_sentence"):
            scene["narration"] = scene["narration_sentence"]
        if "scene_id" not in scene and scene.get("sentence_id"):
            scene["scene_id"] = scene["sentence_id"]
    return scenes


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part.strip() for part in parts if part.strip()]


def srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def ass_escape(path: Path) -> str:
    return path.resolve().as_posix().replace(":", "\\:")


async def edge_tts_to_mp3(text: str, output: Path) -> None:
    import edge_tts

    output.parent.mkdir(parents=True, exist_ok=True)
    communicate = edge_tts.Communicate(
        text=text,
        voice="en-US-BrianNeural",
        rate="-2%",
        volume="+0%",
    )
    await communicate.save(str(output))


async def generate_voice_segments(project: Path, scenes: list[dict[str, str]]) -> tuple[list[Segment], Path]:
    voice_dir = project / "audio" / "voice_segments"
    wav_dir = project / "audio" / "voice_wav"
    voice_dir.mkdir(parents=True, exist_ok=True)
    wav_dir.mkdir(parents=True, exist_ok=True)

    segments: list[Segment] = []
    audio_wavs: list[Path] = []
    cursor = 0.0
    segment_id = 0

    for scene_index, scene in enumerate(scenes, start=1):
        for sentence in split_sentences(scene["narration"]):
            segment_id += 1
            mp3 = voice_dir / f"segment_{segment_id:03}.mp3"
            wav = wav_dir / f"segment_{segment_id:03}.wav"
            if not mp3.exists():
                await edge_tts_to_mp3(sentence, mp3)
            if not wav.exists():
                run(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        str(mp3),
                        "-ar",
                        "44100",
                        "-ac",
                        "2",
                        str(wav),
                    ],
                    f"Convert voice segment {segment_id}",
                )
            duration = ffprobe_duration(wav)
            segments.append(Segment(scene_index, sentence, cursor, cursor + duration))
            audio_wavs.append(wav)
            cursor += duration

    final_wav = project / "audio" / "voiceover_edge_brian_synced.wav"
    with wave.open(str(final_wav), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(44100)
        for wav in audio_wavs:
            with wave.open(str(wav), "rb") as source:
                output.writeframes(source.readframes(source.getnframes()))

    final_mp3 = project / "audio" / "voiceover_edge_brian_synced.mp3"
    run(["ffmpeg", "-y", "-i", str(final_wav), "-codec:a", "libmp3lame", "-q:a", "2", str(final_mp3)], "Encode voiceover")
    return segments, final_mp3


def write_subtitles(project: Path, segments: list[Segment]) -> Path:
    subtitle_dir = project / "subtitles"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    path = subtitle_dir / "subtitles.srt"
    blocks = []
    for index, segment in enumerate(segments, start=1):
        caption = "\n".join(wrap(segment.text, width=42, break_long_words=False))
        blocks.append(f"{index}\n{srt_time(segment.start)} --> {srt_time(segment.end)}\n{caption}")
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return path


def scene_timings(segments: list[Segment], scene_count: int) -> list[tuple[float, float]]:
    timings = []
    for scene_index in range(1, scene_count + 1):
        scene_segments = [segment for segment in segments if segment.scene_index == scene_index]
        timings.append((scene_segments[0].start, scene_segments[-1].end))
    return timings


def normalize_camera_motion(value: str) -> str:
    value = value.lower()
    if "pull" in value or "out" in value:
        return "zoom_out"
    if "left" in value:
        return "pan_left"
    if "right" in value:
        return "pan_right"
    return "zoom_in"


def zoompan_filter(motion: str, width: int, height: int, frames: int, fps: int) -> str:
    base = f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase"
    if motion == "zoom_out":
        zoom = "z='if(eq(on,1),1.08,max(1.01,zoom-0.0006))'"
        x = "x='iw/2-(iw/zoom/2)'"
        y = "y='ih/2-(ih/zoom/2)'"
    elif motion == "pan_left":
        zoom = "z='1.06'"
        x = f"x='(iw-iw/zoom)*(1-on/{frames})'"
        y = "y='ih/2-(ih/zoom/2)'"
    elif motion == "pan_right":
        zoom = "z='1.06'"
        x = f"x='(iw-iw/zoom)*on/{frames}'"
        y = "y='ih/2-(ih/zoom/2)'"
    else:
        zoom = "z='min(1.08,1+on*0.0006)'"
        x = "x='iw/2-(iw/zoom/2)'"
        y = "y='ih/2-(ih/zoom/2)'"
    return f"{base},zoompan={zoom}:d={frames}:s={width}x{height}:fps={fps}:{x}:{y},format=yuv420p"


def render_scene_clips(project: Path, scenes: list[dict[str, str]], timings: list[tuple[float, float]]) -> list[Path]:
    width, height, fps = 1920, 1080, 30
    clip_dir = project / "output" / "_clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    for index, scene in enumerate(scenes, start=1):
        image = project / "images" / f"scene_{index:02}.png"
        if not image.exists():
            raise FileNotFoundError(f"Missing image: {image}")
        start, end = timings[index - 1]
        duration = end - start
        frames = max(1, int(math.ceil(duration * fps)))
        clip = clip_dir / f"scene_{index:03}.mp4"
        motion = normalize_camera_motion(scene.get("camera_motion", "slow push in"))
        run(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(image),
                "-frames:v",
                str(frames),
                "-vf",
                zoompan_filter(motion, width, height, frames, fps),
                "-an",
                "-r",
                str(fps),
                str(clip),
            ],
            f"Render scene {index}",
        )
        clips.append(clip)
    return clips


def concat_clips(project: Path, clips: list[Path]) -> Path:
    concat_path = project / "output" / "_clips" / "clips.txt"
    silent_video = project / "output" / "_clips" / "silent_video.mp4"
    lines = [f"file '{clip.resolve().as_posix()}'" for clip in clips]
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", str(silent_video)], "Concat clips")
    return silent_video


def ensure_background_music(project: Path, duration: float) -> Path:
    audio_dir = project / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    candidates = [
        audio_dir / "background_music.mp3",
        project / "music" / "background.mp3",
        ROOT / "MC VEDIO" / "audio" / "background_music.mp3",
    ]
    for candidate in candidates:
        if candidate.exists():
            target = audio_dir / "background_music.mp3"
            if candidate.resolve() != target.resolve():
                shutil.copy2(candidate, target)
            return target

    target = audio_dir / "background_music.mp3"
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=110:sample_rate=44100",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=color=pink:amplitude=0.12:sample_rate=44100",
            "-filter_complex",
            f"[0:a]volume=0.025[a0];[1:a]volume=0.02[a1];[a0][a1]amix=inputs=2:duration=longest,atrim=0:{duration:.3f},afade=t=in:st=0:d=3,afade=t=out:st={max(duration - 4, 0):.3f}:d=4",
            "-c:a",
            "libmp3lame",
            str(target),
        ],
        "Generate background music",
    )
    return target


def subtitle_force_style() -> str:
    return (
        "FontName=Arial,"
        "FontSize=24,"
        "PrimaryColour=&HFFFFFF,"
        "OutlineColour=&H000000,"
        "BackColour=&H66000000,"
        "BorderStyle=1,"
        "Outline=1.5,"
        "Shadow=0,"
        "Alignment=2,"
        "MarginV=56"
    )


def mux_final(project: Path, video: Path, voice: Path, subtitles: Path, duration: float) -> Path:
    output = project / "output" / "final_youtube_video.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    music = ensure_background_music(project, duration)
    style = subtitle_force_style()
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-i",
            str(voice),
            "-stream_loop",
            "-1",
            "-i",
            str(music),
            "-filter_complex",
            (
                f"[0:v]subtitles='{ass_escape(subtitles)}':force_style='{style}'[v];"
                "[1:a]volume=1.0[a1];[2:a]volume=0.09,atrim=0:"
                f"{duration:.3f}[a2];[a1][a2]amix=inputs=2:duration=first:dropout_transition=0[a]"
            ),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output),
        ],
        "Mux final video",
    )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a horizontal YouTube video from a project folder.")
    parser.add_argument("--project", default="youtube1", help="Project folder path, absolute or relative to repo root.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    project = resolve_project(args.project)
    scenes = read_scenes(project)
    segments, voice = await generate_voice_segments(project, scenes)
    subtitles = write_subtitles(project, segments)
    timings = scene_timings(segments, len(scenes))
    clips = render_scene_clips(project, scenes, timings)
    silent_video = concat_clips(project, clips)
    final = mux_final(project, silent_video, voice, subtitles, segments[-1].end)
    print(final)


if __name__ == "__main__":
    asyncio.run(main())
