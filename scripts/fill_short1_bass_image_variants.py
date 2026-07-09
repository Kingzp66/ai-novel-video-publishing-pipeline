import json
import math
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


ROOT = Path(r"D:\ai-novel-video-generator\youtube short1 bass")


def cover_crop(image: Image.Image, width: int = 1080, height: int = 1920, shift_x: float = 0, shift_y: float = 0) -> Image.Image:
    src = image.convert("RGB")
    scale = max(width / src.width, height / src.height)
    resized = src.resize((math.ceil(src.width * scale), math.ceil(src.height * scale)), Image.Resampling.LANCZOS)
    max_x = resized.width - width
    max_y = resized.height - height
    left = int(max_x * (0.5 + shift_x))
    top = int(max_y * (0.45 + shift_y))
    left = max(0, min(max_x, left))
    top = max(0, min(max_y, top))
    return resized.crop((left, top, left + width, top + height))


def grade(image: Image.Image, index: int) -> Image.Image:
    img = image
    if index % 5 == 0:
        img = ImageOps.mirror(img)
    img = ImageEnhance.Color(img).enhance(0.92 + (index % 4) * 0.05)
    img = ImageEnhance.Contrast(img).enhance(1.02 + (index % 3) * 0.04)
    img = ImageEnhance.Brightness(img).enhance(0.96 + (index % 5) * 0.018)
    if index % 4 == 0:
        img = img.filter(ImageFilter.UnsharpMask(radius=1.4, percent=115, threshold=4))
    overlay = Image.new("RGB", img.size, (16, 24, 22))
    mask = Image.new("L", img.size, 0)
    # Subtle bottom vignette improves subtitle readability without making a card.
    for y in range(img.height):
        value = int(max(0, (y - img.height * 0.68) / (img.height * 0.32)) * 68)
        if value:
            ImageDraw = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).ImageDraw
            break
    from PIL import ImageDraw as PILImageDraw

    draw = PILImageDraw.Draw(mask)
    for y in range(img.height):
        value = int(max(0, (y - img.height * 0.70) / (img.height * 0.30)) * 70)
        if value:
            draw.line([(0, y), (img.width, y)], fill=value)
    return Image.composite(overlay, img, mask)


def main() -> None:
    shorts = ROOT / "output" / "shorts"
    report = []
    for manifest_path in sorted(shorts.glob("short_*/short_*_manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        folder = manifest_path.parent / "images"
        existing = sorted([p for p in folder.glob("*.png") if p.stat().st_size > 0])
        if not existing:
            raise FileNotFoundError(f"No base images for {manifest['short_id']}")
        base_images = [Image.open(path).convert("RGB") for path in existing]
        for scene in manifest["scenes"]:
            target = folder / scene["image"]
            if target.exists() and target.stat().st_size > 0:
                report.append({"image": str(target), "source": "generated"})
                continue
            idx = int(scene["index"])
            base = base_images[(idx - 1) % len(base_images)]
            shift_x = ((idx % 3) - 1) * 0.08
            shift_y = ((idx % 4) - 1.5) * 0.035
            frame = cover_crop(base, shift_x=shift_x, shift_y=shift_y)
            frame = grade(frame, idx)
            frame.save(target, "PNG", compress_level=1)
            report.append({"image": str(target), "source": f"local_variant_from_{existing[(idx - 1) % len(existing)].name}"})
    (shorts / "image_source_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"images": len(report), "report": str(shorts / "image_source_report.json")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
