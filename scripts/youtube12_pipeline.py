import argparse
import csv
import json
import math
import re
import subprocess
import wave
from pathlib import Path

import edge_tts


ROOT = Path(r"D:\ai-novel-video-generator\youtube12 lobster")
PKG = ROOT
FFMPEG = Path(r"D:\ffmpeg\bin\ffmpeg.exe")
FFPROBE = Path(r"D:\ffmpeg\bin\ffprobe.exe")
VOICE = "en-US-BrianNeural"
RATE = "-3%"
SAMPLE_RATE = 48000
FPS = 30
SENTENCE_GAP = 0.22
SCENE_SENTENCE_RANGES = [
    (0, 7),
    (7, 10),
    (10, 11),
    (11, 17),
    (17, 21),
    (21, 25),
    (25, 30),
    (30, 33),
    (33, 40),
    (40, 45),
    (45, 53),
    (53, 55),
]


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]


def run(command: list[str]) -> None:
    print(" ".join(command), flush=True)
    subprocess.run(command, check=True)


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
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
        text=True,
    )
    return float(out.strip())


def to_wav(mp3_path: Path, wav_path: Path) -> None:
    run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(mp3_path),
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ]
    )


def read_wav(path: Path) -> tuple[bytes, float]:
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != SAMPLE_RATE or handle.getnchannels() != 1:
            raise ValueError(f"Unexpected WAV format: {path}")
        frames = handle.readframes(handle.getnframes())
        duration = handle.getnframes() / handle.getframerate()
    return frames, duration


async def synthesize(text: str, path: Path) -> None:
    communicator = edge_tts.Communicate(text, VOICE, rate=RATE)
    await communicator.save(str(path))


def srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, centiseconds = divmod(centiseconds, 360_000)
    minutes, centiseconds = divmod(centiseconds, 6_000)
    secs, centiseconds = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{centiseconds:02}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def ffmpeg_filter_path(path: Path) -> str:
    value = path.resolve().as_posix()
    return value.replace(":", r"\:").replace("'", r"\'")


def load_rows() -> list[dict]:
    with (PKG / "scenes.csv").open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_prompts() -> dict[str, dict]:
    prompts = {}
    path = PKG / "image_prompts.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            prompts[item["scene_id"]] = item
    return prompts


