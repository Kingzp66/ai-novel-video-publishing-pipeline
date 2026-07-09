import argparse
import base64
import json
import time
from pathlib import Path

from PIL import Image


ROOT = Path(r"D:\ai-novel-video-generator\youtube short1 bass")
REPO = Path(r"D:\ai-novel-video-generator")


def load_env() -> None:
    import os

    env_path = REPO / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def normalize_prompt(raw: str) -> str:
    prompt = raw.replace("Vertical 9:16 composition,", "").strip()
    return (
        "Create a vertical 9:16 image for a short-form fishing education video.\n"
        "Style: vintage hand-drawn fishing instructional illustration, realistic freshwater manual art, "
        "clean accurate line art, lightly colored natural tones, beige off-white paper background, clear and believable, "
        "not abstract, not surreal, not symbolic.\n"
        "Important realism: realistic largemouth bass anatomy, realistic fishing rods, realistic boat proportions, "
        "physically possible water, weather, and shoreline details.\n"
        "Character consistency when the angler appears: middle-aged male freshwater angler, olive-green fishing jacket, "
        "tan fishing cap, dark waterproof pants, simple outdoor boots, calm focused expression, realistic proportions.\n"
        f"Scene: {prompt}\n"
        "Composition: vertical portrait frame, main subject centered, clean lower safe area for subtitles.\n"
        "Avoid: absolutely no text anywhere, no letters, no numbers, no labels, no handwritten marks, no chart words, "
        "no logos, no subtitles, no watermark, no readable signs, no black cards, no UI, fantasy elements, "
        "extra limbs, deformed hands, impossible fishing gear, distorted fish."
    )


def iter_missing(short_id: str | None):
    root = ROOT / "output" / "shorts"
    for manifest_path in sorted(root.glob("short_*/short_*_manifest.json")):
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if short_id and data["short_id"] != short_id:
            continue
        folder = manifest_path.parent / "images"
        folder.mkdir(parents=True, exist_ok=True)
        for scene in data["scenes"]:
            out = folder / scene["image"]
            if out.exists() and out.stat().st_size > 0:
                continue
            yield data["short_id"], scene, out


def write_image_from_response(item, out: Path) -> None:
    if getattr(item, "b64_json", None):
        raw = base64.b64decode(item.b64_json)
    elif getattr(item, "url", None):
        import requests

        raw = requests.get(item.url, timeout=120).content
    else:
        raise RuntimeError("Image response did not include b64_json or url")
    temp = out.with_suffix(".raw.png")
    temp.write_bytes(raw)
    with Image.open(temp) as image:
        image.convert("RGB").resize((1080, 1920), Image.Resampling.LANCZOS).save(out, "PNG", optimize=True)
    temp.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--short-id")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    load_env()
    from openai import OpenAI

    client = OpenAI()
    jobs = list(iter_missing(args.short_id))
    if args.limit:
        jobs = jobs[: args.limit]
    print(f"missing jobs: {len(jobs)}", flush=True)
    for index, (short_id, scene, out) in enumerate(jobs, start=1):
        started = time.time()
        prompt = normalize_prompt(scene["visual_prompt"])
        result = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1536",
            quality="medium",
            n=1,
        )
        write_image_from_response(result.data[0], out)
        print(f"{index}/{len(jobs)} saved {out} in {time.time() - started:.1f}s", flush=True)


if __name__ == "__main__":
    main()
