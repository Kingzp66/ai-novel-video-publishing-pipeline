"""
Create simple placeholder video clips for every scene.

This first version does not call any paid AI video API. Instead, it creates a
plain 1080x1920 image for each scene, writes the scene number and caption on
top, then asks FFmpeg to turn that image into an MP4 clip.
"""

import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EPISODE_PATH = PROJECT_ROOT / "prompts" / "episode_01.json"
VIDEO_DIR = PROJECT_ROOT / "assets" / "videos"

WIDTH = 1080
HEIGHT = 1920


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


def load_font(size):
    """Load a readable Windows font, with a Pillow default as a fallback."""
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    if font_path.exists():
        return ImageFont.truetype(str(font_path), size=size)

    return ImageFont.load_default()


def wrap_text(draw, text, font, max_width):
    """Split text into multiple lines so it fits inside the video frame."""
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        left, top, right, bottom = draw.textbbox((0, 0), test_line, font=font)
        line_width = right - left

        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def draw_centered_text(draw, lines, font, center_y, fill):
    """Draw several text lines centered horizontally around a y position."""
    line_height = font.size + 18 if hasattr(font, "size") else 60
    total_height = len(lines) * line_height
    y = center_y - total_height / 2

    for line in lines:
        left, top, right, bottom = draw.textbbox((0, 0), line, font=font)
        x = (WIDTH - (right - left)) / 2
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height


def create_placeholder_image(scene, image_path):
    """Create one 1080x1920 PNG title card for a scene."""
    image = Image.new("RGB", (WIDTH, HEIGHT), color=(22, 24, 32))
    draw = ImageDraw.Draw(image)

    title_font = load_font(86)

    # Add a few simple rectangles so each card has some visual depth.
    draw.rectangle((0, 0, WIDTH, HEIGHT), fill=(22, 24, 32))
    draw.rectangle((70, 120, WIDTH - 70, HEIGHT - 120), outline=(90, 160, 255), width=6)
    draw.rectangle((100, 150, WIDTH - 100, HEIGHT - 150), outline=(255, 210, 110), width=3)

    scene_title = f"Scene {scene['id']:02}"

    draw_centered_text(draw, [scene_title], title_font, center_y=620, fill=(255, 255, 255))

    image.save(image_path)


def create_video_from_image(ffmpeg, image_path, output_path, duration):
    """Use FFmpeg to convert one still image into one MP4 video clip."""
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-t",
        str(duration),
        "-vf",
        "format=yuv420p",
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]

    subprocess.run(command, check=True)


def main():
    """Read the episode JSON and create one placeholder MP4 per scene."""
    ffmpeg = find_ffmpeg()

    with EPISODE_PATH.open("r", encoding="utf-8") as file:
        episode = json.load(file)

    VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    for scene in episode["scenes"]:
        image_path = VIDEO_DIR / f"scene_{scene['id']:02}.png"
        clip_path = VIDEO_DIR / f"scene_{scene['id']:02}.mp4"

        create_placeholder_image(scene, image_path)
        create_video_from_image(ffmpeg, image_path, clip_path, scene["duration"])
        image_path.unlink(missing_ok=True)

        print(f"Created clip: {clip_path}")


if __name__ == "__main__":
    main()
