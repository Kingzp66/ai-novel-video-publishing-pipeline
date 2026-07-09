import asyncio
import json
import subprocess
import wave
from pathlib import Path

import edge_tts


ROOT = Path(r"D:\ai-novel-video-generator\youtube6")
NARRATION = ROOT / "narration_en.json"
SEGMENT_DIR = ROOT / "audio" / "voice_segments"
WAV_DIR = ROOT / "audio" / "voice_wav"
VOICE_WAV = ROOT / "audio" / "voiceover_brian.wav"
VOICE_MP3 = ROOT / "audio" / "voiceover_brian.mp3"
SRT_PATH = ROOT / "subtitles" / "subtitles_en.srt"
TIMING_PATH = ROOT / "subtitles" / "timing.json"
SCRIPT_PATH = ROOT / "subtitles" / "narration_en.txt"
FFMPEG = Path(r"D:\ffmpeg\bin\ffmpeg.exe")
VOICE = "en-US-BrianNeural"
RATE = "-3%"
SENTENCE_GAP = 0.22
SCENE_GAP = 0.55
SAMPLE_RATE = 48000


def srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


async def synthesize(text: str, path: Path) -> None:
    communicator = edge_tts.Communicate(text, VOICE, rate=RATE)
    await communicator.save(str(path))


def to_wav(mp3_path: Path, wav_path: Path) -> None:
    subprocess.run(
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
        ],
        check=True,
    )


def read_wav(path: Path) -> tuple[bytes, float]:
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != SAMPLE_RATE or handle.getnchannels() != 1:
            raise ValueError(f"Unexpected WAV format: {path}")
        frames = handle.readframes(handle.getnframes())
        duration = handle.getnframes() / handle.getframerate()
    return frames, duration


async def main() -> None:
    scenes = json.loads(NARRATION.read_text(encoding="utf-8"))
    SEGMENT_DIR.mkdir(parents=True, exist_ok=True)
    WAV_DIR.mkdir(parents=True, exist_ok=True)
    SRT_PATH.parent.mkdir(parents=True, exist_ok=True)

    flat = []
    sequence = 1
    for scene_index, scene in enumerate(scenes, start=1):
        for sentence_index, text in enumerate(scene["sentences"], start=1):
            flat.append(
                {
                    "sequence": sequence,
                    "scene_id": scene["scene_id"],
                    "scene_index": scene_index,
                    "sentence_index": sentence_index,
                    "text": text,
                }
            )
            sequence += 1

    for item in flat:
        stem = f"segment_{item['sequence']:03d}"
        mp3_path = SEGMENT_DIR / f"{stem}.mp3"
        wav_path = WAV_DIR / f"{stem}.wav"
        if not mp3_path.exists() or mp3_path.stat().st_size == 0:
            print(f"Synthesizing {stem}: {item['text']}", flush=True)
            await synthesize(item["text"], mp3_path)
        if not wav_path.exists() or wav_path.stat().st_size == 0:
            to_wav(mp3_path, wav_path)

    timeline = []
    scene_timings = []
    cursor = 0.0
    silence_frame = b"\x00\x00"

    with wave.open(str(VOICE_WAV), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)

        for scene_index, scene in enumerate(scenes, start=1):
            scene_start = cursor
            scene_items = [item for item in flat if item["scene_index"] == scene_index]
            for local_index, item in enumerate(scene_items):
                wav_path = WAV_DIR / f"segment_{item['sequence']:03d}.wav"
                frames, duration = read_wav(wav_path)
                start = cursor
                output.writeframes(frames)
                cursor += duration
                end = cursor
                timeline.append({**item, "start": start, "end": end, "duration": duration})

                is_last_sentence = local_index == len(scene_items) - 1
                gap = SCENE_GAP if is_last_sentence else SENTENCE_GAP
                gap_frames = round(gap * SAMPLE_RATE)
                output.writeframes(silence_frame * gap_frames)
                cursor += gap

            scene_timings.append(
                {
                    "scene_id": scene["scene_id"],
                    "start": scene_start,
                    "end": cursor,
                    "duration": cursor - scene_start,
                }
            )

    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(VOICE_WAV),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(VOICE_MP3),
        ],
        check=True,
    )

    srt_blocks = []
    for index, item in enumerate(timeline, start=1):
        srt_blocks.append(
            f"{index}\n{srt_time(item['start'])} --> {srt_time(item['end'])}\n{item['text']}"
        )
    SRT_PATH.write_text("\n\n".join(srt_blocks) + "\n", encoding="utf-8")

    TIMING_PATH.write_text(
        json.dumps(
            {
                "voice": VOICE,
                "rate": RATE,
                "duration": cursor,
                "sentences": timeline,
                "scenes": scene_timings,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    SCRIPT_PATH.write_text(
        "\n\n".join(" ".join(scene["sentences"]) for scene in scenes) + "\n",
        encoding="utf-8",
    )
    print(f"Created {VOICE_WAV}")
    print(f"Duration: {cursor:.3f} seconds")
    print(f"Sentences: {len(timeline)}")


if __name__ == "__main__":
    asyncio.run(main())
