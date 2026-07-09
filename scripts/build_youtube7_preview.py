import argparse
import asyncio
import csv
import json
import math
import os
import re
import shutil
import subprocess
import time
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from textwrap import wrap
from urllib.request import urlopen

import edge_tts
from dotenv import load_dotenv
from ftfy import fix_text
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "youtube7 drug doctor" / "cartel_doctor_video_package_v1"
PYTHON = Path(r"C:\Users\11847\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
VOICE = "en-US-BrianNeural"
VOICE_RATE = "-3%"
FPS = 30
WIDTH = 1920
HEIGHT = 1080
SAMPLE_RATE = 48000
SENTENCE_GAP = 0.18
SCENE_GAP = 0.45
STORY_IMAGES_TO_GENERATE = 2
SCHNELL_MODEL = "black-forest-labs/flux-schnell"
KONTEXT_MODEL = "black-forest-labs/flux-kontext-pro"


@dataclass
class Scene:
    output_index: int
    scene_id: str
    level: str
    type: str
    visual_summary: str
    camera: str
    prompt: str = ""
    title_text: str = ""
    sentences: list[str] | None = None


def run(command: list[str], label: str, cwd: Path = ROOT) -> None:
    print(f"[{label}] {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
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


def clean_text(text: str) -> str:
    text = fix_text(text)
    replacements = {
        "\u2014": " - ",
        "\u2013": " - ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "Culiacan": "Culiacan",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    text = clean_text(text)
    text = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part.strip() for part in parts if part.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_prompts() -> dict[str, dict[str, str]]:
    prompts: dict[str, dict[str, str]] = {}
    for line in (PROJECT / "image_prompts.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            prompts[item["scene_id"]] = item
    return prompts


def load_scenes() -> list[Scene]:
    prompts = load_prompts()
    rows = read_csv(PROJECT / "scenes.csv")
    scenes: list[Scene] = []
    for index, row in enumerate(rows, start=1):
        item = prompts.get(row["scene_id"], {})
        scenes.append(
            Scene(
                output_index=index,
                scene_id=row["scene_id"],
                level=row["level"],
                type=row["type"],
                visual_summary=row["visual_summary"],
                camera=row.get("camera") or row.get("camera_motion") or "slow push in",
                prompt=item.get("visual_prompt", ""),
                title_text=item.get("text_overlay", ""),
            )
        )
    return scenes


def parse_script_by_level() -> tuple[list[str], dict[str, list[str]]]:
    script = clean_text((PROJECT / "full_script.txt").read_text(encoding="utf-8"))
    script = re.sub(r"^TITLE:.*?$", "", script, flags=re.MULTILINE)
    script = script.replace("OPENING DISCLAIMER", "\nOPENING DISCLAIMER\n")
    script = script.replace("VIDEO HOOK", "\nVIDEO HOOK\n")
    level_pattern = re.compile(r"^LEVEL\s+(\d+):\s+(.+)$", re.MULTILINE)
    matches = list(level_pattern.finditer(script))
    preface = script[: matches[0].start()] if matches else script
    preface = re.sub(r"\bOPENING DISCLAIMER\b|\bVIDEO HOOK\b", "", preface)
    intro = split_sentences(preface)
    levels: dict[str, list[str]] = {}
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(script)
        levels[f"Level {match.group(1)}"] = split_sentences(script[start:end])
    return intro, levels


def distribute_sentences(sentences: list[str], count: int) -> list[list[str]]:
    if count <= 0:
        return []
    buckets: list[list[str]] = [[] for _ in range(count)]
    if not sentences:
        return buckets
    weights = [max(1, len(sentence.split())) for sentence in sentences]
    total = sum(weights)
    target = total / count
    bucket = 0
    current = 0
    for sentence, weight in zip(sentences, weights):
        if bucket < count - 1 and current >= target and buckets[bucket]:
            bucket += 1
            current = 0
        buckets[bucket].append(sentence)
        current += weight
    return buckets


def attach_narration(scenes: list[Scene]) -> None:
    _, levels = parse_script_by_level()
    by_level: dict[str, list[Scene]] = {}
    for scene in scenes:
        scene.sentences = []
        if scene.type == "title_card":
            text = scene.title_text.replace("\n", ". ")
            if scene.scene_id == "title_00":
                scene.sentences = ["Your Life as a Cartel Doctor."]
            elif text:
                scene.sentences = [text + "."]
        else:
            by_level.setdefault(scene.level, []).append(scene)

    for level, story_scenes in by_level.items():
        chunks = distribute_sentences(levels.get(level, []), len(story_scenes))
        for scene, sentences in zip(story_scenes, chunks):
            scene.sentences = sentences or [scene.visual_summary.rstrip(".") + "."]


def safe_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
    ]:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


def create_placeholder(path: Path, scene: Scene) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#20252a")
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        shade = int(26 + 22 * (y / HEIGHT))
        draw.line([(0, y), (WIDTH, y)], fill=(shade, shade + 6, shade + 10))
    accent = "#586f73" if scene.output_index % 2 else "#836d4f"
    draw.rounded_rectangle((180, 170, 1740, 850), radius=36, outline=accent, width=4)
    draw.ellipse((430, 310, 590, 470), fill="#d8d1c2", outline="#111111", width=6)
    draw.rectangle((465, 470, 555, 670), fill="#6b8582", outline="#111111", width=6)
    draw.line((505, 500, 350, 650), fill="#111111", width=8)
    draw.line((515, 500, 680, 650), fill="#111111", width=8)
    draw.line((485, 670, 430, 805), fill="#111111", width=8)
    draw.line((535, 670, 600, 805), fill="#111111", width=8)
    draw.ellipse((480, 380, 492, 392), fill="#111111")
    draw.ellipse((530, 380, 542, 392), fill="#111111")
    draw.arc((485, 395, 540, 435), 20, 160, fill="#111111", width=4)
    title_font = safe_font(52)
    body_font = safe_font(36)
    small_font = safe_font(30)
    draw.text((1440, 86), "PLACEHOLDER", fill="#d6c492", font=small_font)
    draw.text((220, 210), scene.scene_id, fill="#ffffff", font=title_font)
    lines = fit_text(draw, scene.visual_summary, body_font, 940)
    y = 300
    for line in lines[:6]:
        draw.text((720, y), line, fill="#f2f0ea", font=body_font)
        y += 48
    draw.text((220, 890), "Style approval preview - final art will replace this frame", fill="#aeb8ba", font=small_font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)


def normalize_png(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        image = image.convert("RGB")
        image = ImageOps_contain_crop(image, WIDTH, HEIGHT)
        image.save(target, "PNG", optimize=True)


def ImageOps_contain_crop(image: Image.Image, width: int, height: int) -> Image.Image:
    ratio = max(width / image.width, height / image.height)
    resized = image.resize((math.ceil(image.width * ratio), math.ceil(image.height * ratio)), Image.Resampling.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def save_replicate_output(output, target: Path) -> None:
    if isinstance(output, list):
        output = output[0]
    temp = target.with_suffix(".download")
    if hasattr(output, "read"):
        temp.write_bytes(output.read())
    elif isinstance(output, str) and output.startswith(("http://", "https://")):
        with urlopen(output) as response:
            temp.write_bytes(response.read())
    elif isinstance(output, str):
        temp.write_bytes(Path(output).read_bytes())
    else:
        raise TypeError(f"Unsupported Replicate output: {type(output)!r}")
    normalize_png(temp, target)
    temp.unlink(missing_ok=True)


def generate_story_image(scene: Scene, target: Path, reference: Path | None) -> None:
    import replicate

    safe_overrides = {
        "story_032": (
            "16:9 widescreen, simple 2D cartoon YouTube story style. Dr. Mateo stands alone in a dim clinic hallway, "
            "his face tense and hollow, while an empty examination room is visible behind him. The scene implies a "
            "morally devastating case without showing any patient, injury, blood, weapon, violence, or procedure. "
            "Muted blue-gray, beige, hospital green and dim amber palette, clean black outlines, flat cel shading, "
            "no text, no signs, no logos, no gore, no medical procedure, no minors shown."
        ),
        "story_034": (
            "16:9 widescreen, simple 2D cartoon YouTube story style. Dr. Mateo sits alone in a staged office, facing "
            "a glowing laptop video call screen that shows only soft abstract silhouettes and no identifiable family "
            "members. His posture is rigid and anxious, suggesting emotional pressure and isolation. Muted palette, "
            "flat cel shading, no readable interface, no text, no children, no threats shown, no violence."
        ),
        "story_037": (
            "16:9 widescreen, simple 2D cartoon YouTube story style. Dr. Mateo wakes in a quiet estate clinic bed, "
            "pale and exhausted, while a stern boss figure stands at a distance beside the doorway. The image is about "
            "control and disappointment, not injury. No medical crisis shown, no self-harm, no blood, no tools, no text."
        ),
        "story_043": (
            "16:9 widescreen, simple 2D cartoon YouTube story style. Dr. Mateo sits alone in a dark room watching "
            "blurred news screens and anonymous papers on a desk, realizing his work only delayed a larger machine. "
            "Show emotional defeat through posture and lighting only. No bodies, no injuries, no readable news text."
        ),
        "story_045": (
            "16:9 widescreen, simple 2D cartoon YouTube story style. Dr. Mateo stands in a quiet visiting room with "
            "empty chairs and a family photograph turned face-down on the table, his expression frozen. Show loss and "
            "distance without depicting children. No minors, no text, no violence."
        ),
        "story_046": (
            "16:9 widescreen, simple 2D cartoon YouTube story style. Dr. Mateo stares blankly at abstract medical "
            "charts made of unreadable shapes on a wall, emotionally detached and exhausted. The clinic is clean and "
            "quiet. No patients, no anatomy details, no injuries, no procedures, no readable text."
        ),
        "story_047": (
            "16:9 widescreen, simple 2D cartoon YouTube story style. Dr. Mateo addresses a small group of shadowed "
            "adult doctors in a hidden classroom with blank boards and closed supply cabinets, tense and morally weary. "
            "No text, no procedures, no injuries, no weapons."
        ),
        "story_052": (
            "16:9 widescreen, simple 2D cartoon YouTube story style. Dr. Mateo studies an escape plan on a desk with "
            "a blank passport-like booklet, hidden cash, an unlabeled map, and a face-down family photo. Show tension "
            "and longing without readable text or children."
        ),
        "story_054": (
            "16:9 widescreen, simple 2D cartoon YouTube story style. Dr. Mateo stands in a panic-filled office with "
            "scattered blank papers, a muted television glow, and guards moving as silhouettes outside frosted glass. "
            "Show fear and secrecy only. No death, no bodies, no readable text, no violence."
        ),
        "story_055": (
            "16:9 widescreen, simple 2D cartoon YouTube story style. Paranoid and sleepless, Dr. Mateo sits on the edge "
            "of a bed in a guarded room, watching the door with untouched food on a tray nearby. No blade, no weapon, "
            "no self-harm, no readable text."
        ),
        "story_056": (
            "16:9 widescreen, simple 2D cartoon YouTube story style. During a tense crackdown, Dr. Mateo stands frozen "
            "beside a clinic monitor showing abstract unreadable shapes, realizing a small mistake could end everything. "
            "No injuries, no procedures, no weapons, no text."
        ),
        "story_057": (
            "16:9 widescreen, simple 2D cartoon YouTube story style. Dr. Mateo stands before the boss in a quiet estate "
            "office, pleading with tense hands while a closed door and dim window symbolize family distance. No children "
            "shown, no threats, no weapons, no text."
        ),
        "story_058": (
            "16:9 widescreen, simple 2D cartoon YouTube story style. Dr. Mateo stands alone under surgical lights like "
            "a tired machine, surrounded by empty clean tables and cold equipment. Show emotional numbness only. No "
            "patients, no injuries, no procedures, no blood, no text."
        ),
        "story_061": (
            "16:9 widescreen, simple 2D cartoon YouTube story style. Dr. Mateo sits at a desk with torn-up escape notes "
            "and blank papers, then pushes them away, exhausted and trapped. The mood is despair without depicting "
            "self-harm or death. No weapons, no text, no readable papers."
        ),
    }
    prompt = safe_overrides.get(scene.scene_id) or (
        scene.prompt
        + " Keep the lower 18 percent uncluttered for English movie subtitles. "
        + "Do not include text, captions, logos, watermarks, or readable signs."
    )
    if reference and reference.exists():
        model = KONTEXT_MODEL
        model_input = {
            "prompt": (
                f"Create a new 16:9 scene based on the reference image. Preserve Dr. Mateo's visual identity, "
                f"the same simple 2D cartoon YouTube story style, line weight, flat cel shading, muted palette, "
                f"and non-graphic tone. Scene direction: {prompt}"
            ),
            "input_image": reference,
            "aspect_ratio": "16:9",
            "output_format": "png",
            "prompt_upsampling": False,
            "seed": 900 + scene.output_index,
        }
    else:
        model = SCHNELL_MODEL
        model_input = {
            "prompt": prompt,
            "aspect_ratio": "16:9",
            "output_format": "png",
            "output_quality": 95,
            "num_outputs": 1,
            "num_inference_steps": 4,
            "go_fast": True,
        }
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            print(f"Generating {target.name} with {model}", flush=True)
            output = replicate.run(model, input=model_input)
            save_replicate_output(output, target)
            return
        except Exception as exc:
            last_error = exc
            wait = 10 * attempt
            print(f"Retry {target.name} in {wait}s: {exc}", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Failed to generate {target.name}: {last_error}") from last_error


def looks_like_placeholder(path: Path) -> bool:
    return path.exists() and path.stat().st_size < 150_000


def prepare_images(scenes: list[Scene], regenerate_first_two: bool = False, generate_all_story_images: bool = False) -> None:
    load_dotenv(ROOT / ".env")
    if not os.environ.get("REPLICATE_API_TOKEN"):
        raise SystemExit("Missing REPLICATE_API_TOKEN in .env or environment.")
    images = PROJECT / "images"
    images.mkdir(parents=True, exist_ok=True)
    generated_story_count = 0
    first_reference: Path | None = None
    for scene in scenes:
        target = images / f"scene_{scene.output_index:02}.png"
        if scene.type == "title_card":
            source = PROJECT / "title_cards" / f"{scene.scene_id}.png"
            if source.exists() and (not target.exists() or target.stat().st_size == 0):
                normalize_png(source, target)
            continue
        if target.exists() and not regenerate_first_two and not (generate_all_story_images and looks_like_placeholder(target)):
            if generated_story_count < STORY_IMAGES_TO_GENERATE:
                generated_story_count += 1
                if first_reference is None:
                    first_reference = target
            continue
        if generated_story_count < STORY_IMAGES_TO_GENERATE or generate_all_story_images:
            if regenerate_first_two or not target.exists():
                generate_story_image(scene, target, first_reference)
            elif generate_all_story_images and looks_like_placeholder(target):
                generate_story_image(scene, target, first_reference)
            generated_story_count += 1
            if first_reference is None:
                first_reference = target
        elif not target.exists() or target.stat().st_size == 0:
            create_placeholder(target, scene)


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


async def synthesize(text: str, path: Path) -> None:
    communicator = edge_tts.Communicate(text, VOICE, rate=VOICE_RATE)
    await communicator.save(str(path))


def to_wav(mp3_path: Path, wav_path: Path) -> None:
    run(
        [
            "ffmpeg",
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
        f"Convert {mp3_path.name}",
    )


def read_wav(path: Path) -> tuple[bytes, float]:
    with wave.open(str(path), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
        duration = handle.getnframes() / handle.getframerate()
    return frames, duration


async def build_audio_and_subtitles(scenes: list[Scene]) -> dict:
    audio = PROJECT / "audio"
    subtitles = PROJECT / "subtitles"
    segment_dir = audio / "voice_segments"
    wav_dir = audio / "voice_wav"
    for folder in [audio, subtitles, segment_dir, wav_dir]:
        folder.mkdir(parents=True, exist_ok=True)

    flat: list[dict] = []
    sequence = 0
    for scene in scenes:
        for sentence_index, sentence in enumerate(scene.sentences or [], start=1):
            sequence += 1
            flat.append(
                {
                    "sequence": sequence,
                    "scene_index": scene.output_index,
                    "scene_id": scene.scene_id,
                    "sentence_index": sentence_index,
                    "text": sentence,
                }
            )

    for item in flat:
        stem = f"segment_{item['sequence']:03d}"
        mp3 = segment_dir / f"{stem}.mp3"
        wav = wav_dir / f"{stem}.wav"
        if not mp3.exists() or mp3.stat().st_size == 0:
            print(f"Synthesizing {stem}: {item['text']}", flush=True)
            await synthesize(item["text"], mp3)
        if not wav.exists() or wav.stat().st_size == 0:
            to_wav(mp3, wav)

    voice_wav = audio / "voiceover_edge_brian_synced.wav"
    silence = b"\x00\x00"
    timeline = []
    scene_timings = []
    cursor = 0.0
    with wave.open(str(voice_wav), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        for scene in scenes:
            scene_start = cursor
            scene_items = [item for item in flat if item["scene_index"] == scene.output_index]
            for local_index, item in enumerate(scene_items):
                wav = wav_dir / f"segment_{item['sequence']:03d}.wav"
                frames, duration = read_wav(wav)
                start = cursor
                output.writeframes(frames)
                cursor += duration
                end = cursor
                timeline.append({**item, "start": start, "end": end, "duration": duration})
                gap = SCENE_GAP if local_index == len(scene_items) - 1 else SENTENCE_GAP
                output.writeframes(silence * round(gap * SAMPLE_RATE))
                cursor += gap
            if not scene_items:
                output.writeframes(silence * round(1.5 * SAMPLE_RATE))
                cursor += 1.5
            scene_timings.append(
                {
                    "scene_index": scene.output_index,
                    "scene_id": scene.scene_id,
                    "start": scene_start,
                    "end": cursor,
                    "duration": max(1.0, cursor - scene_start),
                }
            )

    voice_mp3 = audio / "voiceover_edge_brian_synced.mp3"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(voice_wav), "-c:a", "libmp3lame", "-b:a", "192k", str(voice_mp3)], "Encode voice")

    srt_blocks = []
    for index, item in enumerate(timeline, start=1):
        caption = "\n".join(wrap(item["text"], width=44, break_long_words=False))
        srt_blocks.append(f"{index}\n{srt_time(item['start'])} --> {srt_time(item['end'])}\n{caption}")
    (subtitles / "subtitles_en.srt").write_text("\n\n".join(srt_blocks) + "\n", encoding="utf-8")

    ass_lines = [
        "[Script Info]",
        "Title: Cartel Doctor English Subtitles",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: English,Arial,42,&H00FFFFFF,&H00FFFFFF,&H00000000,&H70000000,0,0,0,0,100,100,0,0,1,2.6,0.5,2,130,130,58,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for item in timeline:
        caption = r"\N".join(ass_escape(line) for line in wrap(item["text"], width=48, break_long_words=False))
        ass_lines.append(
            f"Dialogue: 0,{ass_time(item['start'])},{ass_time(item['end'])},English,,0,0,0,,{caption}"
        )
    ass_path = subtitles / "subtitles_en.ass"
    ass_path.write_text("\n".join(ass_lines) + "\n", encoding="utf-8")

    timing = {"voice": VOICE, "rate": VOICE_RATE, "duration": cursor, "sentences": timeline, "scenes": scene_timings}
    (subtitles / "timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")
    (subtitles / "narration_en.txt").write_text(
        "\n\n".join(" ".join(scene.sentences or []) for scene in scenes) + "\n",
        encoding="utf-8",
    )
    return {"voice": voice_mp3, "ass": ass_path, "timing": timing}


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
    return (
        "scale=1920:1080:force_original_aspect_ratio=increase,"
        "crop=1920:1080,"
        f"zoompan={patterns[(index - 1) % len(patterns)]}:d={frames}:s=1920x1080:fps={FPS},"
        "format=yuv420p"
    )


def render_clips(timing: dict) -> Path:
    output = PROJECT / "output"
    clips_dir = output / "_clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    for item in timing["scenes"]:
        index = int(item["scene_index"])
        image = PROJECT / "images" / f"scene_{index:02}.png"
        clip = clips_dir / f"scene_{index:02}.mp4"
        duration = max(1.0, float(item["duration"]))
        frames = max(1, round(duration * FPS))
        if not clip.exists() or clip.stat().st_size == 0:
            run(
                [
                    "ffmpeg",
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
                ],
                f"Render scene {index:02}",
            )
        clips.append(clip)
    concat_file = clips_dir / "clips.txt"
    concat_file.write_text("\n".join(f"file '{clip.resolve().as_posix()}'" for clip in clips) + "\n", encoding="utf-8")
    silent_video = clips_dir / "silent_video.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(silent_video)], "Concat clips")
    return silent_video


def ensure_music(duration: float) -> Path:
    audio = PROJECT / "audio"
    target = audio / "background_music.mp3"
    candidates = [
        target,
        ROOT / "MC VEDIO" / "audio" / "background_music.mp3",
        ROOT / "youtube6" / "audio" / "background_music.mp3",
        ROOT / "youtube5" / "audio" / "background_music.mp3",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size > 0:
            if candidate.resolve() != target.resolve():
                shutil.copy2(candidate, target)
            return target
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=82:sample_rate=44100",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=color=pink:amplitude=0.10:sample_rate=44100",
            "-filter_complex",
            f"[0:a]volume=0.018[a0];[1:a]volume=0.018[a1];[a0][a1]amix=inputs=2:duration=longest,atrim=0:{duration:.3f},afade=t=in:st=0:d=3,afade=t=out:st={max(duration - 4, 0):.3f}:d=4",
            "-c:a",
            "libmp3lame",
            str(target),
        ],
        "Generate background music",
    )
    return target


def burn_and_mux(silent_video: Path, voice: Path, ass: Path, duration: float) -> Path:
    output = PROJECT / "output" / "final_youtube_video.mp4"
    music = ensure_music(duration)
    escaped_ass = ass.resolve().as_posix().replace(":", r"\:")
    filter_graph = (
        f"[0:v]ass='{escaped_ass}'[v];"
        "[1:a]volume=1.0,aformat=channel_layouts=stereo,asplit=2[voice_mix][voice_sc];"
        "[2:a]volume=0.075[bg];"
        "[bg][voice_sc]sidechaincompress=threshold=0.018:ratio=10:attack=20:release=450[ducked];"
        "[voice_mix][ducked]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[aout]"
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(silent_video),
            "-i",
            str(voice),
            "-stream_loop",
            "-1",
            "-i",
            str(music),
            "-filter_complex",
            filter_graph,
            "-map",
            "[v]",
            "-map",
            "[aout]",
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
            "-shortest",
            "-movflags",
            "+faststart",
            str(output),
        ],
        "Mux final video",
    )
    return output


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regenerate-first-two", action="store_true", help="Regenerate the first two story images.")
    parser.add_argument("--generate-all-story-images", action="store_true", help="Replace placeholder story frames with Replicate images.")
    parser.add_argument("--skip-images", action="store_true", help="Skip image preparation.")
    parser.add_argument("--skip-audio", action="store_true", help="Reuse existing timing/audio files.")
    args = parser.parse_args()

    scenes = load_scenes()
    attach_narration(scenes)
    if not args.skip_images:
        prepare_images(
            scenes,
            regenerate_first_two=args.regenerate_first_two,
            generate_all_story_images=args.generate_all_story_images,
        )
    if args.skip_audio:
        timing = json.loads((PROJECT / "subtitles" / "timing.json").read_text(encoding="utf-8"))
        voice = PROJECT / "audio" / "voiceover_edge_brian_synced.mp3"
        ass = PROJECT / "subtitles" / "subtitles_en.ass"
    else:
        result = await build_audio_and_subtitles(scenes)
        timing = result["timing"]
        voice = result["voice"]
        ass = result["ass"]
    silent_video = render_clips(timing)
    final = burn_and_mux(silent_video, voice, ass, timing["duration"])
    print(f"FINAL={final}")


if __name__ == "__main__":
    asyncio.run(main())