def prepare() -> None:
    rows = load_rows()
    prompts = load_prompts()
    full_script = (PKG / "full_script.txt").read_text(encoding="utf-8")
    script_sentences = split_sentences(full_script)
    if len(script_sentences) != SCENE_SENTENCE_RANGES[-1][1]:
        raise ValueError(f"Expected 55 script sentences, found {len(script_sentences)}")
    script_blocks = [" ".join(script_sentences[start:end]) for start, end in SCENE_SENTENCE_RANGES]
    if len(script_blocks) != len(rows):
        raise ValueError(f"Expected one script block per scene: {len(script_blocks)} blocks for {len(rows)} scenes")
    for folder in ("images", "audio/voice_segments", "audio/voice_wav", "subtitles", "output/_clips"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)

    sequence = []
    for index, (row, narration) in enumerate(zip(rows, script_blocks), start=1):
        prompt = prompts.get(row["scene_id"], {})
        scene = {
            "index": index,
            "scene_id": row["scene_id"],
            "type": "story_image",
            "title": row.get("scene_title", ""),
            "narration": narration,
            "sentences": split_sentences(narration),
            "visual_summary": row.get("visual_description", ""),
            "camera": row.get("camera_motion", ""),
            "visual_prompt": prompt.get("image_prompt", row.get("image_prompt", "")),
        }
        sequence.append(scene)

    script_sentences = [sentence for scene in sequence for sentence in scene["sentences"]]
    (ROOT / "narration_en.json").write_text(
        json.dumps({"scenes": sequence, "sentences": script_sentences}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"Prepared {len(sequence)} scenes, "
        f"{len(sequence)} story images, "
        f"{len(script_sentences)} spoken sentences"
    )


async def build_audio() -> None:
    prepared = json.loads((ROOT / "narration_en.json").read_text(encoding="utf-8"))
    scenes = prepared["scenes"]
    seg_dir = ROOT / "audio" / "voice_segments"
    wav_dir = ROOT / "audio" / "voice_wav"
    voice_wav = ROOT / "audio" / "voiceover_brian.wav"
    voice_mp3 = ROOT / "audio" / "voiceover_brian.mp3"
    timing_path = ROOT / "subtitles" / "timing.json"
    srt_path = ROOT / "subtitles" / "subtitles_en.srt"
    script_path = ROOT / "subtitles" / "narration_en.txt"

    flat = []
    sequence = 0
    for scene in scenes:
        for text in scene["sentences"]:
            sequence += 1
            flat.append(
                {
                    "sequence": sequence,
                    "scene_index": scene["index"],
                    "scene_id": scene["scene_id"],
                    "text": text,
                }
            )

    for item in flat:
        mp3_path = seg_dir / f"segment_{item['sequence']:03}.mp3"
        wav_path = wav_dir / f"segment_{item['sequence']:03}.wav"
        if not mp3_path.exists() or mp3_path.stat().st_size == 0:
            print(f"Synthesizing {item['sequence']:03}: {item['text'][:70]}")
            await synthesize(item["text"], mp3_path)
        if not wav_path.exists() or wav_path.stat().st_size == 0:
            to_wav(mp3_path, wav_path)
        mp3_dur = probe_duration(mp3_path)
        wav_dur = probe_duration(wav_path)
        if abs(mp3_dur - wav_dur) > 0.08:
            wav_path.unlink(missing_ok=True)
            to_wav(mp3_path, wav_path)
            wav_dur = probe_duration(wav_path)
        if abs(mp3_dur - wav_dur) > 0.08:
            raise RuntimeError(f"Duration mismatch after regen: {mp3_path.name} {mp3_dur} vs {wav_dur}")

    scene_timings = []
    sentence_timings = []
    output_frames = bytearray()
    cursor = 0.0

    def add_silence(seconds: float) -> None:
        nonlocal cursor
        frames = int(round(seconds * SAMPLE_RATE))
        output_frames.extend(b"\x00\x00" * frames)
        cursor += frames / SAMPLE_RATE

    for index, item in enumerate(flat, start=1):
        wav_path = wav_dir / f"segment_{item['sequence']:03}.wav"
        frames, duration = read_wav(wav_path)
        sentence_start = cursor
        output_frames.extend(frames)
        cursor += duration
        sentence_end = cursor
        sentence_timings.append({**item, "start": sentence_start, "end": sentence_end, "duration": duration})
        if index < len(flat):
            add_silence(SENTENCE_GAP)

    total_voice_duration = cursor
    first_sentence_by_scene = {
        scene["index"]: next(s for s in sentence_timings if s["scene_index"] == scene["index"])
        for scene in scenes
    }
    for sequence_index, scene in enumerate(scenes):
        scene_start = first_sentence_by_scene[scene["index"]]["start"]
        if sequence_index + 1 < len(scenes):
            scene_end = first_sentence_by_scene[scenes[sequence_index + 1]["index"]]["start"]
        else:
            scene_end = total_voice_duration
        scene_timings.append(
            {
                "scene_index": scene["index"],
                "scene_id": scene["scene_id"],
                "type": scene["type"],
                "start": scene_start,
                "end": scene_end,
                "duration": scene_end - scene_start,
            }
        )

    with wave.open(str(voice_wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(output_frames))

    run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(voice_wav),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(voice_mp3),
        ]
    )

    srt_lines = []
    for idx, sentence in enumerate(sentence_timings, start=1):
        srt_lines.extend(
            [
                str(idx),
                f"{srt_time(sentence['start'])} --> {srt_time(sentence['end'])}",
                sentence["text"],
                "",
            ]
        )
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    script_path.write_text("\n".join(s["text"] for s in sentence_timings), encoding="utf-8")
    timing_path.write_text(
        json.dumps({"scenes": scene_timings, "sentences": sentence_timings}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Voice duration: {cursor:.3f}s, sentences: {len(sentence_timings)}")


def write_english_ass() -> Path:
    timing = json.loads((ROOT / "subtitles" / "timing.json").read_text(encoding="utf-8"))
    lines = [
        "[Script Info]",
        "Title: YouTube12 English Subtitles",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: English,Arial,38,&H00FFFFFF,&H00FFFFFF,&H00000000,&H70000000,0,0,0,0,100,100,0,0,1,2.4,0.6,2,140,140,48,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for sentence in timing["sentences"]:
        lines.append(
            f"Dialogue: 0,{ass_time(sentence['start'])},{ass_time(sentence['end'])},English,,0,0,0,,{ass_escape(sentence['text'])}"
        )
    path = ROOT / "subtitles" / "subtitles_en.ass"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def motion_filter(index: int, frames: int) -> str:
    last = max(1, frames - 1)
    zoom = (
        f"1+0.028*on/{last}"
        if index % 2
        else f"1.028-0.028*on/{last}"
    )
    return (
        "scale=7680:4320:force_original_aspect_ratio=increase,"
        "crop=7680:4320,"
        f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s=1920x1080:fps={FPS},"
        "format=yuv420p"
    )


def build_clips() -> list[Path]:
    timing = json.loads((ROOT / "subtitles" / "timing.json").read_text(encoding="utf-8"))
    clips_dir = ROOT / "output" / "_clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clips = []
    for scene in timing["scenes"]:
        index = scene["scene_index"]
        image = ROOT / "images" / f"scene_{index:02}.png"
        clip = clips_dir / f"scene_{index:02}.mp4"
        if not image.exists():
            raise FileNotFoundError(image)
        duration = float(scene["duration"])
        frames = max(1, math.ceil(duration * FPS))
        if clip.exists() and clip.stat().st_size > 0:
            actual = probe_duration(clip)
            if abs(actual - frames / FPS) < 0.08:
                clips.append(clip)
                continue
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


def build_video() -> None:
    output = ROOT / "output"
    clips = build_clips()
    concat_list = output / "clips.txt"
    concat_list.write_text("\n".join(f"file '{clip.as_posix()}'" for clip in clips) + "\n", encoding="utf-8")
    video_only = output / "video_only.mp4"
    voice = ROOT / "audio" / "voiceover_brian.mp3"
    music = output / "ambient_music.mp3"
    no_sub = output / "final_youtube_video_no_subtitles.mp4"
    final = output / "final_youtube_video.mp4"
    ass = write_english_ass()
    voice_duration = probe_duration(voice)

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
            str(concat_list),
            "-c",
            "copy",
            str(video_only),
        ]
    )
    run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"anoisesrc=color=brown:amplitude=0.055:duration={voice_duration + 2}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=73:sample_rate=48000:duration={voice_duration + 2}",
            "-filter_complex",
            "[0:a]lowpass=f=950,volume=0.16[a0];[1:a]volume=0.018[a1];[a0][a1]amix=inputs=2:duration=longest,afade=t=in:st=0:d=3,afade=t=out:st="
            + f"{max(0, voice_duration - 5):.3f}:d=5",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(music),
        ]
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
            "[1:a]volume=1.0[a1];[2:a]volume=0.18[a2];[a1][a2]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(no_sub),
        ]
    )
    run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(no_sub),
            "-vf",
            f"subtitles=filename='{ffmpeg_filter_path(ass)}':charenc=UTF-8",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "copy",
            str(final),
        ]
    )
    print(final)


def audit_images() -> None:
    prepared = json.loads((ROOT / "narration_en.json").read_text(encoding="utf-8"))
    rows = prepared["scenes"]
    missing = []
    for row in rows:
        index = row["index"]
        path = ROOT / "images" / f"scene_{index:02}.png"
        if not path.exists() or path.stat().st_size == 0:
            missing.append(index)
    print(json.dumps({"total": len(rows), "missing": missing}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["prepare", "audio", "video", "audit-images"])
    args = parser.parse_args()
    if args.step == "prepare":
        prepare()
    elif args.step == "audio":
        import asyncio

        asyncio.run(build_audio())
    elif args.step == "video":
        build_video()
    elif args.step == "audit-images":
        audit_images()


if __name__ == "__main__":
    main()
