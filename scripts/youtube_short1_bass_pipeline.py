import argparse
import asyncio
import csv
import json
import math
import re
import subprocess
import wave
from pathlib import Path

import edge_tts


ROOT = Path(r"D:\ai-novel-video-generator\youtube short1 bass")
FFMPEG = Path(r"D:\ffmpeg\bin\ffmpeg.exe")
FFPROBE = Path(r"D:\ffmpeg\bin\ffprobe.exe")
VOICE = "en-US-BrianNeural"
RATE = "-3%"
SAMPLE_RATE = 48000
FPS = 30
SENTENCE_GAP = 0.18
MIN_IMAGES_PER_MINUTE = 8


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


def split_sentences(text: str) -> list[str]:
    text = text.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text.strip())
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


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


async def synthesize(text: str, path: Path) -> None:
    communicator = edge_tts.Communicate(text, VOICE, rate=RATE)
    await communicator.save(str(path))


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


def load_shorts() -> list[dict]:
    with (ROOT / "shorts.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    segments = json.loads((ROOT / "short_segments.json").read_text(encoding="utf-8-sig"))
    segment_by_id = {item["short_id"]: item for item in segments}
    for row in rows:
        segment = segment_by_id[row["short_id"]]
        row["narration_script"] = segment["narration_script"]
        row["ending_line"] = segment.get("ending_line", row.get("ending_line", ""))
        row["emotional_tone"] = segment.get("emotional_tone", "")
    return rows


def load_image_prompts() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    path = ROOT / "image_prompts.jsonl"
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        grouped.setdefault(item["short_id"], []).append(item)
    for items in grouped.values():
        items.sort(key=lambda item: item["scene_id"])
    return grouped


def output_dir(short_id: str) -> Path:
    return ROOT / "output" / "shorts" / short_id


def estimate_seconds(row: dict) -> int:
    match = re.search(r"\d+", row.get("duration_estimate", "90"))
    return int(match.group(0)) if match else 90


def expanded_visual_prompts(row: dict, base_prompts: list[dict]) -> list[dict]:
    if base_prompts:
        return list(base_prompts)
    target = max(len(base_prompts), math.ceil(estimate_seconds(row) / 60 * MIN_IMAGES_PER_MINUTE), 8)
    prompts = list(base_prompts)
    sentences = split_sentences(row["narration_script"])
    style = (
        "Vertical 9:16 composition, cinematic short-form fishing documentary still, realistic but polished, "
        "dramatic natural lake light, high production value, professional color grading, no text, no logos, "
        "no watermark, keep the same main character: focused male angler in his mid-30s, light skin, short dark hair, "
        "trimmed beard, unbranded olive waterproof jacket, dark unbranded baseball cap, tan fishing vest, black waders, "
        "graphite spinning rod. Keep the subject centered with open lower safe area for subtitles."
    )
    while len(prompts) < target:
        index = len(prompts) + 1
        sentence = sentences[min(len(sentences) - 1, round((index - 1) * (len(sentences) - 1) / max(1, target - 1)))]
        prompts.append(
            {
                "short_id": row["short_id"],
                "scene_id": f"{row['short_id']}_scene_{index:02}",
                "image_prompt": (
                    f"{style} Visualize this story beat: {sentence} "
                    f"Topic: {row['short_title']}. Mood: {row.get('emotional_tone', '')}. "
                    "Use a different camera angle from nearby scenes, but keep character identity and wardrobe consistent."
                ),
            }
        )
    return prompts[:target]


def prepare() -> None:
    shorts = load_shorts()
    prompt_map = load_image_prompts()
    summary = []
    for row in shorts:
        short_id = row["short_id"]
        folder = output_dir(short_id)
        for sub in ("images", "audio_segments", "audio_wav", "_clips"):
            (folder / sub).mkdir(parents=True, exist_ok=True)
        script = row["narration_script"].strip()
        (folder / f"{short_id}_script.txt").write_text(script + "\n", encoding="utf-8")
        sentences = split_sentences(script)
        prompts = expanded_visual_prompts(row, prompt_map.get(short_id, []))
        scenes = []
        for idx, item in enumerate(prompts, start=1):
            scenes.append(
                {
                    "index": idx,
                    "scene_id": item["scene_id"],
                    "image": f"{short_id}_scene_{idx:02}.png",
                    "visual_prompt": item["image_prompt"],
                }
            )
        manifest = {
            "short_id": short_id,
            "short_title": row["short_title"],
            "platform_title": row["platform_title"],
            "hook": row["hook"],
            "main_topic": row["main_topic"],
            "ending_line": row["ending_line"],
            "sentences": sentences,
            "scenes": scenes,
        }
        (folder / f"{short_id}_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        with (folder / f"{short_id}_storyboard.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["index", "scene_id", "image", "visual_prompt"])
            writer.writeheader()
            writer.writerows(scenes)
        summary.append({"short_id": short_id, "title": row["short_title"], "scenes": len(scenes), "sentences": len(sentences)})
    (ROOT / "output" / "shorts" / "shorts_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


async def build_audio() -> None:
    for row in load_shorts():
        short_id = row["short_id"]
        folder = output_dir(short_id)
        manifest = json.loads((folder / f"{short_id}_manifest.json").read_text(encoding="utf-8"))
        flat = [{"sequence": i, "text": text} for i, text in enumerate(manifest["sentences"], start=1)]
        for item in flat:
            mp3_path = folder / "audio_segments" / f"segment_{item['sequence']:03}.mp3"
            wav_path = folder / "audio_wav" / f"segment_{item['sequence']:03}.wav"
            if not mp3_path.exists() or mp3_path.stat().st_size == 0:
                print(f"{short_id} synth {item['sequence']:03}: {item['text'][:70]}")
                await synthesize(item["text"], mp3_path)
            if not wav_path.exists() or wav_path.stat().st_size == 0:
                to_wav(mp3_path, wav_path)

        output_frames = bytearray()
        cursor = 0.0
        sentence_timings = []
        for index, item in enumerate(flat, start=1):
            wav_path = folder / "audio_wav" / f"segment_{item['sequence']:03}.wav"
            frames, duration = read_wav(wav_path)
            start = cursor
            output_frames.extend(frames)
            cursor += duration
            end = cursor
            sentence_timings.append({**item, "start": start, "end": end, "duration": duration})
            if index < len(flat):
                silence_frames = int(round(SENTENCE_GAP * SAMPLE_RATE))
                output_frames.extend(b"\x00\x00" * silence_frames)
                cursor += silence_frames / SAMPLE_RATE

        wav_voice = folder / f"{short_id}_voice.wav"
        with wave.open(str(wav_voice), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(bytes(output_frames))
        mp3_voice = folder / f"{short_id}_voice.mp3"
        run([str(FFMPEG), "-y", "-loglevel", "error", "-i", str(wav_voice), "-c:a", "libmp3lame", "-b:a", "192k", str(mp3_voice)])

        timing = build_scene_timing(manifest, sentence_timings, cursor)
        (folder / f"{short_id}_timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")
        write_srt(folder, short_id, timing)
        print(f"{short_id} duration {cursor:.3f}s")


def build_scene_timing(manifest: dict, sentence_timings: list[dict], total_duration: float) -> dict:
    scene_count = len(manifest["scenes"])
    sentence_count = len(sentence_timings)
    boundaries = [0]
    for i in range(1, scene_count):
        target = round(i * sentence_count / scene_count)
        target = max(boundaries[-1] + 1, min(target, sentence_count - (scene_count - i)))
        boundaries.append(target)
    boundaries.append(sentence_count)

    scenes = []
    for i in range(scene_count):
        start_sentence = boundaries[i]
        end_sentence = boundaries[i + 1]
        start = sentence_timings[start_sentence]["start"]
        end = sentence_timings[end_sentence]["start"] if end_sentence < sentence_count else total_duration
        scene = manifest["scenes"][i]
        scenes.append({**scene, "start": start, "end": end, "duration": end - start})
    return {"duration": total_duration, "sentences": sentence_timings, "scenes": scenes}


def write_srt(folder: Path, short_id: str, timing: dict) -> None:
    lines = []
    for idx, item in enumerate(timing["sentences"], start=1):
        lines.extend([str(idx), f"{srt_time(item['start'])} --> {srt_time(item['end'])}", item["text"], ""])
    (folder / f"{short_id}.srt").write_text("\n".join(lines), encoding="utf-8")


def write_ass(folder: Path, short_id: str, timing: dict) -> Path:
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: English,Arial,56,&H00FFFFFF,&H00FFFFFF,&H00000000,&H7A000000,0,0,0,0,100,100,0,0,1,4.0,1.0,2,70,70,210,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for sentence in timing["sentences"]:
        lines.append(f"Dialogue: 0,{ass_time(sentence['start'])},{ass_time(sentence['end'])},English,,0,0,0,,{ass_escape(sentence['text'])}")
    path = folder / f"{short_id}.ass"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def motion_filter(index: int, frames: int) -> str:
    last = max(1, frames - 1)
    if index % 3 == 0:
        zoom = f"1.020-0.020*on/{last}"
    else:
        zoom = f"1+0.024*on/{last}"
    x = "iw/2-(iw/zoom/2)"
    y = "ih/2-(ih/zoom/2)"
    return (
        "scale=2160:3840:force_original_aspect_ratio=increase,"
        "crop=2160:3840,"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s=1080x1920:fps={FPS},"
        "format=yuv420p"
    )


def make_music(folder: Path, duration: float) -> Path:
    music = folder / "background_music.mp3"
    run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"anoisesrc=color=brown:amplitude=0.045:duration={duration + 2}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=86:sample_rate=48000:duration={duration + 2}",
            "-filter_complex",
            "[0:a]lowpass=f=1100,volume=0.13[a0];[1:a]volume=0.014[a1];"
            "[a0][a1]amix=inputs=2:duration=longest,"
            f"afade=t=in:st=0:d=2,afade=t=out:st={max(0, duration - 4):.3f}:d=4",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(music),
        ]
    )
    return music


def build_video(short_id: str | None = None) -> None:
    rows = [row for row in load_shorts() if short_id is None or row["short_id"] == short_id]
    for row in rows:
        sid = row["short_id"]
        folder = output_dir(sid)
        timing = json.loads((folder / f"{sid}_timing.json").read_text(encoding="utf-8"))
        clips = []
        for scene in timing["scenes"]:
            image = folder / "images" / scene["image"]
            if not image.exists():
                raise FileNotFoundError(image)
            clip = folder / "_clips" / f"{Path(scene['image']).stem}.mp4"
            duration = float(scene["duration"])
            frames = max(1, math.ceil(duration * FPS))
            if not clip.exists() or abs(probe_duration(clip) - frames / FPS) > 0.08:
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
                        motion_filter(int(scene["index"]), frames),
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

        concat_list = folder / "clips.txt"
        concat_list.write_text("\n".join(f"file '{clip.as_posix()}'" for clip in clips) + "\n", encoding="utf-8")
        video_only = folder / "video_only.mp4"
        run([str(FFMPEG), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(video_only)])
        voice = folder / f"{sid}_voice.mp3"
        music = make_music(folder, float(timing["duration"]))
        mixed = folder / "video_with_audio.mp4"
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
                "[1:a]volume=1.0[a1];[2:a]volume=0.16[a2];[a1][a2]amix=inputs=2:duration=first:dropout_transition=2[a]",
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
                str(mixed),
            ]
        )
        ass = write_ass(folder, sid, timing)
        final = folder / f"final_{sid}.mp4"
        run(
            [
                str(FFMPEG),
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(mixed),
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


def audit() -> None:
    rows = load_shorts()
    report = []
    for row in rows:
        sid = row["short_id"]
        folder = output_dir(sid)
        manifest_path = folder / f"{sid}_manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        images = []
        missing = []
        for scene in manifest["scenes"]:
            path = folder / "images" / scene["image"]
            (images if path.exists() and path.stat().st_size > 0 else missing).append(str(path))
        final = folder / f"final_{sid}.mp4"
        duration = probe_duration(final) if final.exists() else None
        report.append({"short_id": sid, "title": manifest["short_title"], "duration": duration, "images": len(images), "missing": len(missing), "final": str(final)})
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["prepare", "audio", "video", "audit"])
    parser.add_argument("--short-id")
    args = parser.parse_args()
    if args.step == "prepare":
        prepare()
    elif args.step == "audio":
        asyncio.run(build_audio())
    elif args.step == "video":
        build_video(args.short_id)
    elif args.step == "audit":
        audit()


if __name__ == "__main__":
    main()
